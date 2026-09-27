"""Criação do schema, carga do catálogo e geração da view do dataset (comando init-db)."""

import re
from importlib.resources import files

from sqlalchemy import Connection, text

from agro_pipeline.catalogo import FONTES, SERIES, Serie, coluna_dataset
from agro_pipeline.db.conexao import engine

_CODIGO_VALIDO = re.compile(r"^[a-z0-9_.]+$")


def sql_schema() -> str:
    return files("agro_pipeline.db").joinpath("schema.sql").read_text(encoding="utf-8")


def sql_view_dataset(series: list[Serie]) -> str:
    """View com uma linha por dia corrido e uma coluna por série diária.

    Gerada a partir do catálogo para que novas séries virem colunas sem SQL manual.
    """
    diarias = [s for s in series if s.frequencia == "diaria"]
    for s in diarias:
        if not _CODIGO_VALIDO.match(s.codigo):
            raise ValueError(f"código de série inválido para coluna: {s.codigo!r}")

    colunas = ",\n".join(
        f"       MAX(o.valor) FILTER (WHERE s.codigo = '{s.codigo}') AS {coluna_dataset(s.codigo)}"
        for s in diarias
    )
    return f"""
DROP VIEW IF EXISTS vw_dataset_diario;
CREATE VIEW vw_dataset_diario WITH (security_invoker = true) AS
WITH dias AS (
    SELECT generate_series(min(data), max(data), interval '1 day')::date AS data
    FROM observacao
)
SELECT d.data,
{colunas}
FROM dias d
LEFT JOIN observacao o ON o.data = d.data
LEFT JOIN serie s ON s.id = o.serie_id
GROUP BY d.data
ORDER BY d.data;
"""


def _gravar_catalogo(conn: Connection) -> None:
    conn.execute(
        text("""
            INSERT INTO fonte (codigo, nome, url, licenca)
            VALUES (:codigo, :nome, :url, :licenca)
            ON CONFLICT (codigo) DO UPDATE
            SET nome = EXCLUDED.nome, url = EXCLUDED.url, licenca = EXCLUDED.licenca
        """),
        [vars(f) for f in FONTES],
    )
    conn.execute(
        text("""
            INSERT INTO serie (codigo, fonte_id, categoria, produto, variavel, local, lat, lon,
                               unidade, frequencia, calendario, limite_min, limite_max, descricao, ativa)
            VALUES (:codigo, (SELECT id FROM fonte WHERE codigo = :fonte), :categoria, :produto,
                    :variavel, :local, :lat, :lon, :unidade, :frequencia, :calendario,
                    :limite_min, :limite_max, :descricao, TRUE)
            ON CONFLICT (codigo) DO UPDATE
            SET fonte_id = EXCLUDED.fonte_id, categoria = EXCLUDED.categoria,
                produto = EXCLUDED.produto, variavel = EXCLUDED.variavel, local = EXCLUDED.local,
                lat = EXCLUDED.lat, lon = EXCLUDED.lon, unidade = EXCLUDED.unidade,
                frequencia = EXCLUDED.frequencia, calendario = EXCLUDED.calendario,
                limite_min = EXCLUDED.limite_min, limite_max = EXCLUDED.limite_max,
                descricao = EXCLUDED.descricao, ativa = TRUE
        """),
        [vars(s) for s in SERIES],
    )
    # séries removidas do catálogo ficam inativas (o histórico é preservado)
    conn.execute(
        text("UPDATE serie SET ativa = FALSE WHERE NOT (codigo = ANY(:codigos))"),
        {"codigos": [s.codigo for s in SERIES]},
    )


def inicializar() -> dict[str, int]:
    with engine().begin() as conn:
        conn.exec_driver_sql(sql_schema())
        _gravar_catalogo(conn)
        conn.exec_driver_sql(sql_view_dataset(SERIES))
        return {
            "fontes": conn.execute(text("SELECT count(*) FROM fonte")).scalar_one(),
            "series_ativas": conn.execute(text("SELECT count(*) FROM serie WHERE ativa")).scalar_one(),
        }
