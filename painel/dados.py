"""Consultas ao banco usadas pelo painel (com cache de 5 minutos)."""

import pandas as pd
import streamlit as st
from sqlalchemy import text

from agro_pipeline.db.conexao import engine


def _ler(sql: str, **params) -> pd.DataFrame:
    with engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


@st.cache_data(ttl=300, show_spinner=False)
def execucoes() -> pd.DataFrame:
    return _ler("""
        SELECT e.id, e.iniciada_em AT TIME ZONE 'America/Sao_Paulo' AS inicio, e.modo, e.ambiente,
               e.versao_codigo, e.status,
               EXTRACT(EPOCH FROM e.finalizada_em - e.iniciada_em) AS duracao_s,
               count(c.id) FILTER (WHERE c.status = 'sucesso') AS coletas_ok,
               count(c.id) FILTER (WHERE c.status = 'falha') AS coletas_falha,
               coalesce(sum(c.linhas_recebidas), 0) AS recebidas,
               coalesce(sum(c.linhas_rejeitadas), 0) AS rejeitadas,
               coalesce(sum(c.linhas_inseridas), 0) AS inseridas,
               coalesce(sum(c.linhas_revisadas), 0) AS revisadas
        FROM execucao e LEFT JOIN coleta c ON c.execucao_id = e.id
        GROUP BY e.id ORDER BY e.id DESC
    """)


@st.cache_data(ttl=300, show_spinner=False)
def coletas(execucao_id: int) -> pd.DataFrame:
    return _ler("""
        SELECT c.id, f.codigo AS fonte, c.metodo, c.status, c.tentativas, c.duracao_ms,
               c.linhas_recebidas, c.linhas_rejeitadas, c.linhas_inseridas, c.linhas_revisadas,
               c.rejeicoes, c.parametros, c.erro
        FROM coleta c JOIN fonte f ON f.id = c.fonte_id
        WHERE c.execucao_id = :id ORDER BY c.id
    """, id=execucao_id)


@st.cache_data(ttl=300, show_spinner=False)
def total_observacoes() -> int:
    return int(_ler("SELECT count(*) AS n FROM observacao")["n"].iloc[0])


@st.cache_data(ttl=300, show_spinner=False)
def checagens_recentes() -> pd.DataFrame:
    """Último lote de checagens (um lote = um INSERT, mesmo criada_em)."""
    return _ler("""
        SELECT q.execucao_id, s.codigo AS serie, s.categoria, q.regra, q.severidade, q.aprovada,
               q.detalhe, q.criada_em AT TIME ZONE 'America/Sao_Paulo' AS criada_em
        FROM checagem_qualidade q LEFT JOIN serie s ON s.id = q.serie_id
        WHERE q.criada_em = (SELECT max(criada_em) FROM checagem_qualidade)
        ORDER BY q.id
    """)


@st.cache_data(ttl=300, show_spinner=False)
def catalogo() -> pd.DataFrame:
    return _ler("SELECT codigo, categoria, produto, variavel, local, unidade, descricao FROM serie WHERE ativa ORDER BY id")


@st.cache_data(ttl=300, show_spinner=False)
def serie(codigo: str) -> pd.DataFrame:
    df = _ler("""
        SELECT o.data, o.valor FROM observacao o JOIN serie s ON s.id = o.serie_id
        WHERE s.codigo = :codigo ORDER BY o.data
    """, codigo=codigo)
    df["data"] = pd.to_datetime(df["data"])
    return df


@st.cache_data(ttl=300, show_spinner=False)
def dataset() -> pd.DataFrame:
    df = _ler("SELECT * FROM vw_dataset_diario")
    df["data"] = pd.to_datetime(df["data"])
    return df.set_index("data")
