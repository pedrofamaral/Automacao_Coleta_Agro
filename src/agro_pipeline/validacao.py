"""Validação de entrada: o que não passa aqui não entra em `observacao`.

Cada linha rejeitada é contada por motivo (gravado em coleta.rejeicoes).
"""

from collections import Counter
from datetime import date

import pandas as pd

from agro_pipeline.catalogo import SERIES, Serie
from agro_pipeline.collectors.base import COLUNAS_CANONICAS

CATALOGO: dict[str, Serie] = {s.codigo: s for s in SERIES}


def validar(
    df: pd.DataFrame, hoje: date, catalogo: dict[str, Serie] = CATALOGO
) -> tuple[pd.DataFrame, dict[str, int]]:
    motivos: Counter[str] = Counter()
    df = df.reset_index(drop=True)
    rejeitada = pd.Series(False, index=df.index)

    def rejeitar(mascara: pd.Series, motivo: str) -> None:
        # cada linha conta só no primeiro motivo em que cai
        nonlocal rejeitada
        nova = mascara.fillna(False).astype(bool) & ~rejeitada
        if n := int(nova.sum()):
            motivos[motivo] += n
        rejeitada = rejeitada | nova

    serie = df["serie"].map(catalogo.get)
    rejeitar(serie.isna(), "serie_desconhecida")
    rejeitar(df["valor"].isna(), "nulo")
    rejeitar(df["data"].isna(), "data_invalida")
    rejeitar(df["data"] > hoje, "data_futura")

    unidade = serie.map(lambda s: s.unidade if s else None)
    local = serie.map(lambda s: s.local if s else None)
    minimo = serie.map(lambda s: s.limite_min if s else None).astype(float)
    maximo = serie.map(lambda s: s.limite_max if s else None).astype(float)
    positiva = serie.map(lambda s: bool(s and s.categoria in ("preco", "cambio")))

    if "unidade" in df:
        rejeitar(df["unidade"] != unidade, "unidade_divergente")
    if "local" in df:
        rejeitar(df["local"] != local, "local_divergente")
    rejeitar(positiva & (df["valor"] <= 0), "nao_positivo")
    rejeitar(minimo.notna() & (df["valor"] < minimo), "abaixo_do_limite")
    rejeitar(maximo.notna() & (df["valor"] > maximo), "acima_do_limite")
    rejeitar(df.duplicated(["serie", "data"], keep="first"), "duplicada")

    return df.loc[~rejeitada, COLUNAS_CANONICAS].reset_index(drop=True), dict(motivos)
