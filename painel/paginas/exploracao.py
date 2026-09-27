from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dados
import estilo

st.title("Exploração")
st.caption("Análise exploratória do dataset (vw_dataset_diario) — base para escolher as features do modelo.")

ds = dados.dataset()
PRECOS = {"soja": "cepea_soja", "milho": "cepea_milho", "dolar": "bcb_ptax_venda"}
PONTOS = ["sorriso_mt", "rio_verde_go", "cascavel_pr"]

# Filtro de período (uma linha, vale para a página toda) ----------------------
inicio_min, fim_max = ds.index.min().date(), ds.index.max().date()
f1, f2 = st.columns([3, 1])
periodo = f1.slider(
    "Período", min_value=inicio_min, max_value=fim_max,
    value=(max(inicio_min, date(fim_max.year - 10, 1, 1)), fim_max), format="MM/YYYY",
)
f2.download_button(
    "Baixar dataset do período (CSV)",
    ds.loc[str(periodo[0]):str(periodo[1])].to_csv().encode("utf-8"),
    file_name=f"dataset_{periodo[0]}_{periodo[1]}.csv", mime="text/csv", width="stretch",
)
d = ds.loc[str(periodo[0]):str(periodo[1])]

if d.index.min() <= pd.Timestamp("2015-01-26") and d.index.max() >= pd.Timestamp("2014-09-29"):
    st.info("O período inclui o trecho em que a soja em R$ ficou congelada na fonte (29/09/2014 → 26/01/2015). "
            "Veja a página Qualidade.", icon="⚠️")

# Números do momento ----------------------------------------------------------
cols = st.columns(3)
for col, (ent, coluna) in zip(cols, PRECOS.items()):
    s = d[coluna].dropna()
    if s.empty:
        continue
    ha_um_ano = s[: s.index[-1] - pd.DateOffset(years=1)]
    delta = f"{s.iloc[-1] / ha_um_ano.iloc[-1] - 1:+.1%} em 12 meses" if len(ha_um_ano) else None
    unidade = "R$/US$" if ent == "dolar" else "R$/sc 60 kg"
    col.metric(f"{estilo.NOME[ent]} · {s.index[-1]:%d/%m/%Y}",
               f"{s.iloc[-1]:,.2f} {unidade}".replace(",", "X").replace(".", ",").replace("X", "."),
               delta, delta_color="off")

# Preços em R$ ----------------------------------------------------------------
st.subheader("Preços à vista (R$/saca de 60 kg)")
fig = go.Figure()
for ent in ("soja", "milho"):
    s = d[PRECOS[ent]].dropna()
    estilo.linha(fig, s.index, s, ent, hovertemplate="R$ %{y:.2f}<extra>" + estilo.NOME[ent] + "</extra>")
estilo.mostrar(estilo.layout(fig, "R$/sc 60 kg"))

# Índice base 100 -------------------------------------------------------------
st.subheader("Evolução comparada (índice, início do período = 100)")
st.caption("Séries em escalas diferentes num único eixo: cada uma é dividida pelo próprio valor inicial.")
com_usd = st.toggle("Incluir soja em US$ (R$ ÷ PTAX) — separa o efeito do câmbio", value=True)
indices = {ent: d[c].dropna() for ent, c in PRECOS.items()}
if com_usd:
    indices["soja_usd"] = (d["cepea_soja"] / d["bcb_ptax_venda"]).dropna()
fig = go.Figure()
variacoes = {}
for ent, s in indices.items():
    if s.empty:
        continue
    idx = 100 * s / s.iloc[0]
    variacoes[ent] = idx.iloc[-1] - 100
    estilo.linha(fig, idx.index, idx, ent, hovertemplate="%{y:.0f}<extra>" + estilo.NOME[ent] + "</extra>")
fig.add_hline(y=100, line_width=1, line_color=estilo.tinta("base"))
estilo.mostrar(estilo.layout(fig, "índice"))
st.caption("No período: " + " · ".join(f"{estilo.NOME[e]} {v:+.0f}%" for e, v in variacoes.items()))

# Sazonalidade ----------------------------------------------------------------
st.subheader("Sazonalidade: preço relativo à média do ano")
st.caption("Para cada ano completo do período, preço do mês ÷ média do ano − 1; depois a média entre os anos.")
mensal = d[[PRECOS["soja"], PRECOS["milho"]]].resample("MS").mean()
anos_completos = mensal.groupby(mensal.index.year).filter(lambda g: g.notna().sum().min() == 12)
relativo = anos_completos / anos_completos.groupby(anos_completos.index.year).transform("mean") - 1
sazonal = 100 * relativo.groupby(relativo.index.month).mean()
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
if sazonal.empty:
    st.info("Selecione um período com pelo menos um ano completo.")
else:
    fig = go.Figure()
    for ent in ("soja", "milho"):
        estilo.linha(fig, [MESES[m - 1] for m in sazonal.index], sazonal[PRECOS[ent]], ent,
                     hovertemplate="%{y:+.1f}%<extra>" + estilo.NOME[ent] + "</extra>")
        fig.data[-1].update(mode="lines+markers", marker=dict(size=8))
    fig.add_hline(y=0, line_width=1, line_color=estilo.tinta("base"))
    estilo.mostrar(estilo.layout(fig, "% vs média do ano", altura=320))
    n_anos = anos_completos.index.year.nunique()
    st.caption(" · ".join(
        f"{estilo.NOME[e]}: mais barato em {MESES[sazonal[PRECOS[e]].idxmin() - 1]}, "
        f"mais caro em {MESES[sazonal[PRECOS[e]].idxmax() - 1]}" for e in ("soja", "milho")
    ) + f" (média de {n_anos} anos)")

# Correlação preço x clima ----------------------------------------------------
st.subheader("Correlação mensal: preços, câmbio e chuva")
st.caption(
    "Variação % mensal dos preços e do dólar contra a anomalia de chuva (chuva do mês − média histórica "
    "daquele mês no ponto). Tirar a média do mês remove a sazonalidade, que senão dominaria a correlação."
)
m = pd.DataFrame({estilo.NOME[e]: d[c].resample("MS").mean().pct_change() for e, c in PRECOS.items()})
for p in PONTOS:
    chuva = d[f"nasa_{p}_precip_mm"].resample("MS").sum(min_count=20)
    m[f"Chuva {estilo.NOME[p]}"] = chuva - chuva.groupby(chuva.index.month).transform("mean")
corr = m.corr()
fig = go.Figure(go.Heatmap(
    z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1, colorscale=estilo.escala_divergente(),
    text=corr.round(2).values, texttemplate="%{text}", textfont=dict(size=12),
    hovertemplate="%{y} × %{x}: r = %{z:.2f}<extra></extra>", colorbar=dict(title="r", thickness=12),
    xgap=2, ygap=2,
))
fig.update_yaxes(autorange="reversed")
estilo.mostrar(estilo.layout(fig, altura=420, hover="closest"))
pares = corr.where(~pd.DataFrame(
    [[i >= j for j in range(len(corr))] for i in range(len(corr))], index=corr.index, columns=corr.columns
)).stack()
forte = pares.abs().sort_values(ascending=False).head(2)
st.caption(f"{len(m.dropna())} meses. Maiores correlações: " + " · ".join(
    f"{a} × {b}: r = {pares[(a, b)]:+.2f}" for a, b in forte.index
))
with st.expander("Ver matriz em tabela"):
    st.dataframe(corr.round(3), width="stretch")

# Chuva por ponto -------------------------------------------------------------
st.subheader("Chuva mensal acumulada por região produtora (mm)")
fig = go.Figure()
for p in PONTOS:
    s = d[f"nasa_{p}_precip_mm"].resample("MS").sum(min_count=20).dropna()
    estilo.linha(fig, s.index, s, p, hovertemplate="%{y:.0f} mm<extra>" + estilo.NOME[p] + "</extra>")
estilo.mostrar(estilo.layout(fig, "mm/mês", altura=320))
with st.expander("Ver chuva mensal em tabela"):
    st.dataframe(
        pd.DataFrame({estilo.NOME[p]: d[f"nasa_{p}_precip_mm"].resample("MS").sum(min_count=20) for p in PONTOS}).round(1),
        width="stretch",
    )
