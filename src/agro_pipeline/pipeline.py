"""Orquestração: para cada tarefa, coleta -> valida -> persiste, isolando falhas."""

import time
import traceback
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Engine

from agro_pipeline import config
from agro_pipeline.collectors import TAREFAS
from agro_pipeline.collectors.base import FalhaBusca, Tarefa, com_retry
from agro_pipeline.db import repositorio
from agro_pipeline.db.conexao import engine as engine_padrao
from agro_pipeline.quality.checks import Checagem, executar_checagens
from agro_pipeline.validacao import validar


@dataclass
class ResultadoTarefa:
    tarefa: str
    status: str
    inicio: date
    fim: date
    metodo: str | None = None
    recebidas: int = 0
    rejeitadas: int = 0
    inseridas: int = 0
    revisadas: int = 0
    duracao_ms: int = 0
    rejeicoes: dict[str, int] = field(default_factory=dict)
    erro: str | None = None


@dataclass
class ResultadoExecucao:
    execucao_id: int
    status: str
    tarefas: list[ResultadoTarefa]
    checagens: list[Checagem] = field(default_factory=list)
    erro_qualidade: str | None = None


def janela(
    tarefa: Tarefa, ultimas: dict[str, date], modo: str, desde: date, hoje: date
) -> tuple[date, date]:
    """Período a buscar. Incremental: desde o dado mais antigo entre as 'últimas datas' das
    séries da tarefa, menos a sobreposição; série sem dados cai no histórico completo."""
    if modo == "backfill":
        return desde, hoje
    datas = [ultimas.get(s) for s in tarefa.series]
    if any(d is None for d in datas):
        return desde, hoje
    return min(datas) - timedelta(days=tarefa.sobreposicao_dias), hoje


def _executar_tarefa(
    eng: Engine, execucao_id: int, tarefa: Tarefa, inicio: date, fim: date, hoje: date,
    espera_retry: float,
) -> ResultadoTarefa:
    res = ResultadoTarefa(tarefa=tarefa.nome, status="falha", inicio=inicio, fim=fim)
    t0 = time.perf_counter()
    try:
        busca, tentativas = com_retry(lambda: tarefa.buscar(inicio, fim), espera_inicial=espera_retry)
    except FalhaBusca as e:
        res.duracao_ms = int((time.perf_counter() - t0) * 1000)
        res.erro = str(e)
        with eng.begin() as conn:
            repositorio.registrar_coleta(
                conn, execucao_id, tarefa.fonte, metodo=f"{tarefa.nome}.buscar", status="falha",
                tentativas=e.tentativas, duracao_ms=res.duracao_ms, erro="\n".join(e.historico),
                parametros={"inicio": inicio.isoformat(), "fim": fim.isoformat()},
            )
        return res

    busca.tentativas = tentativas
    busca.duracao_ms = res.duracao_ms = int((time.perf_counter() - t0) * 1000)
    res.metodo = busca.metodo
    res.recebidas = len(busca.registros)
    campos = dict(
        metodo=busca.metodo, parametros=busca.parametros, tentativas=tentativas,
        duracao_ms=busca.duracao_ms, linhas_recebidas=res.recebidas,
        payload=busca.registros, hash_payload=busca.hash,
    )
    try:
        df = tarefa.transformar(busca.registros)
        validas, rejeicoes = validar(df, hoje)
        res.rejeicoes, res.rejeitadas = rejeicoes, sum(rejeicoes.values())
        with eng.begin() as conn:
            coleta_id = repositorio.registrar_coleta(
                conn, execucao_id, tarefa.fonte, **campos,
                linhas_rejeitadas=res.rejeitadas, rejeicoes=rejeicoes,
            )
            res.inseridas, res.revisadas = repositorio.gravar_observacoes(conn, coleta_id, validas)
            repositorio.atualizar_contagens(conn, coleta_id, res.inseridas, res.revisadas)
        res.status = "sucesso"
    except Exception:
        # falha depois da busca: guarda o payload bruto para diagnóstico/reprocessamento
        res.erro = traceback.format_exc(limit=3)
        with eng.begin() as conn:
            repositorio.registrar_coleta(
                conn, execucao_id, tarefa.fonte, **campos, status="falha", erro=res.erro
            )
    return res


def executar(
    modo: str = "incremental",
    desde: date = config.DESDE_PADRAO,
    fontes: list[str] | None = None,
    tarefas: list[Tarefa] | None = None,
    eng: Engine | None = None,
    hoje: date | None = None,
    espera_retry: float = 2.0,
) -> ResultadoExecucao:
    eng = eng or engine_padrao()
    hoje = hoje or config.hoje()
    tarefas = [t for t in (tarefas or TAREFAS) if not fontes or t.fonte in fontes]

    with eng.begin() as conn:
        execucao_id = repositorio.abrir_execucao(
            conn, modo, config.ambiente(), config.versao_codigo(),
            {"desde": desde.isoformat(), "fontes": fontes, "hoje": hoje.isoformat()},
        )
        ultimas = repositorio.ultima_data_por_serie(conn)

    resultados = []
    for tarefa in tarefas:
        inicio, fim = janela(tarefa, ultimas, modo, desde, hoje)
        resultados.append(_executar_tarefa(eng, execucao_id, tarefa, inicio, fim, hoje, espera_retry))

    falhas = sum(r.status == "falha" for r in resultados)
    status = "sucesso" if falhas == 0 else ("falha" if falhas == len(resultados) else "parcial")
    with eng.begin() as conn:
        erro = "; ".join(f"{r.tarefa}: {r.erro.splitlines()[-1]}" for r in resultados if r.erro) or None
        repositorio.fechar_execucao(conn, execucao_id, status, erro)
    resultado = ResultadoExecucao(execucao_id, status, resultados)

    # a qualidade não pode derrubar a coleta que já foi gravada
    try:
        with eng.begin() as conn:
            resultado.checagens = executar_checagens(conn, hoje, execucao_id)
    except Exception:
        resultado.erro_qualidade = traceback.format_exc(limit=3)
    return resultado
