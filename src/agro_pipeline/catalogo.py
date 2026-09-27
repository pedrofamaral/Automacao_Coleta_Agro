"""Catálogo de fontes e séries do MVP.

É a fonte da verdade do que o pipeline coleta: o `init-db` grava este catálogo nas
tabelas `fonte` e `serie`, e os coletores usam os códigos daqui.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Fonte:
    codigo: str
    nome: str
    url: str
    licenca: str


@dataclass(frozen=True)
class Serie:
    codigo: str
    fonte: str
    categoria: str  # preco | cambio | clima
    variavel: str
    unidade: str
    calendario: str  # dias_uteis | dias_corridos
    frequencia: str = "diaria"
    produto: str | None = None
    local: str | None = None
    lat: float | None = None
    lon: float | None = None
    limite_min: float | None = None
    limite_max: float | None = None
    descricao: str | None = None
    # parâmetros das checagens de qualidade (quality/checks.py)
    defasagem_max: int = 3  # dias sem dado novo tolerados, na unidade do calendário
    tipico_min: float | None = None  # faixa típica da mediana dos últimos 365 dias
    tipico_max: float | None = None


# dias úteis em que a fonte não publica, além dos feriados da B3 (mês, dia)
NAO_PUBLICA: dict[str, list[tuple[int, int]]] = {
    "cepea": [(12, 24), (12, 31)],
}


FONTES: list[Fonte] = [
    Fonte(
        codigo="cepea",
        nome="CEPEA/ESALQ-USP",
        url="https://www.cepea.esalq.usp.br",
        licenca="CC BY-NC 4.0 (uso comercial requer autorização do CEPEA)",
    ),
    Fonte(
        codigo="bcb",
        nome="Banco Central do Brasil (PTAX)",
        url="https://dadosabertos.bcb.gov.br",
        licenca="Dados abertos do Portal de Dados Abertos do BCB",
    ),
    Fonte(
        codigo="nasa_power",
        nome="NASA POWER (Langley Research Center)",
        url="https://power.larc.nasa.gov",
        licenca="Dados públicos da NASA, uso livre com citação da fonte",
    ),
]

# Preços ---------------------------------------------------------------------

SERIES_PRECO: list[Serie] = [
    Serie(
        codigo="cepea.soja",
        fonte="cepea",
        categoria="preco",
        produto="soja",
        variavel="preco_a_vista",
        local="Paranaguá/PR",
        unidade="BRL/sc60kg",
        calendario="dias_uteis",
        limite_min=0,
        descricao="Indicador da Soja CEPEA/ESALQ - Paranaguá, à vista",
    ),
    Serie(
        codigo="cepea.milho",
        fonte="cepea",
        categoria="preco",
        produto="milho",
        variavel="preco_a_vista",
        local="Campinas/SP",
        unidade="BRL/sc60kg",
        calendario="dias_uteis",
        limite_min=0,
        descricao="Indicador do Milho ESALQ/B3 - Campinas, à vista",
    ),
]

# Câmbio ---------------------------------------------------------------------

SERIES_CAMBIO: list[Serie] = [
    Serie(
        codigo=f"bcb.ptax_{lado}",
        fonte="bcb",
        categoria="cambio",
        variavel=f"ptax_{lado}",
        unidade="BRL/USD",
        calendario="dias_uteis",
        limite_min=0,
        defasagem_max=2,  # publicada por volta das 13h
        descricao=f"Dólar PTAX, cotação de {lado}",
    )
    for lado in ("venda", "compra")
]

# Clima ----------------------------------------------------------------------

# Pontos em regiões produtoras de soja/milho (não nas praças de preço).
PONTOS_CLIMA: dict[str, tuple[str, float, float]] = {
    "sorriso_mt": ("Sorriso/MT", -12.55, -55.71),
    "rio_verde_go": ("Rio Verde/GO", -17.80, -50.93),
    "cascavel_pr": ("Cascavel/PR", -24.96, -53.46),
}

# variável do agrobr -> (unidade, limite físico (mín, máx), faixa típica da mediana anual
# (mín, máx) ou None, descrição). O limite físico rejeita o dado na entrada; a faixa típica só
# gera alerta de qualidade.
VARIAVEIS_CLIMA: dict[str, tuple[str, tuple[float, float], tuple[float, float] | None, str]] = {
    "temp_media": ("°C", (-10, 50), (10, 35), "Temperatura média a 2 m (T2M)"),
    "temp_max": ("°C", (-10, 50), (15, 42), "Temperatura máxima a 2 m (T2M_MAX)"),
    "temp_min": ("°C", (-15, 45), (0, 30), "Temperatura mínima a 2 m (T2M_MIN)"),
    "precip_mm": ("mm/dia", (0, 500), None, "Precipitação corrigida (PRECTOTCORR)"),
    "umidade_rel": ("%", (0, 100), (30, 95), "Umidade relativa a 2 m (RH2M)"),
    "radiacao_mj": ("MJ/m²/dia", (0, 45), (8, 30), "Radiação solar na superfície (ALLSKY_SFC_SW_DWN)"),
    "vento_ms": ("m/s", (0, 40), (0.5, 10), "Velocidade do vento a 2 m (WS2M)"),
}

SERIES_CLIMA: list[Serie] = [
    Serie(
        codigo=f"nasa.{ponto}.{variavel}",
        fonte="nasa_power",
        categoria="clima",
        variavel=variavel,
        local=local,
        lat=lat,
        lon=lon,
        unidade=unidade,
        calendario="dias_corridos",
        limite_min=limite[0],
        limite_max=limite[1],
        descricao=descricao,
        defasagem_max=7,  # a NASA publica com 2 a 5 dias de atraso
        tipico_min=tipico[0] if tipico else None,
        tipico_max=tipico[1] if tipico else None,
    )
    for ponto, (local, lat, lon) in PONTOS_CLIMA.items()
    for variavel, (unidade, limite, tipico, descricao) in VARIAVEIS_CLIMA.items()
]

SERIES: list[Serie] = SERIES_PRECO + SERIES_CAMBIO + SERIES_CLIMA


def coluna_dataset(codigo_serie: str) -> str:
    """Nome da coluna da série em vw_dataset_diario (ex.: 'cepea.soja' -> 'cepea_soja')."""
    return codigo_serie.replace(".", "_")
