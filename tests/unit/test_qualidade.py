from datetime import date

import numpy as np
import pandas as pd

from agro_pipeline.quality.checks import (
    checar_completude,
    checar_defasagem,
    checar_faixa_tipica,
    checar_repetidos,
    checar_saltos,
    checar_serie,
    dias_esperados,
)
from agro_pipeline.validacao import CATALOGO

SOJA = CATALOGO["cepea.soja"]
PTAX = CATALOGO["bcb.ptax_venda"]
VENTO = CATALOGO["nasa.sorriso_mt.vento_ms"]
TEMP = CATALOGO["nasa.sorriso_mt.temp_media"]


def serie_uteis(serie, inicio, fim, valores=None, sem=()):
    datas = [d.date() for d in dias_esperados(serie, inicio, fim) if d.date() not in set(sem)]
    rng = np.random.default_rng(0)
    if valores is None:
        valores = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(datas))))
    return pd.DataFrame({"data": datas, "valor": valores[: len(datas)]})


def test_calendario_segue_a_b3_e_os_dias_sem_publicacao_do_cepea():
    carnaval = dias_esperados(PTAX, date(2026, 2, 13), date(2026, 2, 18))
    assert [d.date() for d in carnaval] == [date(2026, 2, 13), date(2026, 2, 18)]
    natal_cepea = dias_esperados(SOJA, date(2025, 12, 22), date(2025, 12, 26))
    natal_ptax = dias_esperados(PTAX, date(2025, 12, 22), date(2025, 12, 26))
    assert date(2025, 12, 24) not in {d.date() for d in natal_cepea}
    assert date(2025, 12, 24) in {d.date() for d in natal_ptax}


def test_completude_conta_faltantes_e_reprova_so_se_forem_recentes():
    df = serie_uteis(PTAX, date(2026, 1, 2), date(2026, 9, 25), sem=[date(2026, 3, 10), date(2026, 3, 11)])
    c = checar_completude(PTAX, df["data"])
    assert c.aprovada
    assert c.detalhe["faltantes"] == 2
    assert c.detalhe["maior_lacuna"] == {"inicio": "2026-03-10", "fim": "2026-03-11", "dias": 2}

    df = serie_uteis(PTAX, date(2026, 1, 2), date(2026, 9, 25), sem=[date(2026, 9, 22)])
    c = checar_completude(PTAX, df["data"])
    assert not c.aprovada and c.detalhe["faltantes_recentes"] == ["2026-09-22"]


def test_defasagem_conta_dias_uteis_e_e_erro():
    # sexta 25/09 -> segunda 28/09: 1 dia útil sem dado
    assert checar_defasagem(SOJA, date(2026, 9, 25), date(2026, 9, 28)).aprovada
    c = checar_defasagem(SOJA, date(2026, 9, 18), date(2026, 9, 28))
    assert not c.aprovada and c.severidade == "erro" and c.detalhe["dias_sem_dado"] == 6


def test_saltos_detecta_variacao_anomala_recente():
    df = serie_uteis(SOJA, date(2026, 1, 2), date(2026, 9, 25))
    assert checar_saltos(SOJA, df).aprovada
    df.loc[df.index[-3]:, "valor"] *= 1.15  # +15% num dia
    c = checar_saltos(SOJA, df)
    assert not c.aprovada
    # +15% injetado somado ao ruído do próprio dia (~1%)
    assert 12 < c.detalhe["recentes"][0]["variacao_pct"] < 18


def test_valores_repetidos_detecta_dado_congelado():
    df = serie_uteis(SOJA, date(2026, 6, 1), date(2026, 9, 25))
    assert checar_repetidos(SOJA, df).aprovada
    df.loc[df.index[-6]:, "valor"] = 150.0
    c = checar_repetidos(SOJA, df)
    assert not c.aprovada and c.detalhe["maior_sequencia"]["dias"] == 6


def test_faixa_tipica_pega_o_vento_da_nasa():
    datas = pd.date_range("2025-09-01", "2026-09-24").date
    assert not checar_faixa_tipica(VENTO, pd.DataFrame({"data": datas, "valor": 0.08})).aprovada
    assert checar_faixa_tipica(TEMP, pd.DataFrame({"data": datas, "valor": 25.0})).aprovada


def test_regras_aplicadas_por_categoria_e_serie_vazia_e_erro():
    df = serie_uteis(SOJA, date(2026, 1, 2), date(2026, 9, 25))
    assert [c.regra for c in checar_serie(SOJA, df, date(2026, 9, 27))] == [
        "completude", "defasagem", "saltos", "valores_repetidos"
    ]
    vazia = checar_serie(SOJA, pd.DataFrame(columns=["data", "valor"]), date(2026, 9, 27))
    assert len(vazia) == 1 and vazia[0].severidade == "erro" and not vazia[0].aprovada
