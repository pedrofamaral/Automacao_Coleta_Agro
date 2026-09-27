"""Paleta e layout dos gráficos (paleta de referência da skill de dataviz, validada).

Cada entidade tem cor fixa em todo o painel: soja sempre azul, milho sempre laranja etc.
Clima usa um conjunto próprio (pontos), validado à parte (todos os pares, claro e escuro).
"""

import plotly.graph_objects as go
import streamlit as st

_CATEGORICA = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
# slot da paleta categórica por entidade
_SLOT = {
    "soja": 0, "milho": 1, "dolar": 2, "soja_usd": 3,
    "sorriso_mt": 4, "rio_verde_go": 5, "cascavel_pr": 6,
}
_TINTA = {
    "light": {"primaria": "#0b0b0b", "secundaria": "#52514e", "muted": "#898781",
              "grade": "#e1e0d9", "base": "#c3c2b7", "superficie": "#fcfcfb", "meio": "#f0efec"},
    "dark": {"primaria": "#ffffff", "secundaria": "#c3c2b7", "muted": "#898781",
             "grade": "#2c2c2a", "base": "#383835", "superficie": "#1a1a19", "meio": "#383835"},
}
STATUS = {"ok": "#0ca30c", "aviso": "#fab219", "serio": "#ec835a", "erro": "#d03b3b"}
ICONE = {"ok": "✅", "aviso": "⚠️", "erro": "⛔", "info": "ℹ️"}

NOME = {
    "soja": "Soja (Paranaguá)", "milho": "Milho (Campinas)", "dolar": "Dólar PTAX",
    "soja_usd": "Soja em US$", "sorriso_mt": "Sorriso/MT", "rio_verde_go": "Rio Verde/GO",
    "cascavel_pr": "Cascavel/PR",
}


def modo() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


def cor(entidade: str) -> str:
    return _CATEGORICA[modo()][_SLOT[entidade]]


def tinta(papel: str) -> str:
    return _TINTA[modo()][papel]


def escala_divergente() -> list[list]:
    """Correlação: vermelho (negativa) <-> cinza neutro (zero) <-> azul (positiva)."""
    m = modo()
    return [[0, _CATEGORICA[m][7]], [0.5, _TINTA[m]["meio"]], [1, _CATEGORICA[m][0]]]


def rotulo_status(aprovada: bool, severidade: str) -> str:
    if aprovada:
        return f"{ICONE['ok']} ok"
    return f"{ICONE.get(severidade, '')} {severidade}"


def layout(fig: go.Figure, titulo_y: str = "", altura: int = 380, hover: str = "x unified") -> go.Figure:
    eixo = dict(
        gridcolor=tinta("grade"), linecolor=tinta("base"), zerolinecolor=tinta("base"),
        tickfont=dict(color=tinta("muted")), title_font=dict(color=tinta("secundaria")),
        showline=True,
    )
    fig.update_layout(
        height=altura,
        margin=dict(l=8, r=8, t=36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=tinta("primaria"), size=13),
        hovermode=hover,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font=dict(color=tinta("secundaria"))),
        xaxis=eixo,
        yaxis={**eixo, "title": titulo_y},
    )
    return fig


def linha(fig: go.Figure, x, y, entidade: str, **kwargs) -> None:
    fig.add_trace(go.Scatter(
        x=x, y=y, name=kwargs.pop("name", NOME.get(entidade, entidade)), mode="lines",
        line=dict(color=cor(entidade), width=2), **kwargs,
    ))


def mostrar(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, config={"displaylogo": False})
