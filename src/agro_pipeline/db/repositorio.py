"""Acesso ao banco: execuções, coletas e gravação idempotente de observações."""

import json
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import Connection, text

# diferença mínima para considerar que a fonte revisou um valor
TOLERANCIA = 1e-9


def abrir_execucao(conn: Connection, modo: str, ambiente: str, versao: str | None, parametros: dict) -> int:
    return conn.execute(
        text("""
            INSERT INTO execucao (modo, ambiente, versao_codigo, parametros)
            VALUES (:modo, :ambiente, :versao, CAST(:parametros AS jsonb))
            RETURNING id
        """),
        {"modo": modo, "ambiente": ambiente, "versao": versao, "parametros": json.dumps(parametros)},
    ).scalar_one()


def fechar_execucao(conn: Connection, execucao_id: int, status: str, erro: str | None = None) -> None:
    conn.execute(
        text("UPDATE execucao SET status = :status, erro = :erro, finalizada_em = now() WHERE id = :id"),
        {"id": execucao_id, "status": status, "erro": erro},
    )


def registrar_coleta(conn: Connection, execucao_id: int, fonte: str, **campos: Any) -> int:
    """Insere uma linha em `coleta`. `payload`, `parametros` e `rejeicoes` são serializados em JSON."""
    valores = {
        "metodo": None,
        "parametros": {},
        "status": "sucesso",
        "tentativas": 1,
        "duracao_ms": None,
        "erro": None,
        "linhas_recebidas": None,
        "linhas_rejeitadas": None,
        "rejeicoes": {},
        "payload": None,
        "hash_payload": None,
    } | campos
    for chave in ("parametros", "rejeicoes", "payload"):
        valores[chave] = None if valores[chave] is None else json.dumps(valores[chave], ensure_ascii=False)
    return conn.execute(
        text("""
            INSERT INTO coleta (execucao_id, fonte_id, metodo, parametros, status, tentativas,
                                duracao_ms, erro, linhas_recebidas, linhas_rejeitadas, rejeicoes,
                                payload, hash_payload)
            VALUES (:execucao_id, (SELECT id FROM fonte WHERE codigo = :fonte), :metodo,
                    CAST(:parametros AS jsonb), :status, :tentativas, :duracao_ms, :erro,
                    :linhas_recebidas, :linhas_rejeitadas, CAST(:rejeicoes AS jsonb),
                    CAST(:payload AS jsonb), :hash_payload)
            RETURNING id
        """),
        {"execucao_id": execucao_id, "fonte": fonte, **valores},
    ).scalar_one()


def atualizar_contagens(conn: Connection, coleta_id: int, inseridas: int, revisadas: int) -> None:
    conn.execute(
        text("UPDATE coleta SET linhas_inseridas = :i, linhas_revisadas = :r WHERE id = :id"),
        {"id": coleta_id, "i": inseridas, "r": revisadas},
    )


def ultima_data_por_serie(conn: Connection) -> dict[str, date]:
    return dict(
        conn.execute(
            text("SELECT s.codigo, max(o.data) FROM serie s JOIN observacao o ON o.serie_id = s.id GROUP BY s.codigo")
        ).all()
    )


def gravar_observacoes(conn: Connection, coleta_id: int, df: pd.DataFrame) -> tuple[int, int]:
    """Grava (serie, data, valor) de forma idempotente. Devolve (inseridas, revisadas).

    - data nova para a série -> inserida;
    - valor igual ao já gravado -> ignorada (reexecutar não muda nada);
    - valor diferente -> atualizada, com o valor anterior registrado em observacao_revisao.
    """
    if df.empty:
        return 0, 0

    ids = dict(conn.execute(text("SELECT codigo, id FROM serie")).all())
    conn.exec_driver_sql(
        "CREATE TEMP TABLE _stg_observacao (serie_id int, data date, valor double precision) ON COMMIT DROP"
    )
    # COPY: carga em lote (o backfill tem ~200 mil linhas; INSERT linha a linha seria lento)
    with conn.connection.driver_connection.cursor() as cur:
        with cur.copy("COPY _stg_observacao (serie_id, data, valor) FROM STDIN") as copia:
            for serie, data, valor in df[["serie", "data", "valor"]].itertuples(index=False):
                copia.write_row((ids[serie], data, float(valor)))

    parametros = {"coleta_id": coleta_id, "tol": TOLERANCIA}
    conn.execute(
        text("""
            INSERT INTO observacao_revisao (serie_id, data, valor_anterior, valor_novo, coleta_id)
            SELECT o.serie_id, o.data, o.valor, t.valor, :coleta_id
            FROM _stg_observacao t
            JOIN observacao o ON o.serie_id = t.serie_id AND o.data = t.data
            WHERE abs(o.valor - t.valor) > :tol
        """),
        parametros,
    )
    inseridas, revisadas = conn.execute(
        text("""
            WITH gravadas AS (
                INSERT INTO observacao (serie_id, data, valor, coleta_id)
                SELECT serie_id, data, valor, :coleta_id FROM _stg_observacao
                ON CONFLICT (serie_id, data) DO UPDATE
                SET valor = EXCLUDED.valor, coleta_id = EXCLUDED.coleta_id, atualizada_em = now()
                WHERE abs(observacao.valor - EXCLUDED.valor) > :tol
                RETURNING (xmax = 0) AS inserida
            )
            SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida) FROM gravadas
        """),
        parametros,
    ).one()
    return inseridas, revisadas
