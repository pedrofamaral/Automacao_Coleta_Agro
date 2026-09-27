"""NASA POWER — clima diário por ponto (lat/lon), via agrobr."""

from datetime import date
from importlib.metadata import version
from typing import Any

import pandas as pd

from agro_pipeline.catalogo import PONTOS_CLIMA, VARIAVEIS_CLIMA
from agro_pipeline.collectors.base import Busca, Tarefa, iso, numero, quadro_canonico


class TarefaNasaPower(Tarefa):
    fonte = "nasa_power"
    # a NASA deixa buracos no meio da série (ex.: radiação nula num dia) e pode preenchê-los
    # depois; reconsultar 30 dias (= janela recente da checagem de completude) faz o pipeline
    # recuperar sozinho qualquer lacuna recente
    sobreposicao_dias = 30

    def __init__(self, ponto: str):
        self.ponto = ponto
        _, self.lat, self.lon = PONTOS_CLIMA[ponto]
        self.nome = f"nasa.{ponto}"
        self.series = tuple(f"nasa.{ponto}.{v}" for v in VARIAVEIS_CLIMA)

    def buscar(self, inicio: date, fim: date) -> Busca:
        from agrobr.sync import nasa_power

        df = nasa_power.clima_ponto(self.lat, self.lon, inicio.isoformat(), fim.isoformat())
        registros = [
            {"data": iso(r["data"]), **{v: numero(r[v]) for v in VARIAVEIS_CLIMA}}
            for r in df.to_dict("records")
        ]
        return Busca(
            metodo="agrobr.nasa_power.clima_ponto",
            parametros={
                "lat": self.lat,
                "lon": self.lon,
                "inicio": inicio.isoformat(),
                "fim": fim.isoformat(),
                "agrobr": version("agrobr"),
            },
            registros=registros,
        )

    def transformar(self, registros: list[dict[str, Any]]) -> pd.DataFrame:
        linhas = [
            (f"nasa.{self.ponto}.{v}", r["data"], r[v]) for r in registros for v in VARIAVEIS_CLIMA
        ]
        return quadro_canonico(linhas)


TAREFAS = [TarefaNasaPower(p) for p in PONTOS_CLIMA]
