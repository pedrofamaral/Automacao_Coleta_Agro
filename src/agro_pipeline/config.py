"""Configuração lida do ambiente (.env em desenvolvimento, secrets no GitHub Actions)."""

import os
import subprocess
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dotenv import find_dotenv, load_dotenv
from sqlalchemy.engine import URL, make_url

load_dotenv(find_dotenv(usecwd=True))

_HOSTS_LOCAIS = {"localhost", "127.0.0.1"}

FUSO = ZoneInfo("America/Sao_Paulo")

# início padrão do histórico (as séries mais antigas do MVP começam em 2004)
DESDE_PADRAO = date(2004, 1, 1)


def database_url() -> URL:
    """URL do banco, com driver psycopg 3 e SSL obrigatório fora do localhost."""
    bruta = os.environ.get("DATABASE_URL")
    if not bruta:
        raise RuntimeError("DATABASE_URL não definida (crie o .env a partir do .env.example)")

    url = make_url(bruta)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.host not in _HOSTS_LOCAIS and "sslmode" not in url.query:
        url = url.update_query_dict({"sslmode": "require"})
    return url


def ambiente() -> str:
    return "github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"


def hoje() -> date:
    """Data corrente no fuso de Brasília (as fontes publicam no horário brasileiro)."""
    return datetime.now(FUSO).date()


def versao_codigo() -> str | None:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha[:7]
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
