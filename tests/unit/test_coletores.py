from datetime import date
from pathlib import Path

import pytest

from agro_pipeline.collectors import base
from agro_pipeline.collectors.base import FalhaBusca, com_retry
from agro_pipeline.collectors.bcb import TarefaPtax
from agro_pipeline.collectors.cepea import TarefaCepea, ler_planilha
from agro_pipeline.collectors.nasa_power import TarefaNasaPower
from agro_pipeline.pipeline import janela

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_planilha_cepea_real_e_lida_apesar_do_ole_corrompido():
    titulo, dados = ler_planilha((FIXTURES / "cepea_soja_92.xls").read_bytes())
    assert "SOJA" in titulo.upper() and "PARANAGU" in titulo.upper()
    assert list(dados.columns) == ["data", "valor_brl", "valor_usd"]
    assert dados["data"].iloc[0] == date(2006, 3, 13)
    assert dados["valor_brl"].iloc[0] == pytest.approx(27.66)
    assert dados["data"].is_monotonic_increasing
    assert dados["valor_brl"].notna().all()


def test_cepea_transforma_registros_do_agrobr_com_praca_e_unidade():
    registros = [
        {"data": "2026-09-24", "valor": 161.84, "praca": "Paranaguá/PR", "unidade": "BRL/sc60kg",
         "fonte": "cepea", "metodologia": "indicador_esalq"},
    ]
    df = TarefaCepea("soja", 92, "SOJA").transformar(registros)
    assert df.to_dict("records") == [
        {"serie": "cepea.soja", "data": date(2026, 9, 24), "valor": 161.84,
         "unidade": "BRL/sc60kg", "local": "Paranaguá/PR"}
    ]


def test_cepea_usa_planilha_quando_a_janela_e_maior_que_a_pagina_do_agrobr(monkeypatch):
    tarefa = TarefaCepea("soja", 92, "SOJA")
    chamados = []
    monkeypatch.setattr(tarefa, "_buscar_agrobr", lambda i, f: chamados.append("agrobr"))
    monkeypatch.setattr(tarefa, "_buscar_planilha", lambda i, f: chamados.append("planilha"))
    tarefa.buscar(date(2004, 1, 1), date(2026, 9, 27))
    tarefa.buscar(date(2026, 9, 17), date(2026, 9, 27))
    assert chamados == ["planilha", "agrobr"]


def test_cepea_cai_para_planilha_se_o_agrobr_falhar(monkeypatch):
    tarefa = TarefaCepea("soja", 92, "SOJA")

    def agrobr_quebrado(i, f):
        raise ConnectionError("fora do ar")

    monkeypatch.setattr(tarefa, "_buscar_agrobr", agrobr_quebrado)
    monkeypatch.setattr(tarefa, "_buscar_planilha", lambda i, f: base.Busca("cepea.planilha", {}, []))
    busca = tarefa.buscar(date(2026, 9, 17), date(2026, 9, 27))
    assert busca.metodo == "cepea.planilha"
    assert "fora do ar" in busca.parametros["fallback_de_agrobr"]


def test_ptax_gera_venda_e_compra_e_fica_com_o_ultimo_boletim_do_dia():
    registros = [
        {"data": "2026-09-25", "cotacao_compra": 5.10, "cotacao_venda": 5.11, "data_hora": "2026-09-25T10:00:00"},
        {"data": "2026-09-25", "cotacao_compra": 5.19, "cotacao_venda": 5.20, "data_hora": "2026-09-25T13:10:00"},
    ]
    df = TarefaPtax().transformar(registros)
    assert sorted(df[["serie", "valor"]].itertuples(index=False, name=None)) == [
        ("bcb.ptax_compra", 5.19), ("bcb.ptax_venda", 5.20)
    ]


def test_nasa_gera_uma_serie_por_variavel_e_mantem_nulos_para_a_validacao():
    registro = {"data": "2026-09-26", "temp_media": 25.0, "temp_max": 31.0, "temp_min": 20.0,
                "precip_mm": None, "umidade_rel": 70.0, "radiacao_mj": 18.0, "vento_ms": 0.1}
    df = TarefaNasaPower("sorriso_mt").transformar([registro])
    assert len(df) == 7
    assert set(df["serie"]) == {f"nasa.sorriso_mt.{v}" for v in registro if v != "data"}
    assert df.loc[df["serie"] == "nasa.sorriso_mt.precip_mm", "valor"].isna().all()


def test_retry_tenta_de_novo_e_desiste_depois_do_limite(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    tentativas = iter([ConnectionError("1"), ConnectionError("2"), "ok"])

    def instavel():
        r = next(tentativas)
        if isinstance(r, Exception):
            raise r
        return r

    assert com_retry(instavel) == ("ok", 3)

    def sempre_falha():
        raise TimeoutError("sem resposta")

    with pytest.raises(FalhaBusca) as exc:
        com_retry(sempre_falha)
    assert exc.value.tentativas == 3 and len(exc.value.historico) == 3


def test_janela_incremental_reconsulta_a_sobreposicao_e_serie_vazia_vai_ao_historico():
    tarefa = TarefaPtax()
    hoje, desde = date(2026, 9, 27), date(2004, 1, 1)
    ultimas = {"bcb.ptax_venda": date(2026, 9, 25), "bcb.ptax_compra": date(2026, 9, 24)}
    assert janela(tarefa, ultimas, "incremental", desde, hoje) == (date(2026, 9, 14), hoje)
    assert janela(tarefa, {"bcb.ptax_venda": date(2026, 9, 25)}, "incremental", desde, hoje) == (desde, hoje)
    assert janela(tarefa, ultimas, "backfill", desde, hoje) == (desde, hoje)
