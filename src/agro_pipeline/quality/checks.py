"""Checagens de qualidade sobre o que já está gravado em `observacao`.

Diferente da validação de entrada (que rejeita linhas), estas regras não alteram dados:
produzem alertas em `checagem_qualidade`. Rodam ao fim de cada execução e pelo comando
`qualidade`. Os parâmetros de cada série vêm do catálogo.

Regras por série:
- completude       : dias esperados pelo calendário da série sem valor (gaps)
- defasagem        : dias desde o último dado (fonte quebrada em silêncio) -> erro
- saltos           : variação diária anômala (z-score robusto), preço e câmbio
- valores_repetidos: mesmo valor em dias seguidos (dado congelado), preço e câmbio
- faixa_tipica     : mediana dos últimos 365 dias fora da faixa típica, clima
Regras por execução: rejeicoes, revisoes (informativas).
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import holidays
import numpy as np
import pandas as pd
from sqlalchemy import Connection, text

from agro_pipeline.catalogo import NAO_PUBLICA, SERIES, Serie

JANELA_RECENTE = 30  # dias corridos: problema recente reprova a checagem
# saltos: z-score robusto dos log-retornos, janela móvel de 60 observações
SALTO_JANELA = 60
SALTO_PISO_VOL = 0.01  # piso do desvio robusto (1%/dia): evita z infinito em trechos parados
SALTO_LIMITE_Z = 6.0
REPETIDOS_LIMITE = 5  # dias seguidos com o mesmo valor


@dataclass
class Checagem:
    regra: str
    severidade: str  # info | aviso | erro
    aprovada: bool
    serie: str | None = None
    detalhe: dict[str, Any] = field(default_factory=dict)


# Calendário ------------------------------------------------------------------


@lru_cache(maxsize=8)
def _feriados(fonte: str, ano_min: int, ano_max: int) -> tuple[date, ...]:
    dias = set(holidays.financial_holidays("BVMF", years=range(ano_min, ano_max + 1)))
    for ano in range(ano_min, ano_max + 1):
        dias |= {date(ano, m, d) for m, d in NAO_PUBLICA.get(fonte, [])}
    return tuple(sorted(dias))


def dias_esperados(serie: Serie, inicio: date, fim: date) -> pd.DatetimeIndex:
    """Datas em que a série deveria ter valor, entre inicio e fim (inclusive)."""
    if inicio > fim:
        return pd.DatetimeIndex([])
    if serie.calendario == "dias_corridos":
        return pd.date_range(inicio, fim, freq="D")
    feriados = _feriados(serie.fonte, inicio.year, fim.year)
    return pd.bdate_range(inicio, fim, freq="C", holidays=list(feriados))


# Regras por série ------------------------------------------------------------


def checar_completude(serie: Serie, datas: pd.Series) -> Checagem:
    presentes = pd.DatetimeIndex(pd.to_datetime(datas)).unique().sort_values()
    esperados = dias_esperados(serie, presentes[0].date(), presentes[-1].date())
    faltantes = esperados.difference(presentes)
    extras = presentes.difference(esperados)
    limite_recente = presentes[-1] - pd.Timedelta(days=JANELA_RECENTE)
    recentes = faltantes[faltantes > limite_recente]

    maior = None
    if len(faltantes):
        # sequências consecutivas no calendário da série
        pos = esperados.get_indexer(faltantes)
        quebras = np.flatnonzero(np.diff(pos) != 1)
        inicios = np.r_[0, quebras + 1]
        fins = np.r_[quebras, len(pos) - 1]
        i = int(np.argmax(fins - inicios))
        maior = {
            "inicio": faltantes[inicios[i]].date().isoformat(),
            "fim": faltantes[fins[i]].date().isoformat(),
            "dias": int(fins[i] - inicios[i] + 1),
        }

    return Checagem(
        regra="completude",
        severidade="aviso",
        aprovada=len(recentes) == 0,
        serie=serie.codigo,
        detalhe={
            "esperados": len(esperados),
            "faltantes": len(faltantes),
            "completude": round(1 - len(faltantes) / len(esperados), 5),
            "faltantes_recentes": [d.date().isoformat() for d in recentes],
            "ultimos_faltantes": [d.date().isoformat() for d in faltantes[-5:]],
            "maior_lacuna": maior,
            "fora_do_calendario": len(extras),
        },
    )


def checar_defasagem(serie: Serie, ultima: date, hoje: date) -> Checagem:
    atraso = len(dias_esperados(serie, ultima + timedelta(days=1), hoje))
    return Checagem(
        regra="defasagem",
        severidade="erro",
        aprovada=atraso <= serie.defasagem_max,
        serie=serie.codigo,
        detalhe={"ultima_data": ultima.isoformat(), "dias_sem_dado": atraso, "maximo": serie.defasagem_max},
    )


def checar_saltos(serie: Serie, df: pd.DataFrame) -> Checagem:
    """Log-retorno diário comparado à mediana/MAD das 60 observações anteriores."""
    ret = np.log(df["valor"]).diff()
    # shift(1): a referência de cada dia usa só os dias anteriores a ele
    mediana = ret.rolling(SALTO_JANELA, min_periods=20).median().shift(1)
    desvio = (
        (ret - mediana).abs().rolling(SALTO_JANELA, min_periods=20).median().shift(1) * 1.4826
    ).clip(lower=SALTO_PISO_VOL)
    z = (ret - mediana) / desvio
    saltos = df.assign(retorno=ret, z=z)[z.abs() > SALTO_LIMITE_Z]
    limite_recente = df["data"].iloc[-1] - timedelta(days=JANELA_RECENTE)
    recentes = saltos[saltos["data"] > limite_recente]

    def listar(quadro: pd.DataFrame) -> list[dict]:
        return [
            {"data": d.isoformat(), "valor": round(v, 4), "variacao_pct": round(100 * np.expm1(r), 2), "z": round(zz, 1)}
            for d, v, r, zz in quadro[["data", "valor", "retorno", "z"]].itertuples(index=False)
        ]

    return Checagem(
        regra="saltos",
        severidade="aviso",
        aprovada=recentes.empty,
        serie=serie.codigo,
        detalhe={
            "limite_z": SALTO_LIMITE_Z,
            "total_historico": len(saltos),
            "recentes": listar(recentes),
            "maiores": listar(saltos.reindex(saltos["z"].abs().sort_values(ascending=False).index).head(5)),
        },
    )


def checar_repetidos(serie: Serie, df: pd.DataFrame) -> Checagem:
    """Maior sequência de dias seguidos com exatamente o mesmo valor."""
    grupo = (df["valor"].diff() != 0).cumsum()
    seqs = df.groupby(grupo).agg(inicio=("data", "first"), fim=("data", "last"), n=("valor", "size"), valor=("valor", "first"))
    maior = seqs.loc[seqs["n"].idxmax()]
    limite_recente = df["data"].iloc[-1] - timedelta(days=JANELA_RECENTE)
    recentes = seqs[(seqs["fim"] > limite_recente) & (seqs["n"] >= REPETIDOS_LIMITE)]
    return Checagem(
        regra="valores_repetidos",
        severidade="aviso",
        aprovada=recentes.empty,
        serie=serie.codigo,
        detalhe={
            "limite": REPETIDOS_LIMITE,
            "sequencias_acima_do_limite": int((seqs["n"] >= REPETIDOS_LIMITE).sum()),
            "pct_dias_sem_variacao": round(float((df["valor"].diff() == 0).mean()), 4),
            "maior_sequencia": {
                "inicio": maior["inicio"].isoformat(),
                "fim": maior["fim"].isoformat(),
                "dias": int(maior["n"]),
                "valor": float(maior["valor"]),
            },
        },
    )


def checar_faixa_tipica(serie: Serie, df: pd.DataFrame) -> Checagem:
    ultimo_ano = df[df["data"] > df["data"].iloc[-1] - timedelta(days=365)]
    mediana = float(ultimo_ano["valor"].median())
    return Checagem(
        regra="faixa_tipica",
        severidade="aviso",
        aprovada=serie.tipico_min <= mediana <= serie.tipico_max,
        serie=serie.codigo,
        detalhe={"mediana_365d": round(mediana, 3), "faixa": [serie.tipico_min, serie.tipico_max]},
    )


def checar_serie(serie: Serie, df: pd.DataFrame, hoje: date) -> list[Checagem]:
    """df: colunas data (date) e valor, de uma única série."""
    if df.empty:
        return [Checagem("completude", "erro", False, serie.codigo, {"motivo": "série sem dados"})]
    df = df.sort_values("data").reset_index(drop=True)
    checagens = [checar_completude(serie, df["data"]), checar_defasagem(serie, df["data"].iloc[-1], hoje)]
    if serie.categoria in ("preco", "cambio"):
        checagens += [checar_saltos(serie, df), checar_repetidos(serie, df)]
    if serie.tipico_min is not None and serie.tipico_max is not None:
        checagens.append(checar_faixa_tipica(serie, df))
    return checagens


# Regras por execução ---------------------------------------------------------


def checar_execucao(conn: Connection, execucao_id: int) -> list[Checagem]:
    rejeicoes: dict[str, int] = {}
    for (r,) in conn.execute(text("SELECT rejeicoes FROM coleta WHERE execucao_id = :id"), {"id": execucao_id}):
        for motivo, n in (r or {}).items():
            rejeicoes[motivo] = rejeicoes.get(motivo, 0) + n
    revisoes = conn.execute(
        text("""
            SELECT s.codigo, count(*) FROM observacao_revisao r
            JOIN coleta c ON c.id = r.coleta_id JOIN serie s ON s.id = r.serie_id
            WHERE c.execucao_id = :id GROUP BY s.codigo
        """),
        {"id": execucao_id},
    ).all()
    return [
        Checagem("rejeicoes", "info", True, detalhe={"por_motivo": rejeicoes, "total": sum(rejeicoes.values())}),
        Checagem("revisoes", "info", True, detalhe={"por_serie": dict(revisoes), "total": sum(n for _, n in revisoes)}),
    ]


# Execução --------------------------------------------------------------------


def executar_checagens(conn: Connection, hoje: date, execucao_id: int | None = None) -> list[Checagem]:
    obs = pd.read_sql(
        text("SELECT s.codigo AS serie, o.data, o.valor FROM observacao o JOIN serie s ON s.id = o.serie_id WHERE s.ativa"),
        conn,
    )
    por_serie = {codigo: g[["data", "valor"]] for codigo, g in obs.groupby("serie")}
    vazio = pd.DataFrame(columns=["data", "valor"])

    checagens = [c for s in SERIES for c in checar_serie(s, por_serie.get(s.codigo, vazio), hoje)]
    if execucao_id is not None:
        checagens += checar_execucao(conn, execucao_id)

    conn.execute(
        text("""
            INSERT INTO checagem_qualidade (execucao_id, serie_id, regra, severidade, aprovada, detalhe)
            VALUES (:execucao_id, (SELECT id FROM serie WHERE codigo = :serie), :regra, :severidade,
                    :aprovada, CAST(:detalhe AS jsonb))
        """),
        [
            {"execucao_id": execucao_id, "serie": c.serie, "regra": c.regra, "severidade": c.severidade,
             "aprovada": c.aprovada, "detalhe": json.dumps(c.detalhe, ensure_ascii=False, default=str)}
            for c in checagens
        ],
    )
    return checagens
