# 🎬 YouTube Transcriber Web

<p align="center">
  <a href="https://github.com/lucas-hochmann-rosa/youtube-transcriber-web">
    <img src="https://img.shields.io/badge/GitHub-youtube--transcriber--web-181717?style=for-the-badge&logo=github">
  </a>
  <a href="https://www.linkedin.com/in/lucas-hochmann-rosa">
    <img src="https://img.shields.io/badge/LinkedIn-Lucas_Hochmann_Rosa-0A66C2?style=for-the-badge&logo=linkedin">
  </a>
  <a href="#-tech-stack">
    <img src="https://img.shields.io/badge/FastAPI-Python-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-2ea44f?style=for-the-badge">
  </a>
</p>

<p align="center"><a href="README.md">🇧🇷 Português</a> · 🇺🇸 English</p>

> Web application for YouTube media extraction and local AI-powered transcription. Built with Python, FastAPI, yt-dlp, and faster-whisper, featuring optional local Ollama-based refinement with a rule-based fallback.

---

## 📌 Overview

A local web application to download YouTube videos as `mp3` or `mp4` and transcribe the audio content locally, exporting the result as `.txt` and `.md`. All processing runs on your own machine - no audio or video is sent to third-party services (Ollama, when enabled, also runs locally).

---

## ✨ Key Features

- Download audio as `mp3` at the best quality available
- Download video as `mp4` at the best quality available
- Local transcription with `faster-whisper`, no external service required
- Per-segment timestamps (`HH:MM:SS.mmm --> HH:MM:SS.mmm`)
- Optional review of the transcribed text for better coherence
- Review through a local `Ollama` model, with automatic rule-based fallback when Ollama is disabled or unavailable
- Export the transcription as `.txt` and `.md`
- Interface supporting multiple URLs at once and a light/dark theme toggle

---

## 🧭 Table of Contents

- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Project Ground Rules](#-project-ground-rules)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Environment Configuration](#-environment-configuration)
- [Usage](#-usage)
- [Main Endpoints](#-main-endpoints)
- [Web Interface](#-web-interface)
- [Disclaimer](#-disclaimer)
- [Author](#-author)
- [License](#-license)

---

## 🏗️ Architecture

```text
youtube-transcriber-web/
├── main.py                     # FastAPI backend: routes, download, transcription, review and export
├── requirements.txt             # Python dependencies
├── .env                         # Local variables (not versioned)
├── .env.example                 # Example variables
├── README.md                    # Portuguese documentation
├── README.en.md                 # This file (English)
├── LICENSE
├── .gitignore
├── public/
│   └── index.html               # Web interface
├── output/                      # Generated files (audio/video/transcripts), not versioned
│   ├── audio/
│   ├── video/
│   ├── transcripts/
│   └── temp/
└── tools/                       # Optional local dependencies (e.g. a portable ffmpeg build), not versioned
```

### Organization

- **Backend (`main.py`)** → routes, download, transcription, review and export
- **Frontend (`public/index.html`)** → form, API calls and result display
- **Output (`output/`)** → final and temporary processing artifacts, generated at runtime

---

## 🧰 Tech Stack

- Python 3.13+
- FastAPI
- yt-dlp
- faster-whisper
- Ollama (optional, for advanced local review)
- python-dotenv
- HTML + CSS + JavaScript

---

## 📐 Project Ground Rules

- Identifiers, routes, request/response bodies, and function names stay in English.
- Code comments stay in Portuguese, reserved for non-obvious decisions - the "why", not the "what" (e.g. why audio is converted to mono 16kHz PCM before transcription, why a rule-based review fallback exists) - the author's native language, since this is a personal project.
- The visible interface text (`public/index.html`) stays in Portuguese: it's the application itself, built for personal use in Portuguese.
- No credentials or sensitive data are versioned - `.env` stays out of the repository, only `.env.example` is versioned.

---

## ⚙️ Requirements

- Python >= 3.13
- `ffmpeg` and `ffprobe` installed on the system (or a local folder pointed to by `FFMPEG_DIR`)
- `pip`
- Ollama optional, if you want local LLM review

On Windows, you can install ffmpeg with:

```powershell
winget install -e --id Gyan.FFmpeg
```

---

## 🔧 Installation

```bash
git clone https://github.com/lucas-hochmann-rosa/youtube-transcriber-web.git
cd youtube-transcriber-web
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 🔐 Environment Configuration

Create `.env` based on `.env.example`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8000` | HTTP port of the service |
| `WHISPER_MODEL` | `small` | faster-whisper model (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `WHISPER_DEVICE` | `cpu` | Inference device (`cpu` or `cuda`) |
| `WHISPER_COMPUTE_TYPE` | `int8` | Model precision (`int8`, `float16`, `float32`) |
| `HF_HUB_DISABLE_SYMLINKS_WARNING` | `1` | Reduces Hugging Face cache warnings on Windows |
| `USE_OLLAMA_REVIEW` | `1` | Enables Ollama review, with automatic rule-based fallback |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | URL of the local Ollama service |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model used for review through Ollama |
| `OLLAMA_TIMEOUT` | `120` | Timeout for the Ollama review, in seconds |
| `FFMPEG_DIR` | empty | Optional path to a folder with `ffmpeg.exe`/`ffprobe.exe`, if not on PATH |

---

## ▶️ Usage

```bash
.venv\Scripts\python.exe main.py
# UI: http://127.0.0.1:PORT
```

If the configured port is already in use, the service automatically picks the next free one and logs it to the terminal.

---

## 📡 Main Endpoints

| Method | Route | Description |
| ------ | ----- | ----------- |
| GET | `/` | Returns the web interface |
| GET | `/api/status` | Backend, ffmpeg, and transcription/review configuration status |
| POST | `/api/process` | Processes URLs for `audio`, `video`, or `transcript` |
| GET | `/api/download?type=<audio\|video\|transcript>&name=<file>` | Downloads an already generated file |

---

## 🖥️ Web Interface

`public/index.html` is the application itself: a form for one or more YouTube URLs, a choice between downloading audio, downloading video, or transcribing, and a results view with download links - including a light/dark theme toggle.

---

## ⚠️ Disclaimer

This project relies on unofficial libraries (`yt-dlp`) that extract media from YouTube through reverse engineering of the site, and may stop working without notice if YouTube changes how it works. Use at your own risk, respecting YouTube's terms of service and the copyright of the downloaded/transcribed content.

---

## 👨‍💻 Author

**Lucas Hochmann Rosa**

- Repository: <https://github.com/lucas-hochmann-rosa/youtube-transcriber-web>
- GitHub: <https://github.com/lucas-hochmann-rosa>
- LinkedIn: <https://www.linkedin.com/in/lucas-hochmann-rosa>

---

## 📄 License

Licensed under MIT. Feel free to use, modify, and distribute, while keeping the copyright notice and crediting **Lucas Hochmann Rosa**.

---
