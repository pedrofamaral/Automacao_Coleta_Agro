"""Banco Central — dólar PTAX (compra e venda), via agrobr."""

from datetime import date
from importlib.metadata import version
from typing import Any

import pandas as pd

from agro_pipeline.collectors.base import Busca, Tarefa, iso, numero, quadro_canonico


class TarefaPtax(Tarefa):
    fonte = "bcb"
    nome = "bcb.ptax"
    series = ("bcb.ptax_venda", "bcb.ptax_compra")

    def buscar(self, inicio: date, fim: date) -> Busca:
        from agrobr.sync import bcb

        # a API da PTAX espera dd/mm/aaaa
        df = bcb.ptax(data_inicial=inicio.strftime("%d/%m/%Y"), data_final=fim.strftime("%d/%m/%Y"))
        registros = [
            {
                "data": iso(r.data),
                "cotacao_compra": numero(r.cotacao_compra),
                "cotacao_venda": numero(r.cotacao_venda),
                "data_hora": pd.Timestamp(r.data_hora).isoformat(),
            }
            for r in df.itertuples()
        ]
        return Busca(
            metodo="agrobr.bcb.ptax",
            parametros={"inicio": inicio.isoformat(), "fim": fim.isoformat(), "agrobr": version("agrobr")},
            registros=registros,
        )

    def transformar(self, registros: list[dict[str, Any]]) -> pd.DataFrame:
        if not registros:
            return quadro_canonico([])
        df = pd.DataFrame(registros)
        # se houver mais de um boletim no dia, vale o último (fechamento)
        df = df.sort_values("data_hora").drop_duplicates("data", keep="last")
        linhas = [
            (f"bcb.ptax_{lado}", r["data"], r[f"cotacao_{lado}"])
            for r in df.to_dict("records")
            for lado in ("venda", "compra")
        ]
        return quadro_canonico(linhas)


TAREFAS = [TarefaPtax()]
