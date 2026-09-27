"""Interface comum dos coletores.

Uma `Tarefa` é uma unidade de coleta independente (ex.: CEPEA soja, NASA em Sorriso/MT):
cada execução dela gera uma linha em `coleta`, e a falha de uma não afeta as outras.

- `buscar(inicio, fim)` fala com a fonte e devolve o payload bruto (JSON-serializável);
- `transformar(registros)` é pura: converte o payload para o formato canônico
  (serie, data, valor). Por ser pura, também serve para reprocessar payloads já gravados.
"""

import hashlib
import json
import math
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypeVar

import pandas as pd

COLUNAS_CANONICAS = ["serie", "data", "valor"]

T = TypeVar("T")


@dataclass
class Busca:
    metodo: str
    parametros: dict[str, Any]
    registros: list[dict[str, Any]]
    duracao_ms: int = 0
    tentativas: int = 1

    @property
    def hash(self) -> str:
        bruto = json.dumps(self.registros, sort_keys=True, ensure_ascii=False)
        return "sha256:" + hashlib.sha256(bruto.encode("utf-8")).hexdigest()


class Tarefa(ABC):
    fonte: str
    nome: str
    series: tuple[str, ...]
    # dias reconsultados antes do último dado gravado: captura revisões da fonte e dados
    # publicados com atraso
    sobreposicao_dias: int = 10

    @abstractmethod
    def buscar(self, inicio: date, fim: date) -> Busca: ...

    @abstractmethod
    def transformar(self, registros: list[dict[str, Any]]) -> pd.DataFrame: ...


@dataclass
class FalhaBusca(Exception):
    causa: BaseException
    tentativas: int
    historico: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{type(self.causa).__name__}: {self.causa} (após {self.tentativas} tentativas)"


def com_retry(
    fn: Callable[[], T], tentativas: int = 3, espera_inicial: float = 2.0
) -> tuple[T, int]:
    """Executa `fn` com backoff exponencial (2 s, 4 s, ...). Devolve (resultado, tentativas)."""
    historico: list[str] = []
    for n in range(1, tentativas + 1):
        try:
            return fn(), n
        except Exception as e:
            historico.append(f"{type(e).__name__}: {e}")
            if n == tentativas:
                raise FalhaBusca(e, n, historico) from e
            time.sleep(espera_inicial * 2 ** (n - 1))
    raise AssertionError("inalcançável")


def iso(d: Any) -> str:
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def numero(v: Any) -> float | None:
    """float JSON-serializável (NaN/None viram None)."""
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) else f


def quadro_canonico(linhas: list[tuple[str, Any, Any]], extras: dict[str, list] | None = None) -> pd.DataFrame:
    df = pd.DataFrame(linhas, columns=COLUNAS_CANONICAS)
    df["data"] = pd.to_datetime(df["data"]).dt.date
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    for coluna, valores in (extras or {}).items():
        df[coluna] = valores
    return df
