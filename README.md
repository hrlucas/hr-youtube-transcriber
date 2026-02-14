# 🚀 HR YouTube Transcriber

<p align="center">
  <a href="https://github.com/hrlucas">
    <img src="https://img.shields.io/badge/GitHub-hrlucas-181717?style=for-the-badge&logo=github">
  </a>
  <a href="https://www.linkedin.com/in/lucas-hochmann-rosa-456bb7339/">
    <img src="https://img.shields.io/badge/LinkedIn-Lucas_Hochmann_Rosa-0A66C2?style=for-the-badge&logo=linkedin">
  </a>
  <a href="#">
    <img src="https://img.shields.io/badge/FastAPI-Python-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  </a>
  <a href="#">
    <img src="https://img.shields.io/badge/License-MIT-2ea44f?style=for-the-badge">
  </a>
</p>

> Desenvolvi este projeto para concentrar em um único fluxo a extração de mídia do YouTube e a transcrição local com IA. A base principal é Python com FastAPI, yt-dlp e faster-whisper, com revisão opcional por Ollama local e fallback por regras. O projeto pertence a **Lucas Hochmann Rosa / hrlucas.dev**, está aberto sob licença MIT e aceita contribuições, desde que mantendo referência ao autor em usos e derivados.

---

## 📌 Visão Geral

Aplicação web para baixar vídeos do YouTube em `mp3` ou `mp4`, transcrever conteúdo de áudio localmente e exportar resultados em formatos de texto.

---

## 🧠 Funcionalidades

- Download de áudio em `mp3` com melhor qualidade disponível
- Download de vídeo em `mp4` com melhor qualidade disponível
- Transcrição local com `faster-whisper`
- Marcação temporal por segmento (`HH:MM:SS.mmm --> HH:MM:SS.mmm`)
- Revisão opcional de texto para coesão
- Revisão por `Ollama` local com fallback automático por regras
- Exportação em `.txt` e `.md`
- Interface com múltiplas URLs e modo claro/escuro

---

## 🏗️ Arquitetura

```text
project-root/
│
├── main.py                     # Backend FastAPI e regras de processamento
├── requirements.txt            # Dependências Python
├── .env                        # Variáveis locais (não versionar)
├── .env.example                # Exemplo de variáveis
├── README.md
├── LICENSE
├── .gitignore
├── public/
│   └── index.html              # Interface web
├── saida/                      # Arquivos gerados (áudio/vídeo/transcrições)
│   ├── audio/
│   ├── video/
│   ├── transcricoes/
│   └── temp/
└── tools/                      # Dependências locais opcionais (ex.: ffmpeg)
```

### Organização

- **Backend (`main.py`)** → rotas, download, transcrição, revisão e exportação
- **Frontend (`public/index.html`)** → formulário, envio para API e exibição dos resultados
- **Saída (`saida/`)** → artefatos finais e temporários do processamento

---

## 🛠️ Tecnologias

- Python 3.13+
- FastAPI
- yt-dlp
- faster-whisper
- Ollama (opcional para revisão avançada local)
- python-dotenv
- HTML + CSS + JavaScript

---

## ⚙️ Requisitos

- Python >= 3.13
- `ffmpeg` e `ffprobe` instalados no sistema
- `pip`
- Ollama opcional, caso queira revisão por LLM local

No Windows, você pode instalar ffmpeg com:

```powershell
winget install -e --id Gyan.FFmpeg
```

---

## 🔧 Instalação

```bash
git clone https://github.com/hrlucas/hr-youtube-transcriber.git
cd hr-youtube-transcriber
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 🔐 Variáveis de Ambiente

Crie `.env` a partir de `.env.example`:

```env
PORT=8000
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
HF_HUB_DISABLE_SYMLINKS_WARNING=1
USAR_OLLAMA_REVISAO=1
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODELO=llama3.1:8b
OLLAMA_TIMEOUT=120
FFMPEG_DIR=
```

- `PORT`: porta HTTP do serviço
- `WHISPER_MODEL`: modelo do faster-whisper (`tiny`, `base`, `small`, `medium`, `large-v3`)
- `WHISPER_DEVICE`: dispositivo (`cpu` ou `cuda`)
- `WHISPER_COMPUTE_TYPE`: precisão (`int8`, `float16`, `float32`)
- `HF_HUB_DISABLE_SYMLINKS_WARNING`: reduz avisos de cache no Windows
- `USAR_OLLAMA_REVISAO`: ativa revisão por Ollama (`1`) com fallback por regras
- `OLLAMA_BASE_URL`: URL do serviço Ollama local
- `OLLAMA_MODELO`: modelo usado na revisão via Ollama
- `OLLAMA_TIMEOUT`: timeout da revisão com Ollama, em segundos
- `FFMPEG_DIR`: caminho opcional da pasta com `ffmpeg` e `ffprobe`

### ▶️ Execução

```bash
.venv\Scripts\python.exe main.py
# UI:  http://127.0.0.1:PORT
```

---

## 📡 Endpoints Principais

| Método | Rota | Descrição |
| ------ | ---- | --------- |
| GET | `/` | Retorna a interface web |
| GET | `/api/status` | Status do backend, ffmpeg e configuração de transcrição/revisão |
| POST | `/api/processar` | Processa URLs para `audio`, `video` ou `transcricao` |
| GET | `/api/baixar?tipo=<audio|video|transcricao>&nome=<arquivo>` | Download de arquivo gerado |

---

## 📄 Licença

Licenciado sob MIT. Você pode usar, modificar e distribuir, mantendo os avisos de copyright e atribuindo crédito a **Lucas Hochmann Rosa / hrlucas.dev**.

---

## 👨‍💻 Autor

**Lucas Hochmann Rosa / hrlucas.dev** — Desenvolvedor Full Stack

- GitHub: https://github.com/hrlucas
- LinkedIn: https://www.linkedin.com/in/lucas-hochmann-rosa-456bb7339/
- Licença: MIT (cite o autor ao usar ou derivar o projeto)
