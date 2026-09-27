"""CEPEA/ESALQ — indicadores diários de preço (coletor híbrido).

- Janelas curtas (coleta diária): `agrobr.cepea.indicador`, que lê a página do indicador.
  Essa página só exibe ~15 dias úteis.
- Janelas longas (backfill) ou falha do agrobr: planilha oficial com a série completa,
  baixada de /br/indicador/series/<produto>.aspx?id=<id>.
"""

import hashlib
import io
from datetime import date, timedelta
from importlib.metadata import version
from typing import Any

import httpx
import pandas as pd

from agro_pipeline.collectors.base import Busca, Tarefa, iso, numero, quadro_canonico

URL_PLANILHA = "https://www.cepea.esalq.usp.br/br/indicador/series/{produto}.aspx?id={id}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)
# ~15 dias úteis exibidos na página do indicador, com margem
JANELA_AGROBR = timedelta(days=18)


class TarefaCepea(Tarefa):
    fonte = "cepea"

    def __init__(self, produto: str, id_planilha: int, titulo_esperado: str):
        self.produto = produto
        self.id_planilha = id_planilha
        self.titulo_esperado = titulo_esperado
        self.serie = f"cepea.{produto}"
        self.nome = self.serie
        self.series = (self.serie,)

    def buscar(self, inicio: date, fim: date) -> Busca:
        if fim - inicio > JANELA_AGROBR:
            return self._buscar_planilha(inicio, fim)
        try:
            return self._buscar_agrobr(inicio, fim)
        except Exception as e:
            busca = self._buscar_planilha(inicio, fim)
            busca.parametros["fallback_de_agrobr"] = f"{type(e).__name__}: {e}"
            return busca

    def _buscar_agrobr(self, inicio: date, fim: date) -> Busca:
        from agrobr.sync import cepea

        df = cepea.indicador(self.produto, inicio=inicio.isoformat(), fim=fim.isoformat())
        if df.empty:
            raise ValueError("agrobr retornou 0 linhas para uma janela de dias úteis")
        registros = [
            {
                "data": iso(r.data),
                "valor": numero(r.valor),
                "praca": r.praca,
                "unidade": r.unidade,
                "fonte": r.fonte,
                "metodologia": r.metodologia,
            }
            for r in df.itertuples()
        ]
        return Busca(
            metodo="agrobr.cepea.indicador",
            parametros={
                "produto": self.produto,
                "inicio": inicio.isoformat(),
                "fim": fim.isoformat(),
                "agrobr": version("agrobr"),
            },
            registros=registros,
        )

    def _buscar_planilha(self, inicio: date, fim: date) -> Busca:
        url = URL_PLANILHA.format(produto=self.produto, id=self.id_planilha)
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        titulo, dados = ler_planilha(resp.content)
        if self.titulo_esperado not in titulo.upper():
            raise ValueError(f"planilha inesperada (id mudou?): título {titulo!r}")

        dados = dados[(dados["data"] >= inicio) & (dados["data"] <= fim)]
        registros = [
            {"data": d.isoformat(), "valor": numero(brl), "valor_usd": numero(usd)}
            for d, brl, usd in dados.itertuples(index=False)
        ]
        return Busca(
            metodo="cepea.planilha",
            parametros={
                "url": url,
                "titulo": titulo,
                "sha256_arquivo": hashlib.sha256(resp.content).hexdigest(),
                "inicio": inicio.isoformat(),
                "fim": fim.isoformat(),
            },
            registros=registros,
        )

    def transformar(self, registros: list[dict[str, Any]]) -> pd.DataFrame:
        linhas = [(self.serie, r["data"], r["valor"]) for r in registros]
        extras = {}
        # o agrobr informa praça e unidade: a validação confere com o catálogo
        if registros and "unidade" in registros[0]:
            extras = {
                "unidade": [r["unidade"] for r in registros],
                "local": [r["praca"] for r in registros],
            }
        return quadro_canonico(linhas, extras)


def ler_planilha(conteudo: bytes) -> tuple[str, pd.DataFrame]:
    """Lê o .xls do CEPEA: título na 1ª célula, cabeçalho 'Data | À vista R$ | À vista US$'.

    O arquivo vem com o cabeçalho OLE corrompido; o xlrd lê com ignore_workbook_corruption.
    """
    bruto = pd.read_excel(
        io.BytesIO(conteudo),
        header=None,
        engine="xlrd",
        engine_kwargs={"ignore_workbook_corruption": True},
    )
    titulo = str(bruto.iat[0, 0])
    linha_cabecalho = bruto.index[bruto[0].astype(str).str.strip() == "Data"][0]
    dados = bruto.iloc[linha_cabecalho + 1 :, :3].copy()
    dados.columns = ["data", "valor_brl", "valor_usd"]
    dados["data"] = pd.to_datetime(dados["data"], format="%d/%m/%Y").dt.date
    dados["valor_brl"] = pd.to_numeric(dados["valor_brl"], errors="coerce")
    dados["valor_usd"] = pd.to_numeric(dados["valor_usd"], errors="coerce")
    return titulo, dados.reset_index(drop=True)


TAREFAS = [
    TarefaCepea("soja", id_planilha=92, titulo_esperado="SOJA"),
    TarefaCepea("milho", id_planilha=77, titulo_esperado="MILHO"),
]
