from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import logging
import os
import re
import socket
import shutil
import subprocess
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import uvicorn


# Le o .env uma unica vez na inicializacao.
load_dotenv()
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = str(os.getenv("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")).strip()


# Log so no terminal (sem arquivo) - simples o suficiente para uso local.
logger = logging.getLogger("youtube-transcriber")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False


HOST = "127.0.0.1"
try:
    PORT = int(os.getenv("PORT", "8000"))
except ValueError:
    PORT = 8000


def is_port_free(host: str, port: int) -> bool:
    """Returns True if the port is free on the given host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex((host, port)) != 0


def choose_available_port(host: str, initial_port: int, attempts: int = 20) -> int:
    """Tries the initial port and, if taken, looks for the next free one."""
    if is_port_free(host, initial_port):
        return initial_port

    for offset in range(1, attempts + 1):
        candidate_port = initial_port + offset
        if is_port_free(host, candidate_port):
            return candidate_port

    return initial_port


ROOT_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT_DIR / "public"
OUTPUT_DIR = ROOT_DIR / "output"
AUDIO_DIR = OUTPUT_DIR / "audio"
VIDEO_DIR = OUTPUT_DIR / "video"
TRANSCRIPTS_DIR = OUTPUT_DIR / "transcripts"
TEMP_DIR = OUTPUT_DIR / "temp"
WHISPER_MODEL = str(os.getenv("WHISPER_MODEL", "small")).strip() or "small"
WHISPER_DEVICE = str(os.getenv("WHISPER_DEVICE", "cpu")).strip() or "cpu"
WHISPER_COMPUTE_TYPE = str(os.getenv("WHISPER_COMPUTE_TYPE", "int8")).strip() or "int8"
USE_OLLAMA_REVIEW = str(os.getenv("USE_OLLAMA_REVIEW", "1")).strip().lower() not in {"0", "false", "no", "off"}
OLLAMA_BASE_URL = str(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).strip() or "http://127.0.0.1:11434"
OLLAMA_MODEL = str(os.getenv("OLLAMA_MODEL", "llama3.1:8b")).strip() or "llama3.1:8b"
try:
    OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
except ValueError:
    OLLAMA_TIMEOUT = 120
# Carregado sob demanda (ver get_transcription_model) - o modelo do
# faster-whisper e pesado pra carregar, entao so acontece uma vez por
# processo e fica em cache aqui.
TRANSCRIPTION_MODEL: Any | None = None


for folder in [AUDIO_DIR, VIDEO_DIR, TRANSCRIPTS_DIR, TEMP_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


class ProcessRequestBody(BaseModel):
    action: str = ""
    urls: list[str] | str = []
    language: str | None = None
    review_text: bool = True


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("--- YouTube Transcriber interface starting ---")
    logger.info("=" * 72)
    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir:
        logger.info("FFmpeg detected at: %s", ffmpeg_dir)
    else:
        logger.warning("FFmpeg not detected (audio and video may fail)")
    logger.info(
        "Local transcription with faster-whisper: model=%s, device=%s, compute=%s",
        WHISPER_MODEL,
        WHISPER_DEVICE,
        WHISPER_COMPUTE_TYPE,
    )
    if USE_OLLAMA_REVIEW:
        logger.info("Text review: Ollama enabled at %s with model %s", OLLAMA_BASE_URL, OLLAMA_MODEL)
    else:
        logger.info("Text review: local rule-based mode enabled")
    logger.info("Frontend available at: http://%s:%s", HOST, PORT)
    logger.info("=" * 72)
    yield


app = FastAPI(title="youtube-transcriber", lifespan=lifespan)


def log_json(url: str, title: str, destination_folder: Path, status: str, detail: str = "") -> None:
    """Logs a structured JSON entry per processed item."""
    entry = {
        "downloading_url": url,
        "file_title": title,
        "destination_folder": str(destination_folder),
        "status": status,
    }
    if detail:
        entry["detail"] = detail
    logger.info(json.dumps(entry, ensure_ascii=False))


def get_ffmpeg_dir() -> str | None:
    """Returns the ffmpeg/ffprobe folder, or None if not found on PATH."""
    env_path = os.getenv("FFMPEG_DIR", "").strip()
    if env_path:
        env_dir = Path(env_path).expanduser().resolve()
        if (env_dir / "ffmpeg.exe").exists() and (env_dir / "ffprobe.exe").exists():
            return str(env_dir)

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if not ffmpeg_path or not ffprobe_path:
        # Sem ffmpeg no PATH: procura um build portatil em tools/ (ex.: o
        # zip "ffmpeg-essentials" extraido ali), pegando o mais recente se
        # houver mais de uma versao baixada.
        tools_dir = ROOT_DIR / "tools"
        if tools_dir.exists():
            builds = sorted(
                [item for item in tools_dir.iterdir() if item.is_dir() and item.name.lower().startswith("ffmpeg")],
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for build in builds:
                bin_dir = build / "bin"
                if (bin_dir / "ffmpeg.exe").exists() and (bin_dir / "ffprobe.exe").exists():
                    return str(bin_dir.resolve())
        return None
    return str(Path(ffmpeg_path).resolve().parent)


def get_js_runtime() -> dict | None:
    """Enables Node.js if present (helps yt-dlp's YouTube extraction)."""
    node_path = shutil.which("node")
    if not node_path:
        return None
    return {"node": {"path": node_path}}


def get_ffmpeg_binary(ffmpeg_dir: str | None) -> str:
    """Returns the ffmpeg executable path."""
    if ffmpeg_dir:
        folder = Path(ffmpeg_dir)
        windows_candidate = folder / "ffmpeg.exe"
        if windows_candidate.exists():
            return str(windows_candidate)
        candidate = folder / "ffmpeg"
        if candidate.exists():
            return str(candidate)

    path = shutil.which("ffmpeg")
    if path:
        return path

    raise RuntimeError("ffmpeg not found to prepare audio for transcription")


def load_audio_samples(audio_path: Path, ffmpeg_dir: str) -> Any:
    """Converts audio to mono 16kHz PCM and returns a float32 array (faster-whisper's expected input)."""
    import numpy as np

    ffmpeg_binary = get_ffmpeg_binary(ffmpeg_dir)
    command = [
        ffmpeg_binary,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="ignore").strip() or "Failed to convert audio with ffmpeg"
        raise RuntimeError(detail)
    if not result.stdout:
        raise RuntimeError("Could not read audio for transcription")

    audio_pcm = np.frombuffer(result.stdout, dtype=np.int16)
    if audio_pcm.size == 0:
        raise RuntimeError("Audio is empty after PCM conversion")

    return (audio_pcm.astype("float32") / 32768.0).copy()


def format_readable_time(seconds: float) -> str:
    """Formats seconds as HH:MM:SS.mmm."""
    value = max(0.0, float(seconds or 0.0))
    total_ms = int(round(value * 1000))
    hours, remainder = divmod(total_ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def review_text_with_rules(text: str) -> str:
    """Applies simple readability fixes to the transcribed text (used as a fallback when Ollama is off/unavailable)."""
    reviewed = str(text or "").strip()
    if not reviewed:
        return reviewed

    reviewed = re.sub(r"\s+", " ", reviewed)
    reviewed = re.sub(r"\s+([,.;:!?])", r"\1", reviewed)
    reviewed = re.sub(r"([,.;:!?])([^\s])", r"\1 \2", reviewed)
    # Remove palavras repetidas seguidas (comum em transcricao automatica,
    # ex.: "entao entao vamos comecar").
    reviewed = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", reviewed, flags=re.IGNORECASE)

    parts = re.split(r"([.!?]+[\s]*)", reviewed)
    sentences = []
    for index in range(0, len(parts), 2):
        sentence = parts[index].strip()
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        if not sentence:
            continue
        sentence = sentence[0].upper() + sentence[1:]
        sentences.append(f"{sentence}{separator}")

    reviewed = "".join(sentences).strip() or reviewed
    if reviewed and reviewed[-1] not in ".!?":
        reviewed = f"{reviewed}."
    return reviewed


def review_text_with_ollama(text: str, language: str | None) -> str:
    """Uses a local Ollama model to review the transcription and make it more coherent."""
    input_text = str(text or "").strip()
    if not input_text:
        return input_text

    target_language = language or "pt"
    prompt = (
        "You are a transcription reviewer\n"
        "Fix recognition errors, punctuation and flow\n"
        "Keep the original meaning without inventing information\n"
        "Keep the requested language\n"
        "Return only the reviewed text\n\n"
        f"Requested language: {target_language}\n"
        "Text:\n"
        f"{input_text}"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }

    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    request = Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Ollama review failed: {error}") from error

    try:
        data = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("Invalid response from Ollama during review") from error

    reviewed_text = str(data.get("response", "") or "").strip()
    if not reviewed_text:
        raise RuntimeError("Ollama returned an empty review")
    return reviewed_text


def review_transcription_text(text: str, language: str | None, review_text: bool) -> dict:
    """Reviews the transcription text with local AI, falling back to rule-based review."""
    base_text = str(text or "").strip()
    if not base_text:
        return {"reviewed_text": "", "method": "none"}

    if not review_text:
        return {"reviewed_text": base_text, "method": "disabled"}

    logger.info(
        json.dumps(
            {
                "local_review": "transcribed_text",
                "status": "starting",
                "ollama_enabled": USE_OLLAMA_REVIEW,
                "ollama_model": OLLAMA_MODEL if USE_OLLAMA_REVIEW else "",
            },
            ensure_ascii=False,
        )
    )

    if USE_OLLAMA_REVIEW:
        try:
            reviewed_text = review_text_with_ollama(base_text, language)
            logger.info(
                json.dumps(
                    {
                        "local_review": "transcribed_text",
                        "status": "success",
                        "method": "ollama",
                        "text_length": len(reviewed_text),
                    },
                    ensure_ascii=False,
                )
            )
            return {"reviewed_text": reviewed_text, "method": "ollama"}
        except Exception as error:
            logger.warning(
                json.dumps(
                    {
                        "local_review": "transcribed_text",
                        "status": "fallback",
                        "method": "rules",
                        "detail": str(error),
                    },
                    ensure_ascii=False,
                )
            )

    reviewed_text = review_text_with_rules(base_text)
    logger.info(
        json.dumps(
            {
                "local_review": "transcribed_text",
                "status": "success",
                "method": "rules",
                "text_length": len(reviewed_text),
            },
            ensure_ascii=False,
        )
    )
    return {"reviewed_text": reviewed_text, "method": "rules"}


def sanitize_filename(name: str) -> str:
    """Removes characters that are invalid in a Windows filename."""
    forbidden = '<>:"/\\|?*'
    clean_name = "".join(c for c in name if c not in forbidden).strip()
    return clean_name or "file"


def make_unique_path(folder: Path, file_name: str) -> Path:
    """If the name already exists, creates variations like 'name (1).ext'."""
    path = folder / file_name
    if not path.exists():
        return path

    base = path.stem
    extension = path.suffix
    counter = 1
    while True:
        new_path = folder / f"{base} ({counter}){extension}"
        if not new_path.exists():
            return new_path
        counter += 1


def validate_urls(value: object) -> list[str]:
    """Accepts a string or list and returns only valid http(s) URLs."""
    if isinstance(value, str):
        urls = [value]
    elif isinstance(value, list):
        urls = [str(item) for item in value]
    else:
        return []

    valid_urls = []
    for url in urls:
        candidate = url.strip()
        if candidate.startswith(("http://", "https://")):
            valid_urls.append(candidate)
    return valid_urls


def download_mp3(url: str, ffmpeg_dir: str) -> dict:
    """Downloads the URL and converts it to mp3."""
    # Prefixo aleatorio no nome temporario evita colisao entre downloads
    # concorrentes antes do arquivo ser renomeado pro titulo final.
    code = uuid.uuid4().hex[:8]
    output_template = str(AUDIO_DIR / f"{code}_%(title)s.%(ext)s")
    options = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "windowsfilenames": True,
        "ffmpeg_location": ffmpeg_dir,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        ],
    }

    js_runtime = get_js_runtime()
    if js_runtime:
        options["js_runtimes"] = js_runtime

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    generated_files = sorted(AUDIO_DIR.glob(f"{code}_*.mp3"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not generated_files:
        raise RuntimeError("Could not find the generated mp3 file.")

    file = generated_files[0]
    final_name = sanitize_filename(f"{info.get('title', 'audio')}.mp3")
    destination = make_unique_path(AUDIO_DIR, final_name)
    if destination != file:
        file.rename(destination)
        file = destination

    return {
        "status": "success",
        "url": url,
        "title": info.get("title") or file.stem,
        "file_name": file.name,
        "file_url": f"/api/download?type=audio&name={quote(file.name)}",
    }


def download_mp4(url: str, ffmpeg_dir: str) -> dict:
    """Downloads the URL as mp4, aiming for the best quality available."""
    code = uuid.uuid4().hex[:8]
    output_template = str(VIDEO_DIR / f"{code}_%(title)s.%(ext)s")
    options = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "windowsfilenames": True,
        "ffmpeg_location": ffmpeg_dir,
    }

    js_runtime = get_js_runtime()
    if js_runtime:
        options["js_runtimes"] = js_runtime

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    generated_files = sorted(VIDEO_DIR.glob(f"{code}_*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not generated_files:
        raise RuntimeError("Could not find the generated mp4 file.")

    file = generated_files[0]
    final_name = sanitize_filename(f"{info.get('title', 'video')}.mp4")
    destination = make_unique_path(VIDEO_DIR, final_name)
    if destination != file:
        file.rename(destination)
        file = destination

    return {
        "status": "success",
        "url": url,
        "title": info.get("title") or file.stem,
        "file_name": file.name,
        "file_url": f"/api/download?type=video&name={quote(file.name)}",
    }


def download_temp_audio(url: str) -> tuple[Path, str]:
    """Downloads audio-only temporarily to feed the transcription step."""
    code = uuid.uuid4().hex[:8]
    output_template = str(TEMP_DIR / f"{code}.%(ext)s")
    options = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "windowsfilenames": True,
    }

    js_runtime = get_js_runtime()
    if js_runtime:
        options["js_runtimes"] = js_runtime

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    generated_files = sorted(TEMP_DIR.glob(f"{code}.*"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not generated_files:
        raise RuntimeError("Could not download temporary audio.")

    return generated_files[0], str(info.get("title") or "Untitled")


def get_transcription_model():
    """Loads the faster-whisper model once and reuses it across every transcription."""
    global TRANSCRIPTION_MODEL
    if TRANSCRIPTION_MODEL is not None:
        return TRANSCRIPTION_MODEL

    from faster_whisper import WhisperModel

    logger.info(
        json.dumps(
            {
                "local_transcription": "faster-whisper",
                "action": "load_model",
                "model": WHISPER_MODEL,
                "device": WHISPER_DEVICE,
                "compute": WHISPER_COMPUTE_TYPE,
                "status": "starting",
            },
            ensure_ascii=False,
        )
    )
    TRANSCRIPTION_MODEL = WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )
    logger.info(
        json.dumps(
            {
                "local_transcription": "faster-whisper",
                "action": "load_model",
                "model": WHISPER_MODEL,
                "status": "success",
            },
            ensure_ascii=False,
        )
    )
    return TRANSCRIPTION_MODEL


def transcribe_with_faster_whisper(audio_path: Path, language: str | None, ffmpeg_dir: str) -> dict:
    """Transcribes the audio locally with faster-whisper."""
    model = get_transcription_model()

    logger.info(
        json.dumps(
            {
                "local_transcription": "faster-whisper",
                "action": "transcribe",
                "model": WHISPER_MODEL,
                "language": language or "auto",
                "file": audio_path.name,
                "status": "starting",
            },
            ensure_ascii=False,
        )
    )

    try:
        audio_samples = load_audio_samples(audio_path, ffmpeg_dir)
        segments, info = model.transcribe(
            audio_samples,
            language=language,
            vad_filter=True,
        )
        segment_list = []
        running_parts = []
        timestamped_lines = []

        for segment in segments:
            segment_text = str(getattr(segment, "text", "") or "").strip()
            if not segment_text:
                continue

            start = float(getattr(segment, "start", 0.0) or 0.0)
            end = float(getattr(segment, "end", start) or start)

            segment_list.append({"start": start, "end": end, "text": segment_text})
            running_parts.append(segment_text)
            timestamped_lines.append(f"[{format_readable_time(start)} --> {format_readable_time(end)}] {segment_text}")

        full_text = " ".join(running_parts).strip()
        timestamped_text = "\n".join(timestamped_lines).strip()
    except Exception as error:
        logger.error(
            json.dumps(
                {
                    "local_transcription": "faster-whisper",
                    "action": "transcribe",
                    "model": WHISPER_MODEL,
                    "language": language or "auto",
                    "file": audio_path.name,
                    "status": "error",
                    "detail": str(error),
                },
                ensure_ascii=False,
            )
        )
        raise

    if not full_text or not timestamped_text:
        raise RuntimeError("Transcription came back empty")

    logger.info(
        json.dumps(
            {
                "local_transcription": "faster-whisper",
                "action": "transcribe",
                "model": WHISPER_MODEL,
                "requested_language": language or "auto",
                "detected_language": getattr(info, "language", ""),
                "file": audio_path.name,
                "status": "success",
                "text_length": len(full_text),
                "total_segments": len(segment_list),
            },
            ensure_ascii=False,
        )
    )
    return {
        "full_text": full_text,
        "timestamped_text": timestamped_text,
        "segments": segment_list,
        "detected_language": str(getattr(info, "language", "") or ""),
    }


def save_transcription_files(
    url: str,
    title: str,
    original_full_text: str,
    reviewed_full_text: str,
    timestamped_text: str,
    review_text: bool,
) -> dict:
    """Saves the transcription as txt and md."""
    clean_title = sanitize_filename(str(title or "").strip())
    clean_title = re.sub(r"\s+", " ", clean_title).strip(" .")
    if not clean_title:
        clean_title = "Untitled"
    base_name = sanitize_filename(f"Transcript - {clean_title}")
    txt_path = make_unique_path(TRANSCRIPTS_DIR, f"{base_name}.txt")
    md_path = make_unique_path(TRANSCRIPTS_DIR, f"{base_name}.md")

    if review_text:
        txt_content = (
            f"TITLE: {title}\n"
            f"URL: {url}\n\n"
            "REVIEWED TRANSCRIPTION\n"
            "=======================\n"
            f"{reviewed_full_text}\n\n"
            "TIMESTAMPED TRANSCRIPTION\n"
            "==========================\n"
            f"{timestamped_text}\n"
        )
        md_content = (
            f"# {title}\n\n"
            f"URL: {url}\n\n"
            "## Reviewed transcription\n\n"
            f"{reviewed_full_text}\n\n"
            "## Timestamped transcription\n\n"
            f"{timestamped_text}\n"
        )
    else:
        txt_content = (
            f"TITLE: {title}\n"
            f"URL: {url}\n\n"
            "ORIGINAL TRANSCRIPTION\n"
            "========================\n"
            f"{original_full_text}\n"
        )
        md_content = (
            f"# {title}\n\n"
            f"URL: {url}\n\n"
            "## Original transcription\n\n"
            f"{original_full_text}\n"
        )

    txt_path.write_text(txt_content, encoding="utf-8")
    md_path.write_text(md_content, encoding="utf-8")

    return {
        "txt_name": txt_path.name,
        "txt_url": f"/api/download?type=transcript&name={quote(txt_path.name)}",
        "md_name": md_path.name,
        "md_url": f"/api/download?type=transcript&name={quote(md_path.name)}",
    }


def process_transcription(url: str, language: str | None, ffmpeg_dir: str, review_text: bool) -> dict:
    """Full transcription flow: download audio, transcribe, review and save."""
    audio_path = None
    try:
        audio_path, title = download_temp_audio(url)
        transcription_data = transcribe_with_faster_whisper(audio_path, language, ffmpeg_dir)
        review_data = review_transcription_text(
            text=transcription_data["full_text"],
            language=language,
            review_text=review_text,
        )
        files = save_transcription_files(
            url,
            title,
            original_full_text=transcription_data["full_text"],
            reviewed_full_text=review_data["reviewed_text"],
            timestamped_text=transcription_data["timestamped_text"],
            review_text=review_text,
        )
        return {
            "status": "success",
            "url": url,
            "title": title,
            "text": review_data["reviewed_text"],
            "reviewed_text": review_data["reviewed_text"],
            "original_text": transcription_data["full_text"],
            "timestamped_text": transcription_data["timestamped_text"],
            "detected_language": transcription_data["detected_language"],
            "review_method": review_data["method"],
            "review_enabled": review_text,
            "total_segments": len(transcription_data["segments"]),
            "txt_name": files["txt_name"],
            "txt_url": files["txt_url"],
            "md_name": files["md_name"],
            "md_url": files["md_url"],
        }
    finally:
        # Audio temporario e so um meio pro fim - some depois da
        # transcricao, com ou sem sucesso.
        if audio_path and audio_path.exists():
            audio_path.unlink(missing_ok=True)


@app.get("/")
async def root_route():
    # Serve o frontend
    index_path = PUBLIC_DIR / "index.html"
    return FileResponse(index_path)


@app.get("/api/status")
async def status_route():
    # Status simples para o frontend
    return {
        "status": "ok",
        "ffmpeg_available": bool(get_ffmpeg_dir()),
        "local_transcription": "faster-whisper",
        "whisper_model": WHISPER_MODEL,
        "whisper_device": WHISPER_DEVICE,
        "whisper_compute_type": WHISPER_COMPUTE_TYPE,
        "local_review": "ollama+rules" if USE_OLLAMA_REVIEW else "rules",
        "ollama_model": OLLAMA_MODEL if USE_OLLAMA_REVIEW else "",
    }


@app.get("/api/download")
async def download_route(type: str = "", name: str = ""):
    # Baixa arquivos ja gerados
    file_type = str(type).strip().lower()
    name = str(name).strip()
    # Fica so com o nome do arquivo (sem diretorio) - evita path traversal
    # via "../" no parametro.
    clean_name = Path(name).name

    folder_map = {
        "audio": AUDIO_DIR,
        "video": VIDEO_DIR,
        "transcript": TRANSCRIPTS_DIR,
    }
    destination_folder = folder_map.get(file_type)

    if not destination_folder:
        return JSONResponse({"status": "error", "message": "Invalid download type."}, status_code=400)
    if not clean_name or clean_name != name:
        return JSONResponse({"status": "error", "message": "Invalid file name."}, status_code=400)

    file_path = destination_folder / clean_name
    if not file_path.exists():
        return JSONResponse({"status": "error", "message": "File not found."}, status_code=404)

    return FileResponse(file_path, filename=clean_name)


@app.post("/api/process")
async def process_route(body: ProcessRequestBody):
    # Entrada do frontend: acao + lista de URLs
    action = str(body.action or "").strip().lower()
    urls = validate_urls(body.urls)
    language = str(body.language or "").strip().lower() or None
    review_text = bool(body.review_text)

    if action not in {"audio", "video", "transcript"}:
        return JSONResponse(
            {"status": "error", "message": "Invalid action. Use: audio, video or transcript."},
            status_code=400,
        )
    if not urls:
        return JSONResponse(
            {"status": "error", "message": "Provide at least one valid URL."},
            status_code=400,
        )

    ffmpeg_dir = get_ffmpeg_dir()
    if not ffmpeg_dir:
        return JSONResponse(
            {
                "status": "error",
                "message": "ffmpeg/ffprobe not found on PATH. Install with: winget install -e --id Gyan.FFmpeg",
            },
            status_code=400,
        )

    # Processa uma URL por vez para manter a logica simples.
    log_folder = AUDIO_DIR if action == "audio" else VIDEO_DIR if action == "video" else TRANSCRIPTS_DIR
    results = []
    for url in urls:
        log_json(url=url, title="", destination_folder=log_folder, status="starting")
        try:
            if action == "audio":
                result = download_mp3(url, ffmpeg_dir=ffmpeg_dir)
            elif action == "video":
                result = download_mp4(url, ffmpeg_dir=ffmpeg_dir)
            else:
                result = process_transcription(
                    url,
                    language=language,
                    ffmpeg_dir=ffmpeg_dir,
                    review_text=review_text,
                )
            log_json(
                url=url,
                title=str(result.get("title", "")),
                destination_folder=log_folder,
                status="success",
            )
        except DownloadError as error:
            result = {"status": "error", "url": url, "message": f"Download error: {error}"}
            log_json(
                url=url,
                title="",
                destination_folder=log_folder,
                status="error",
                detail=str(error),
            )
        except Exception as error:
            result = {"status": "error", "url": url, "message": str(error)}
            log_json(
                url=url,
                title="",
                destination_folder=log_folder,
                status="error",
                detail=str(error),
            )
        results.append(result)

    total_success = sum(1 for item in results if item.get("status") == "success")
    final_status = "success" if total_success > 0 else "error"
    http_code = 200 if total_success > 0 else 500

    transcribed_text = ""
    transcribed_text_with_timestamps = ""
    transcription_files = []
    if action == "transcript":
        blocks = []
        timestamped_blocks = []
        for item in results:
            if item.get("status") != "success":
                continue
            blocks.append(
                f"TITLE: {item.get('title', 'Untitled')}\n"
                f"URL: {item.get('url', '')}\n\n"
                f"{item.get('text', '')}"
            )
            timestamped_blocks.append(
                f"TITLE: {item.get('title', 'Untitled')}\n"
                f"URL: {item.get('url', '')}\n\n"
                f"{item.get('timestamped_text', '')}"
            )
            transcription_files.append(
                {
                    "source_url": item.get("url", ""),
                    "txt_name": item.get("txt_name", ""),
                    "txt_url": item.get("txt_url", ""),
                    "md_name": item.get("md_name", ""),
                    "md_url": item.get("md_url", ""),
                }
            )

        transcribed_text = "\n\n" + ("\n\n" + ("-" * 80) + "\n\n").join(blocks) if blocks else ""
        transcribed_text = transcribed_text.strip()
        transcribed_text_with_timestamps = "\n\n" + ("\n\n" + ("-" * 80) + "\n\n").join(timestamped_blocks) if timestamped_blocks else ""
        transcribed_text_with_timestamps = transcribed_text_with_timestamps.strip()

    return JSONResponse(
        {
            "status": final_status,
            "action": action,
            "message": f"Processing finished: {total_success}/{len(results)} succeeded.",
            "results": results,
            "transcribed_text": transcribed_text,
            "transcribed_text_with_timestamps": transcribed_text_with_timestamps,
            "transcription_files": transcription_files,
        },
        status_code=http_code,
    )


if __name__ == "__main__":
    requested_port = PORT
    PORT = choose_available_port(HOST, requested_port)

    if PORT != requested_port:
        logger.warning("Port %s in use. Automatically using port %s.", requested_port, PORT)

    uvicorn.run(app, host=HOST, port=PORT, access_log=False, log_level="warning")
