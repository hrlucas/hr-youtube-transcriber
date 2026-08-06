# 🎬 YouTube Transcriber Web

<p align="center">
  <a href="https://github.com/lucas-hochmann-rosa/youtube-transcriber-web">
    <img src="https://img.shields.io/badge/GitHub-youtube--transcriber--web-181717?style=for-the-badge&logo=github">
  </a>
  <a href="https://www.linkedin.com/in/lucas-hochmann-rosa">
    <img src="https://img.shields.io/badge/LinkedIn-Lucas_Hochmann_Rosa-0A66C2?style=for-the-badge&logo=linkedin">
  </a>
  <a href="#-tecnologias">
    <img src="https://img.shields.io/badge/FastAPI-Python-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/Licença-MIT-2ea44f?style=for-the-badge">
  </a>
</p>

<p align="center">🇧🇷 Português · <a href="README.en.md">🇺🇸 English</a></p>

> Aplicação web para extração de mídia do YouTube e transcrição local com IA. A base principal é Python com FastAPI, yt-dlp e faster-whisper, com revisão opcional por Ollama local e fallback por regras.

---

## 📌 Visão Geral

Aplicação web local para baixar vídeos do YouTube em `mp3` ou `mp4` e transcrever o conteúdo de áudio localmente, exportando o resultado em `.txt` e `.md`. Todo o processamento roda na própria máquina - nenhum áudio ou vídeo é enviado para serviços de terceiros (o Ollama, quando habilitado, também roda localmente).

---

## ✨ Funcionalidades

- Download de áudio em `mp3` com a melhor qualidade disponível
- Download de vídeo em `mp4` com a melhor qualidade disponível
- Transcrição local com `faster-whisper`, sem depender de serviço externo
- Marcação temporal por segmento (`HH:MM:SS.mmm --> HH:MM:SS.mmm`)
- Revisão opcional do texto transcrito para melhorar coesão
- Revisão por `Ollama` local, com fallback automático por regras quando o Ollama está desligado ou indisponível
- Exportação da transcrição em `.txt` e `.md`
- Interface com múltiplas URLs de uma vez e alternância entre modo claro/escuro

---

## 🧭 Sumário

- [Arquitetura](#-arquitetura)
- [Tecnologias](#-tecnologias)
- [Regras de construção do projeto](#-regras-de-construção-do-projeto)
- [Requisitos](#-requisitos)
- [Instalação](#-instalação)
- [Variáveis de Ambiente](#-variáveis-de-ambiente)
- [Execução](#-execução)
- [Endpoints Principais](#-endpoints-principais)
- [Interface Web](#-interface-web)
- [Avisos](#-avisos)
- [Autor](#-autor)
- [Licença](#-licença)

---

## 🏗️ Arquitetura

```text
youtube-transcriber-web/
├── main.py                     # Backend FastAPI: rotas, download, transcricao, revisao e exportacao
├── requirements.txt             # Dependencias Python
├── .env                         # Variaveis locais (nao versionar)
├── .env.example                 # Exemplo de variaveis
├── README.md                    # Este arquivo (portugues)
├── README.en.md                 # Documentacao em ingles
├── LICENSE
├── .gitignore
├── public/
│   └── index.html               # Interface web
├── output/                      # Arquivos gerados (audio/video/transcricoes), nao versionado
│   ├── audio/
│   ├── video/
│   ├── transcripts/
│   └── temp/
└── tools/                       # Dependencias locais opcionais (ex.: build portatil do ffmpeg), nao versionado
```

### Organização

- **Backend (`main.py`)** → rotas, download, transcrição, revisão e exportação
- **Frontend (`public/index.html`)** → formulário, chamadas para a API e exibição dos resultados
- **Saída (`output/`)** → artefatos finais e temporários do processamento, gerados em tempo de execução

---

## 🧰 Tecnologias

- Python 3.13+
- FastAPI
- yt-dlp
- faster-whisper
- Ollama (opcional, para revisão avançada local)
- python-dotenv
- HTML + CSS + JavaScript

---

## 📐 Regras de construção do projeto

- Identificadores, rotas, corpo de requisição/resposta e nomes de função ficam em inglês.
- Comentários no código ficam em português, reservados para decisões não óbvias - o "porquê", não o "o quê" (ex.: por que o áudio é convertido para PCM mono 16kHz antes da transcrição, por que existe fallback de revisão por regras).
- O texto visível da interface (`public/index.html`) fica em português: é a aplicação em si, pensada para uso pessoal em português.
- Nenhuma credencial ou dado sensível é versionado - `.env` fica fora do repositório, só `.env.example` é versionado.

---

## ⚙️ Requisitos

- Python >= 3.13
- `ffmpeg` e `ffprobe` instalados no sistema (ou uma pasta local apontada por `FFMPEG_DIR`)
- `pip`
- Ollama opcional, caso queira revisão por LLM local

No Windows, você pode instalar o ffmpeg com:

```powershell
winget install -e --id Gyan.FFmpeg
```

---

## 🔧 Instalação

```bash
git clone https://github.com/lucas-hochmann-rosa/youtube-transcriber-web.git
cd youtube-transcriber-web
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 🔐 Variáveis de Ambiente

Crie `.env` a partir de `.env.example`:

| Variável | Padrão | Para que serve |
| --- | --- | --- |
| `PORT` | `8000` | Porta HTTP do serviço |
| `WHISPER_MODEL` | `small` | Modelo do faster-whisper (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `WHISPER_DEVICE` | `cpu` | Dispositivo de inferência (`cpu` ou `cuda`) |
| `WHISPER_COMPUTE_TYPE` | `int8` | Precisão do modelo (`int8`, `float16`, `float32`) |
| `HF_HUB_DISABLE_SYMLINKS_WARNING` | `1` | Reduz avisos de cache do Hugging Face no Windows |
| `USE_OLLAMA_REVIEW` | `1` | Ativa revisão por Ollama, com fallback automático por regras |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | URL do serviço Ollama local |
| `OLLAMA_MODEL` | `llama3.1:8b` | Modelo usado na revisão via Ollama |
| `OLLAMA_TIMEOUT` | `120` | Timeout da revisão via Ollama, em segundos |
| `FFMPEG_DIR` | vazio | Caminho opcional de uma pasta com `ffmpeg.exe`/`ffprobe.exe`, caso não estejam no PATH |

---

## ▶️ Execução

```bash
.venv\Scripts\python.exe main.py
# UI: http://127.0.0.1:PORT
```

Se a porta configurada já estiver em uso, o serviço escolhe automaticamente a próxima porta livre e avisa no terminal.

---

## 📡 Endpoints Principais

| Método | Rota | Descrição |
| ------ | ---- | --------- |
| GET | `/` | Retorna a interface web |
| GET | `/api/status` | Status do backend, do ffmpeg e da configuração de transcrição/revisão |
| POST | `/api/process` | Processa URLs para `audio`, `video` ou `transcript` |
| GET | `/api/download?type=<audio\|video\|transcript>&name=<arquivo>` | Download de um arquivo já gerado |

---

## 🖥️ Interface Web

`public/index.html` é a própria aplicação: formulário para uma ou mais URLs do YouTube, seleção entre baixar áudio, baixar vídeo ou transcrever, e exibição dos resultados com links de download - incluindo alternância entre modo claro e escuro.

---

## ⚠️ Avisos

Este projeto depende de bibliotecas não-oficiais (`yt-dlp`) que extraem mídia do YouTube por engenharia reversa do site, e pode parar de funcionar sem aviso caso o YouTube altere seu funcionamento. Use por sua conta e risco, respeitando os termos de uso do YouTube e os direitos autorais do conteúdo baixado/transcrito.

---

## 👨‍💻 Autor

**Lucas Hochmann Rosa**

- Repositório: <https://github.com/lucas-hochmann-rosa/youtube-transcriber-web>
- GitHub: <https://github.com/lucas-hochmann-rosa>
- LinkedIn: <https://www.linkedin.com/in/lucas-hochmann-rosa>

---

## 📄 Licença

Licenciado sob MIT. Sinta-se livre para usar, modificar e distribuir, mantendo o aviso de copyright e atribuindo crédito a **Lucas Hochmann Rosa**.

---
