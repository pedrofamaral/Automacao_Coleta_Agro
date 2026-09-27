"""Painel interno do pipeline: operação, qualidade e exploração dos dados.

Rodar: streamlit run painel/app.py
Ferramenta de inspeção/análise exploratória (não é o dashboard de produto, fora do escopo).
"""

import streamlit as st

st.set_page_config(page_title="Pipeline Agro", page_icon="🌾", layout="wide")

paginas = st.navigation([
    st.Page("paginas/operacao.py", title="Operação", icon="⚙️", default=True),
    st.Page("paginas/qualidade.py", title="Qualidade", icon="🔎"),
    st.Page("paginas/exploracao.py", title="Exploração", icon="📈"),
])

with st.sidebar:
    st.caption("Dados: CEPEA/ESALQ (CC BY-NC 4.0), BCB PTAX, NASA POWER.")
    if st.button("Recarregar dados", width="stretch"):
        st.cache_data.clear()

paginas.run()
