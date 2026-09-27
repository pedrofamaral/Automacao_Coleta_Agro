import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dados
import estilo
from agro_pipeline.catalogo import PONTOS_CLIMA

st.title("Operação do pipeline")
st.caption("Cada rodada do pipeline (local ou GitHub Actions) é uma execução; cada chamada a uma fonte é uma coleta.")

execs = dados.execucoes()
if execs.empty:
    st.info("Nenhuma execução registrada ainda.")
    st.stop()

ultima = execs.iloc[0]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Execuções", len(execs))
c2.metric("Taxa de sucesso", f"{(execs['status'] == 'sucesso').mean():.0%}")
c3.metric(
    "Última execução",
    f"{estilo.ICONE['ok'] if ultima['status'] == 'sucesso' else estilo.ICONE['erro']} {ultima['status']}",
    help=f"#{ultima['id']} em {ultima['inicio']:%d/%m/%Y %H:%M} ({ultima['ambiente']})",
)
c4.metric("Observações no banco", f"{dados.total_observacoes():,}".replace(",", "."))
st.caption(f"Última: #{ultima['id']}, {ultima['inicio']:%d/%m/%Y %H:%M} (Brasília), {ultima['modo']}, {ultima['ambiente']}")

# Execuções por dia e status --------------------------------------------------
st.subheader("Execuções por dia")
por_dia = (
    execs.assign(dia=execs["inicio"].dt.date)
    .pivot_table(index="dia", columns="status", values="id", aggfunc="count", fill_value=0)
)
fig = go.Figure()
cores_status = {"sucesso": estilo.STATUS["ok"], "parcial": estilo.STATUS["aviso"], "falha": estilo.STATUS["erro"]}
for status, cor in cores_status.items():
    if status in por_dia:
        fig.add_trace(go.Bar(x=por_dia.index, y=por_dia[status], name=f"{status}", marker_color=cor,
                             marker_line_width=0, hovertemplate="%{y} execução(ões)<extra>" + status + "</extra>"))
fig.update_layout(barmode="stack", bargap=0.35)
estilo.mostrar(estilo.layout(fig, "execuções", altura=260))

# Tabela de execuções ---------------------------------------------------------
st.subheader("Execuções")
tabela = execs.assign(
    status=[f"{estilo.ICONE['ok'] if s == 'sucesso' else estilo.ICONE['aviso'] if s == 'parcial' else estilo.ICONE['erro']} {s}"
            for s in execs["status"]],
)
st.dataframe(
    tabela,
    hide_index=True,
    width="stretch",
    column_config={
        "id": "#",
        "inicio": st.column_config.DatetimeColumn("início (Brasília)", format="DD/MM/YYYY HH:mm"),
        "versao_codigo": "versão",
        "duracao_s": st.column_config.NumberColumn("duração", format="%.1f s"),
        "coletas_ok": "coletas ok",
        "coletas_falha": "coletas com falha",
    },
)

# Detalhe de uma execução -----------------------------------------------------
st.subheader("Coletas de uma execução")
escolhida = st.selectbox(
    "Execução", execs["id"], format_func=lambda i: f"#{i} · {execs.set_index('id').loc[i, 'inicio']:%d/%m %H:%M} · "
    f"{execs.set_index('id').loc[i, 'modo']} · {execs.set_index('id').loc[i, 'ambiente']}",
)
col = dados.coletas(int(escolhida))

pontos = {(lat, lon): nome for nome, (_, lat, lon) in PONTOS_CLIMA.items()}


def alvo(fonte: str, p: dict) -> str:
    if fonte == "cepea":
        return p.get("produto", "")
    if fonte == "nasa_power":
        return estilo.NOME.get(pontos.get((p.get("lat"), p.get("lon")), ""), "")
    return "PTAX"


def origem(p: dict) -> str:
    prov = p.get("proveniencia")
    if prov:
        return "cache do agrobr" if prov.get("from_cache") else prov.get("selected_source", "")
    if "fallback_de_agrobr" in p:
        return "planilha (fallback)"
    return ""


col = col.assign(
    alvo=[alvo(f, p) for f, p in zip(col["fonte"], col["parametros"])],
    janela=[f"{p.get('inicio', '')} → {p.get('fim', '')}" for p in col["parametros"]],
    origem=[origem(p) for p in col["parametros"]],
    status=[f"{estilo.ICONE['ok']} ok" if s == "sucesso" else f"{estilo.ICONE['erro']} falha" for s in col["status"]],
    rejeicoes=[", ".join(f"{k}: {v}" for k, v in (r or {}).items()) for r in col["rejeicoes"]],
)
st.dataframe(
    col[["fonte", "alvo", "metodo", "origem", "status", "janela", "tentativas", "duracao_ms",
         "linhas_recebidas", "linhas_rejeitadas", "rejeicoes", "linhas_inseridas", "linhas_revisadas", "erro"]],
    hide_index=True,
    width="stretch",
    column_config={
        "metodo": "método",
        "duracao_ms": st.column_config.NumberColumn("tempo", format="%d ms"),
        "linhas_recebidas": "recebidas", "linhas_rejeitadas": "rejeitadas",
        "linhas_inseridas": "inseridas", "linhas_revisadas": "revisadas",
        "rejeicoes": "motivos de rejeição",
    },
)
