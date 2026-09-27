import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dados
import estilo
from agro_pipeline.catalogo import SERIES
from agro_pipeline.quality.checks import (
    REPETIDOS_LIMITE,
    Checagem,
    calcular_saltos,
    dias_esperados,
    resumir,
    sequencias_repetidas,
)

st.title("Qualidade dos dados")
st.caption(
    "Checagens rodam ao fim de cada execução e não alteram dados: só sinalizam. "
    "A validação de entrada (que rejeita linhas) aparece na página Operação."
)

chq = dados.checagens_recentes()
if chq.empty:
    st.info("Nenhuma checagem registrada ainda. Rode `python -m agro_pipeline qualidade`.")
    st.stop()

origem = f"execução #{int(chq['execucao_id'].iloc[0])}" if pd.notna(chq["execucao_id"].iloc[0]) else "comando qualidade"
st.caption(f"Último lote: {chq['criada_em'].iloc[0]:%d/%m/%Y %H:%M} (Brasília), {origem}")

reprovadas = chq[~chq["aprovada"]]
c1, c2, c3 = st.columns(3)
c1.metric(f"{estilo.ICONE['ok']} Aprovadas", int(chq["aprovada"].sum()), help=f"de {len(chq)} checagens")
c2.metric(f"{estilo.ICONE['aviso']} Avisos", int((reprovadas["severidade"] == "aviso").sum()))
c3.metric(f"{estilo.ICONE['erro']} Erros", int((reprovadas["severidade"] == "erro").sum()),
          help="Erro = fonte sem dado novo além do tolerado; faz a execução no GitHub falhar e mandar e-mail.")

# Tabela de checagens ---------------------------------------------------------
st.subheader("Checagens")
filtro = st.segmented_control(
    "Mostrar", ["Só reprovadas", "Todas"], default="Só reprovadas", label_visibility="collapsed"
)
tabela = chq if filtro == "Todas" else pd.concat([reprovadas, chq[chq["serie"].isna()]])
tabela = tabela.assign(
    status=[estilo.rotulo_status(a, s) for a, s in zip(tabela["aprovada"], tabela["severidade"])],
    serie=tabela["serie"].fillna("(execução)"),
    resumo=[resumir(Checagem(r, s, a, None, d)) for r, s, a, d in
            zip(tabela["regra"], tabela["severidade"], tabela["aprovada"], tabela["detalhe"])],
)
st.dataframe(tabela[["status", "serie", "regra", "resumo"]], hide_index=True, width="stretch",
             column_config={"serie": "série"})

# Completude por série --------------------------------------------------------
st.subheader("Completude por série")
st.caption("Dias com valor ÷ dias esperados pelo calendário da série (B3 para preço e câmbio; dias corridos para clima).")
comp = chq[chq["regra"] == "completude"].copy()
comp = pd.DataFrame([
    {
        "série": s,
        "completude": d.get("completude"),
        "esperados": d.get("esperados"),
        "faltantes": d.get("faltantes"),
        "maior lacuna": (f"{d['maior_lacuna']['dias']} dia(s) a partir de {d['maior_lacuna']['inicio']}"
                         if d.get("maior_lacuna") else "—"),
        "últimos faltantes": ", ".join(d.get("ultimos_faltantes", [])),
    }
    for s, d in zip(comp["serie"], comp["detalhe"])
])
st.dataframe(comp, hide_index=True, width="stretch", column_config={
    "completude": st.column_config.ProgressColumn("completude", format="percent", min_value=0.95, max_value=1.0),
})

# Inspetor de série -----------------------------------------------------------
st.subheader("Inspecionar uma série")
codigos = [s.codigo for s in SERIES]
codigo = st.selectbox("Série", codigos, index=codigos.index("cepea.soja"))
meta = next(s for s in SERIES if s.codigo == codigo)
df = dados.serie(codigo)
if df.empty:
    st.warning("Série sem dados.")
    st.stop()

base = df.assign(data=df["data"].dt.date)
fig = go.Figure()
entidade = meta.produto or ("dolar" if meta.categoria == "cambio" else codigo.split(".")[1])
estilo.linha(fig, df["data"], df["valor"], entidade, name=meta.descricao or codigo,
             hovertemplate="%{y:.2f} " + meta.unidade + "<extra></extra>")

achados = []
if meta.categoria in ("preco", "cambio"):
    seqs = sequencias_repetidas(base, minimo=REPETIDOS_LIMITE)
    for s in seqs.itertuples():
        fig.add_vrect(x0=s.inicio, x1=s.fim, fillcolor=estilo.STATUS["aviso"], opacity=0.25, line_width=0, layer="below")
        achados.append({"tipo": "valor repetido", "início": s.inicio, "fim": s.fim, "dias": s.n, "valor": s.valor})
    if len(seqs):
        # item de legenda para a faixa sombreada
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=f"valor repetido ≥ {REPETIDOS_LIMITE} dias",
                                 marker=dict(symbol="square", size=12, color=estilo.STATUS["aviso"], opacity=0.5)))
    saltos = calcular_saltos(base)
    if len(saltos):
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(saltos["data"]), y=saltos["valor"], mode="markers", name="salto (z > 6)",
            marker=dict(size=9, color=estilo.STATUS["serio"], line=dict(width=2, color=estilo.tinta("superficie"))),
            customdata=(100 * np.expm1(saltos["retorno"])).round(2),
            hovertemplate="salto de %{customdata}%<extra></extra>",
        ))
        achados += [{"tipo": "salto", "início": d, "fim": d, "dias": 1, "valor": v} for d, v in saltos[["data", "valor"]].itertuples(index=False)]

esperados = dias_esperados(meta, base["data"].iloc[0], base["data"].iloc[-1])
faltantes = esperados.difference(pd.DatetimeIndex(df["data"]))
if len(faltantes):
    fig.add_trace(go.Scatter(
        x=faltantes, y=[df["valor"].min()] * len(faltantes), mode="markers", name="dia faltante",
        marker=dict(symbol="line-ns-open", size=10, color=estilo.STATUS["erro"], line=dict(width=2)),
        hovertemplate="%{x|%d/%m/%Y}: sem valor<extra></extra>",
    ))
    achados += [{"tipo": "dia faltante", "início": d.date(), "fim": d.date(), "dias": 1, "valor": None} for d in faltantes]

estilo.mostrar(estilo.layout(fig, meta.unidade, altura=420))
st.caption(
    f"{len(df):,}".replace(",", ".")
    + f" observações de {df['data'].iloc[0]:%d/%m/%Y} a {df['data'].iloc[-1]:%d/%m/%Y}. "
    "Faixas amarelas: mesmo valor por vários dias seguidos (possível dado congelado na fonte). "
    "Pontos laranja: variação diária anômala. Traços vermelhos na base: dias esperados sem valor."
)
with st.expander(f"Ver achados em tabela ({len(achados)})"):
    st.dataframe(pd.DataFrame(achados), hide_index=True, width="stretch")
