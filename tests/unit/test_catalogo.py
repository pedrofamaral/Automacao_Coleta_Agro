from agro_pipeline.catalogo import FONTES, SERIES, coluna_dataset
from agro_pipeline.db.inicializar import sql_view_dataset


def test_codigos_de_serie_sao_unicos():
    codigos = [s.codigo for s in SERIES]
    assert len(codigos) == len(set(codigos))


def test_toda_serie_aponta_para_fonte_cadastrada():
    fontes = {f.codigo for f in FONTES}
    assert {s.fonte for s in SERIES} <= fontes


def test_valores_de_dominio_batem_com_os_checks_do_schema():
    for s in SERIES:
        assert s.categoria in {"preco", "cambio", "clima"}
        assert s.frequencia in {"diaria", "semanal", "mensal", "anual"}
        assert s.calendario in {"dias_uteis", "dias_corridos"}
        if s.limite_min is not None and s.limite_max is not None:
            assert s.limite_min < s.limite_max


def test_mvp_tem_as_series_esperadas():
    assert len(SERIES) == 2 + 2 + 3 * 7


def test_view_do_dataset_tem_uma_coluna_por_serie_diaria():
    sql = sql_view_dataset(SERIES)
    for s in SERIES:
        assert f"AS {coluna_dataset(s.codigo)}" in sql
    assert "security_invoker" in sql
