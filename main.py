from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import uvicorn


# Carrega variáveis do arquivo .env
load_dotenv()
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = str(os.getenv("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")).strip()


# Configura log somente no terminal
logger = logging.getLogger("hr-youtube-transcriber")
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


# Configurações do servidor
HOST = "127.0.0.1"
try:
    PORTA = int(os.getenv("PORT", "8000"))
except ValueError:
    PORTA = 8000


def porta_esta_livre(host: str, porta: int) -> bool:
    """Retorna True se a porta estiver livre no host informado."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cliente:
        cliente.settimeout(0.2)
        return cliente.connect_ex((host, porta)) != 0


def escolher_porta_disponivel(host: str, porta_inicial: int, tentativas: int = 20) -> int:
    """Tenta a porta inicial e, se ocupada, procura a próxima disponível."""
    if porta_esta_livre(host, porta_inicial):
        return porta_inicial

    for deslocamento in range(1, tentativas + 1):
        porta_atual = porta_inicial + deslocamento
        if porta_esta_livre(host, porta_atual):
            return porta_atual

    return porta_inicial


# Pastas principais do projeto
PASTA_RAIZ = Path(__file__).resolve().parent
PASTA_PUBLICA = PASTA_RAIZ / "public"
PASTA_SAIDA = PASTA_RAIZ / "saida"
PASTA_AUDIO = PASTA_SAIDA / "audio"
PASTA_VIDEO = PASTA_SAIDA / "video"
PASTA_TRANSCRICOES = PASTA_SAIDA / "transcricoes"
PASTA_TEMP = PASTA_SAIDA / "temp"
WHISPER_MODELO = str(os.getenv("WHISPER_MODEL", "small")).strip() or "small"
WHISPER_DISPOSITIVO = str(os.getenv("WHISPER_DEVICE", "cpu")).strip() or "cpu"
WHISPER_TIPO_COMPUTE = str(os.getenv("WHISPER_COMPUTE_TYPE", "int8")).strip() or "int8"
MODELO_TRANSCRICAO: Any | None = None


# Garante que as pastas existam antes de usar
for pasta in [PASTA_AUDIO, PASTA_VIDEO, PASTA_TRANSCRICOES, PASTA_TEMP]:
    pasta.mkdir(parents=True, exist_ok=True)


class CorpoProcessamento(BaseModel):
    acao: str = ""
    urls: list[str] | str = []
    idioma: str | None = None


@asynccontextmanager
async def ciclo_vida(_app: FastAPI):
    logger.info("--- Interface Youtube Transcriber iniciando ---")
    logger.info("=" * 72)
    pasta_ffmpeg = obter_pasta_ffmpeg()
    if pasta_ffmpeg:
        logger.info("FFmpeg detectado em: %s", pasta_ffmpeg)
    else:
        logger.warning("FFmpeg não detectado (áudio e vídeo podem falhar)")
    logger.info(
        "Transcrição local com faster-whisper: modelo=%s, dispositivo=%s, compute=%s",
        WHISPER_MODELO,
        WHISPER_DISPOSITIVO,
        WHISPER_TIPO_COMPUTE,
    )
    logger.info("Frontend disponível em: http://%s:%s", HOST, PORTA)
    logger.info("=" * 72)
    yield


app = FastAPI(title="hr-youtube-transcriber", lifespan=ciclo_vida)


def registrar_log_json(url: str, titulo: str, pasta_destino: Path, status: str, detalhe: str = "") -> None:
    """Registra no terminal um log estruturado em JSON por item processado"""
    log = {
        "Baixando URL": url,
        "Título do arquivo": titulo,
        "Pasta destino": str(pasta_destino),
        "Status": status,
    }
    if detalhe:
        log["Detalhe"] = detalhe
    logger.info(json.dumps(log, ensure_ascii=False))


def obter_pasta_ffmpeg() -> str | None:
    """Retorna a pasta do ffmpeg/ffprobe, ou None se não estiver no PATH."""
    caminho_ffmpeg = shutil.which("ffmpeg")
    caminho_ffprobe = shutil.which("ffprobe")
    if not caminho_ffmpeg or not caminho_ffprobe:
        return None
    return str(Path(caminho_ffmpeg).resolve().parent)


def obter_runtime_js() -> dict | None:
    """Ativa Node.js se existir (ajuda a extração do YouTube no yt-dlp)."""
    caminho_node = shutil.which("node")
    if not caminho_node:
        return None
    return {"node": {"path": caminho_node}}


def obter_binario_ffmpeg(pasta_ffmpeg: str | None) -> str:
    """Retorna o caminho do executável ffmpeg"""
    if pasta_ffmpeg:
        pasta = Path(pasta_ffmpeg)
        candidato_windows = pasta / "ffmpeg.exe"
        if candidato_windows.exists():
            return str(candidato_windows)
        candidato = pasta / "ffmpeg"
        if candidato.exists():
            return str(candidato)

    caminho = shutil.which("ffmpeg")
    if caminho:
        return caminho

    raise RuntimeError("ffmpeg não encontrado para preparar áudio da transcrição")


def carregar_amostras_audio(caminho_audio: Path, pasta_ffmpeg: str) -> Any:
    """Converte áudio para PCM mono 16kHz e retorna array float32"""
    import numpy as np

    binario_ffmpeg = obter_binario_ffmpeg(pasta_ffmpeg)
    comando = [
        binario_ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(caminho_audio),
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
    resultado = subprocess.run(comando, capture_output=True, check=False)
    if resultado.returncode != 0:
        detalhe = resultado.stderr.decode("utf-8", errors="ignore").strip() or "Falha ao converter áudio com ffmpeg"
        raise RuntimeError(detalhe)
    if not resultado.stdout:
        raise RuntimeError("Não foi possível ler o áudio para transcrição")

    audio_pcm = np.frombuffer(resultado.stdout, dtype=np.int16)
    if audio_pcm.size == 0:
        raise RuntimeError("Áudio vazio após conversão para PCM")

    return (audio_pcm.astype("float32") / 32768.0).copy()


def formatar_tempo_legivel(segundos: float) -> str:
    """Formata segundos para HH:MM:SS.mmm"""
    valor = max(0.0, float(segundos or 0.0))
    total_ms = int(round(valor * 1000))
    horas, resto = divmod(total_ms, 3600000)
    minutos, resto = divmod(resto, 60000)
    segundos_int, milissegundos = divmod(resto, 1000)
    return f"{horas:02d}:{minutos:02d}:{segundos_int:02d}.{milissegundos:03d}"


def limpar_nome_seguro(nome: str) -> str:
    """Remove caracteres inválidos para nome de arquivo no Windows."""
    proibidos = '<>:"/\\|?*'
    nome_limpo = "".join(c for c in nome if c not in proibidos).strip()
    return nome_limpo or "arquivo"


def criar_caminho_unico(pasta: Path, nome_arquivo: str) -> Path:
    """Se o nome já existir, cria variações como 'nome (1).ext'."""
    caminho = pasta / nome_arquivo
    if not caminho.exists():
        return caminho

    base = caminho.stem
    extensao = caminho.suffix
    contador = 1
    while True:
        novo_caminho = pasta / f"{base} ({contador}){extensao}"
        if not novo_caminho.exists():
            return novo_caminho
        contador += 1


def validar_urls(entrada: object) -> list[str]:
    """Aceita string ou lista e retorna somente URLs http(s) válidas."""
    if isinstance(entrada, str):
        urls = [entrada]
    elif isinstance(entrada, list):
        urls = [str(item) for item in entrada]
    else:
        return []

    urls_validas = []
    for url in urls:
        valor = url.strip()
        if valor.startswith(("http://", "https://")):
            urls_validas.append(valor)
    return urls_validas


def baixar_mp3(url: str, pasta_ffmpeg: str) -> dict:
    """Baixa a URL e converte para mp3."""
    codigo = uuid.uuid4().hex[:8]
    modelo_saida = str(PASTA_AUDIO / f"{codigo}_%(title)s.%(ext)s")
    opcoes = {
        "format": "bestaudio/best",
        "outtmpl": modelo_saida,
        "noplaylist": True,
        "windowsfilenames": True,
        "ffmpeg_location": pasta_ffmpeg,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        ],
    }

    runtime_js = obter_runtime_js()
    if runtime_js:
        opcoes["js_runtimes"] = runtime_js

    with YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=True)

    arquivos_gerados = sorted(PASTA_AUDIO.glob(f"{codigo}_*.mp3"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not arquivos_gerados:
        raise RuntimeError("Não foi possível encontrar o mp3 gerado.")

    arquivo = arquivos_gerados[0]
    nome_final = limpar_nome_seguro(f"{info.get('title', 'audio')}.mp3")
    destino = criar_caminho_unico(PASTA_AUDIO, nome_final)
    if destino != arquivo:
        arquivo.rename(destino)
        arquivo = destino

    return {
        "status": "sucesso",
        "url": url,
        "titulo": info.get("title") or arquivo.stem,
        "arquivo_nome": arquivo.name,
        "arquivo_url": f"/api/baixar?tipo=audio&nome={quote(arquivo.name)}",
    }


def baixar_mp4(url: str, pasta_ffmpeg: str) -> dict:
    """Baixa a URL em mp4 com foco na melhor qualidade disponível."""
    codigo = uuid.uuid4().hex[:8]
    modelo_saida = str(PASTA_VIDEO / f"{codigo}_%(title)s.%(ext)s")
    opcoes = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": modelo_saida,
        "noplaylist": True,
        "windowsfilenames": True,
        "ffmpeg_location": pasta_ffmpeg,
    }

    runtime_js = obter_runtime_js()
    if runtime_js:
        opcoes["js_runtimes"] = runtime_js

    with YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=True)

    arquivos_gerados = sorted(PASTA_VIDEO.glob(f"{codigo}_*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not arquivos_gerados:
        raise RuntimeError("Não foi possível encontrar o mp4 gerado.")

    arquivo = arquivos_gerados[0]
    nome_final = limpar_nome_seguro(f"{info.get('title', 'video')}.mp4")
    destino = criar_caminho_unico(PASTA_VIDEO, nome_final)
    if destino != arquivo:
        arquivo.rename(destino)
        arquivo = destino

    return {
        "status": "sucesso",
        "url": url,
        "titulo": info.get("title") or arquivo.stem,
        "arquivo_nome": arquivo.name,
        "arquivo_url": f"/api/baixar?tipo=video&nome={quote(arquivo.name)}",
    }


def baixar_audio_temporario(url: str) -> tuple[Path, str]:
    """Baixa somente áudio temporário para enviar para transcrição."""
    codigo = uuid.uuid4().hex[:8]
    modelo_saida = str(PASTA_TEMP / f"{codigo}.%(ext)s")
    opcoes = {
        "format": "bestaudio/best",
        "outtmpl": modelo_saida,
        "noplaylist": True,
        "windowsfilenames": True,
    }

    runtime_js = obter_runtime_js()
    if runtime_js:
        opcoes["js_runtimes"] = runtime_js

    with YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=True)

    arquivos_gerados = sorted(PASTA_TEMP.glob(f"{codigo}.*"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not arquivos_gerados:
        raise RuntimeError("Não foi possível baixar áudio temporário.")

    return arquivos_gerados[0], str(info.get("title") or "Sem título")


def obter_modelo_transcricao():
    """Carrega o modelo faster-whisper uma vez e reaproveita em todas as transcrições"""
    global MODELO_TRANSCRICAO
    if MODELO_TRANSCRICAO is not None:
        return MODELO_TRANSCRICAO

    from faster_whisper import WhisperModel

    logger.info("Carregando modelo faster-whisper: %s", WHISPER_MODELO)
    MODELO_TRANSCRICAO = WhisperModel(
        WHISPER_MODELO,
        device=WHISPER_DISPOSITIVO,
        compute_type=WHISPER_TIPO_COMPUTE,
    )
    logger.info("Modelo faster-whisper carregado: %s", WHISPER_MODELO)
    return MODELO_TRANSCRICAO


def transcrever_com_faster_whisper(caminho_audio: Path, idioma: str | None, pasta_ffmpeg: str) -> dict:
    """Transcreve o áudio localmente com faster-whisper"""
    modelo = obter_modelo_transcricao()

    amostras_audio = carregar_amostras_audio(caminho_audio, pasta_ffmpeg)
    segmentos, info = modelo.transcribe(
        amostras_audio,
        language=idioma,
        vad_filter=True,
    )
    lista_segmentos = []
    partes_corridas = []
    linhas_com_tempo = []

    for segmento in segmentos:
        texto_segmento = str(getattr(segmento, "text", "") or "").strip()
        if not texto_segmento:
            continue

        inicio = float(getattr(segmento, "start", 0.0) or 0.0)
        fim = float(getattr(segmento, "end", inicio) or inicio)

        lista_segmentos.append({"inicio": inicio, "fim": fim, "texto": texto_segmento})
        partes_corridas.append(texto_segmento)
        linhas_com_tempo.append(f"[{formatar_tempo_legivel(inicio)} --> {formatar_tempo_legivel(fim)}] {texto_segmento}")

    texto_corrido = " ".join(partes_corridas).strip()
    texto_com_tempo = "\n".join(linhas_com_tempo).strip()

    if not texto_corrido or not texto_com_tempo:
        raise RuntimeError("A transcrição retornou vazia")

    return {
        "texto_corrido": texto_corrido,
        "texto_com_tempo": texto_com_tempo,
        "segmentos": lista_segmentos,
        "idioma_detectado": str(getattr(info, "language", "") or ""),
    }


def salvar_arquivos_transcricao(url: str, titulo: str, texto_corrido: str, texto_com_tempo: str) -> dict:
    """Salva transcrição em txt e md."""
    titulo_limpo = limpar_nome_seguro(str(titulo or "").strip())
    titulo_limpo = re.sub(r"\s+", " ", titulo_limpo).strip(" .") if titulo_limpo else titulo_limpo
    if not titulo_limpo:
        titulo_limpo = "Sem título"
    nome_base = limpar_nome_seguro(f"Transcrição - {titulo_limpo}")
    caminho_txt = criar_caminho_unico(PASTA_TRANSCRICOES, f"{nome_base}.txt")
    caminho_md = criar_caminho_unico(PASTA_TRANSCRICOES, f"{nome_base}.md")

    conteudo_txt = (
        f"TÍTULO: {titulo}\n"
        f"URL: {url}\n\n"
        "TRANSCRIÇÃO\n"
        "===========\n"
        f"{texto_corrido}\n\n"
        "TRANSCRIÇÃO COM TEMPO\n"
        "=====================\n"
        f"{texto_com_tempo}\n"
    )
    conteudo_md = (
        f"# {titulo}\n\n"
        f"URL: {url}\n\n"
        "## Transcrição\n\n"
        f"{texto_corrido}\n\n"
        "## Transcrição com tempo\n\n"
        f"{texto_com_tempo}\n"
    )

    caminho_txt.write_text(conteudo_txt, encoding="utf-8")
    caminho_md.write_text(conteudo_md, encoding="utf-8")

    return {
        "txt_nome": caminho_txt.name,
        "txt_url": f"/api/baixar?tipo=transcricao&nome={quote(caminho_txt.name)}",
        "md_nome": caminho_md.name,
        "md_url": f"/api/baixar?tipo=transcricao&nome={quote(caminho_md.name)}",
    }


def processar_transcricao(url: str, idioma: str | None, pasta_ffmpeg: str) -> dict:
    """Fluxo completo da transcrição: baixar áudio, transcrever e salvar arquivo."""
    caminho_audio = None
    try:
        caminho_audio, titulo = baixar_audio_temporario(url)
        dados_transcricao = transcrever_com_faster_whisper(caminho_audio, idioma, pasta_ffmpeg)
        arquivos = salvar_arquivos_transcricao(
            url,
            titulo,
            texto_corrido=dados_transcricao["texto_corrido"],
            texto_com_tempo=dados_transcricao["texto_com_tempo"],
        )
        return {
            "status": "sucesso",
            "url": url,
            "titulo": titulo,
            "texto": dados_transcricao["texto_corrido"],
            "idioma_detectado": dados_transcricao["idioma_detectado"],
            "total_segmentos": len(dados_transcricao["segmentos"]),
            "txt_nome": arquivos["txt_nome"],
            "txt_url": arquivos["txt_url"],
            "md_nome": arquivos["md_nome"],
            "md_url": arquivos["md_url"],
        }
    finally:
        if caminho_audio and caminho_audio.exists():
            caminho_audio.unlink(missing_ok=True)


@app.get("/")
async def rota_home():
    # Entrega o frontend
    caminho_index = PASTA_PUBLICA / "index.html"
    return FileResponse(caminho_index)


@app.get("/api/status")
async def rota_status():
    # Retorna status simples para o frontend
    return {
        "status": "ok",
        "ffmpeg_disponivel": bool(obter_pasta_ffmpeg()),
        "transcricao_local": "faster-whisper",
        "whisper_modelo": WHISPER_MODELO,
        "whisper_dispositivo": WHISPER_DISPOSITIVO,
        "whisper_compute_type": WHISPER_TIPO_COMPUTE,
    }


@app.get("/api/baixar")
async def rota_baixar(tipo: str = "", nome: str = ""):
    # Faz download de arquivos já gerados
    tipo = str(tipo).strip().lower()
    nome = str(nome).strip()
    nome_limpo = Path(nome).name

    mapa_pastas = {
        "audio": PASTA_AUDIO,
        "video": PASTA_VIDEO,
        "transcricao": PASTA_TRANSCRICOES,
    }
    pasta_destino = mapa_pastas.get(tipo)

    if not pasta_destino:
        return JSONResponse({"status": "erro", "mensagem": "Tipo de download inválido."}, status_code=400)
    if not nome_limpo or nome_limpo != nome:
        return JSONResponse({"status": "erro", "mensagem": "Nome de arquivo inválido."}, status_code=400)

    caminho_arquivo = pasta_destino / nome_limpo
    if not caminho_arquivo.exists():
        return JSONResponse({"status": "erro", "mensagem": "Arquivo não encontrado."}, status_code=404)

    return FileResponse(caminho_arquivo, filename=nome_limpo)


@app.post("/api/processar")
async def rota_processar(corpo: CorpoProcessamento):
    # Entrada do frontend: ação + lista de URLs
    acao = str(corpo.acao or "").strip().lower()
    urls = validar_urls(corpo.urls)
    idioma = str(corpo.idioma or "").strip().lower() or None

    if acao not in {"audio", "video", "transcricao"}:
        return JSONResponse(
            {"status": "erro", "mensagem": "Ação inválida. Use: áudio, vídeo ou transcrição."},
            status_code=400,
        )
    if not urls:
        return JSONResponse(
            {"status": "erro", "mensagem": "Informe pelo menos uma URL válida."},
            status_code=400,
        )

    pasta_ffmpeg = obter_pasta_ffmpeg()
    if not pasta_ffmpeg:
        return JSONResponse(
            {
                "status": "erro",
                "mensagem": "ffmpeg/ffprobe não encontrados no PATH. Instale com: winget install -e --id Gyan.FFmpeg",
            },
            status_code=400,
        )

    pasta_log = PASTA_AUDIO if acao == "audio" else PASTA_VIDEO if acao == "video" else PASTA_TRANSCRICOES
    resultados = []
    for url in urls:
        registrar_log_json(url=url, titulo="", pasta_destino=pasta_log, status="Iniciando")
        try:
            if acao == "audio":
                resultado = baixar_mp3(url, pasta_ffmpeg=pasta_ffmpeg)
            elif acao == "video":
                resultado = baixar_mp4(url, pasta_ffmpeg=pasta_ffmpeg)
            else:
                resultado = processar_transcricao(url, idioma=idioma, pasta_ffmpeg=pasta_ffmpeg)
            registrar_log_json(
                url=url,
                titulo=str(resultado.get("titulo", "")),
                pasta_destino=pasta_log,
                status="Sucesso",
            )
        except DownloadError as erro:
            resultado = {"status": "erro", "url": url, "mensagem": f"Erro de download: {erro}"}
            registrar_log_json(url=url, titulo="", pasta_destino=pasta_log, status="Erro", detalhe=str(erro))
        except Exception as erro:
            resultado = {"status": "erro", "url": url, "mensagem": str(erro)}
            registrar_log_json(url=url, titulo="", pasta_destino=pasta_log, status="Erro", detalhe=str(erro))
        resultados.append(resultado)

    total_sucesso = sum(1 for item in resultados if item.get("status") == "sucesso")
    status_final = "sucesso" if total_sucesso > 0 else "erro"
    codigo_http = 200 if total_sucesso > 0 else 500

    texto_transcrito = ""
    if acao == "transcricao":
        blocos = [
            f"TÍTULO: {item.get('titulo', 'Sem título')}\nURL: {item.get('url', '')}\n\n{item.get('texto', '')}"
            for item in resultados
            if item.get("status") == "sucesso"
        ]
        texto_transcrito = ("\n\n" + ("-" * 80) + "\n\n").join(blocos).strip()

    return JSONResponse(
        {
            "status": status_final,
            "acao": acao,
            "mensagem": f"Processamento finalizado: {total_sucesso}/{len(resultados)} com sucesso.",
            "resultados": resultados,
            "texto_transcrito": texto_transcrito,
        },
        status_code=codigo_http,
    )


if __name__ == "__main__":
    porta_solicitada = PORTA
    PORTA = escolher_porta_disponivel(HOST, porta_solicitada)

    if PORTA != porta_solicitada:
        logger.warning("Porta %s ocupada. Usando automaticamente a porta %s.", porta_solicitada, PORTA)

    uvicorn.run(app, host=HOST, port=PORTA, access_log=False, log_level="warning")
