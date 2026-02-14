from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
import uvicorn


# Carrega variáveis do arquivo .env
load_dotenv()


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


# Pastas principais do projeto
PASTA_RAIZ = Path(__file__).resolve().parent
PASTA_PUBLICA = PASTA_RAIZ / "public"


@asynccontextmanager
async def ciclo_vida(_app: FastAPI):
    logger.info("--- Interface Youtube Transcriber iniciando ---")
    logger.info("Frontend disponível em: http://%s:%s", HOST, PORTA)
    yield


app = FastAPI(title="hr-youtube-transcriber", lifespan=ciclo_vida)


@app.get("/")
async def rota_home():
    # Entrega o frontend
    caminho_index = PASTA_PUBLICA / "index.html"
    return FileResponse(caminho_index)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORTA, access_log=False, log_level="warning")
