from datetime import date

import pandas as pd

from agro_pipeline.validacao import validar

HOJE = date(2026, 9, 27)


def quadro(linhas, **extras):
    df = pd.DataFrame(linhas, columns=["serie", "data", "valor"])
    for coluna, valores in extras.items():
        df[coluna] = valores
    return df


def test_linhas_validas_passam_intactas():
    df = quadro([("cepea.soja", date(2026, 9, 25), 161.0), ("nasa.sorriso_mt.precip_mm", date(2026, 9, 25), 0.0)])
    validas, rejeicoes = validar(df, HOJE)
    assert len(validas) == 2 and rejeicoes == {}


def test_rejeita_por_motivo_contando_cada_linha_uma_vez():
    df = quadro([
        ("cepea.soja", date(2026, 9, 25), 161.0),          # ok
        ("cepea.soja", date(2026, 9, 25), 162.0),          # duplicada
        ("cepea.soja", date(2026, 9, 24), None),           # nulo
        ("cepea.soja", date(2026, 9, 30), 160.0),          # futura
        ("cepea.soja", date(2026, 9, 23), 0.0),            # preço não positivo
        ("nasa.sorriso_mt.umidade_rel", date(2026, 9, 25), 130.0),  # acima de 100%
        ("nasa.sorriso_mt.precip_mm", date(2026, 9, 25), -1.0),     # abaixo de 0
        ("serie.que.nao.existe", date(2026, 9, 25), 1.0),
    ])
    validas, rejeicoes = validar(df, HOJE)
    assert validas.to_dict("records") == [{"serie": "cepea.soja", "data": date(2026, 9, 25), "valor": 161.0}]
    assert rejeicoes == {
        "duplicada": 1, "nulo": 1, "data_futura": 1, "nao_positivo": 1,
        "acima_do_limite": 1, "abaixo_do_limite": 1, "serie_desconhecida": 1,
    }


def test_confere_unidade_e_praca_quando_a_fonte_informa():
    df = quadro(
        [("cepea.soja", date(2026, 9, 24), 161.0), ("cepea.soja", date(2026, 9, 25), 161.0),
         ("cepea.soja", date(2026, 9, 23), 161.0)],
        unidade=["BRL/sc60kg", "USD/sc60kg", "BRL/sc60kg"],
        local=["Paranaguá/PR", "Paranaguá/PR", "Paraná"],
    )
    validas, rejeicoes = validar(df, HOJE)
    assert len(validas) == 1
    assert rejeicoes == {"unidade_divergente": 1, "local_divergente": 1}
