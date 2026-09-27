import argparse
import logging
import os
import sys
from datetime import date

import structlog

from agro_pipeline import config


def _silenciar_agrobr() -> None:
    # o agrobr loga via structlog sem configurar nível: sem isto, sai debug com traceback
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))


def _init_db(_: argparse.Namespace) -> None:
    from agro_pipeline.db.inicializar import inicializar

    resumo = inicializar()
    print(f"schema aplicado: {resumo['fontes']} fontes, {resumo['series_ativas']} séries ativas")


def _coletar(args: argparse.Namespace) -> None:
    from agro_pipeline.pipeline import executar

    modo = "backfill" if args.comando == "backfill" else "incremental"
    resultado = executar(modo=modo, desde=args.desde, fontes=args.fonte)

    print(f"\nexecução #{resultado.execucao_id} ({modo}): {resultado.status.upper()}\n")
    print(f"{'tarefa':<20} {'status':<8} {'método':<30} {'janela':<23} "
          f"{'receb.':>7} {'rejeit.':>7} {'inser.':>7} {'revis.':>6} {'tempo':>7}")
    for r in resultado.tarefas:
        print(f"{r.tarefa:<20} {r.status:<8} {(r.metodo or '-'):<30} {r.inicio} → {r.fim} "
              f"{r.recebidas:>7} {r.rejeitadas:>7} {r.inseridas:>7} {r.revisadas:>6} "
              f"{r.duracao_ms / 1000:>6.1f}s")
        if r.rejeicoes:
            print(f"{'':<20} rejeições: {r.rejeicoes}")
        if r.erro:
            print(f"{'':<20} erro: {r.erro.strip().splitlines()[-1]}")

    print()
    if resultado.erro_qualidade:
        print(f"qualidade: falhou ao rodar as checagens\n{resultado.erro_qualidade}")
    else:
        print("\n".join(_linhas_qualidade(resultado.checagens)))

    _resumo_github(resultado, modo)
    if resultado.status != "sucesso" or resultado.erro_qualidade or _tem_erro(resultado.checagens):
        sys.exit(1)


def _qualidade(_: argparse.Namespace) -> None:
    from agro_pipeline.db.conexao import engine
    from agro_pipeline.quality.checks import executar_checagens

    with engine().begin() as conn:
        checagens = executar_checagens(conn, config.hoje())
    print("\n".join(_linhas_qualidade(checagens, todas=True)))
    if _tem_erro(checagens):
        sys.exit(1)


def _tem_erro(checagens) -> bool:
    return any(c.severidade == "erro" and not c.aprovada for c in checagens)


def _linhas_qualidade(checagens, todas: bool = False) -> list[str]:
    from agro_pipeline.quality.checks import resumir


    reprovadas = [c for c in checagens if not c.aprovada]
    linhas = [
        f"qualidade: {len(checagens)} checagens, {len(checagens) - len(reprovadas)} aprovadas, "
        f"{sum(c.severidade == 'aviso' for c in reprovadas)} avisos, "
        f"{sum(c.severidade == 'erro' for c in reprovadas)} erros"
    ]
    for c in checagens if todas else reprovadas + [c for c in checagens if c.serie is None]:
        marca = "ok " if c.aprovada else c.severidade.upper()
        linhas.append(f"  [{marca:<5}] {(c.serie or 'execução'):<30} {c.regra:<18} {resumir(c)}")
    return linhas


def _resumo_github(resultado, modo: str) -> None:
    """No GitHub Actions, escreve a tabela da execução na página do run."""
    caminho = os.environ.get("GITHUB_STEP_SUMMARY")
    if not caminho:
        return
    linhas = [
        f"### Execução #{resultado.execucao_id} ({modo}): {resultado.status.upper()}",
        "",
        "| tarefa | status | método | janela | recebidas | rejeitadas | inseridas | revisadas | tempo |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in resultado.tarefas:
        status = r.status if not r.erro else f"{r.status}: {r.erro.strip().splitlines()[-1]}"
        linhas.append(
            f"| {r.tarefa} | {status} | {r.metodo or '-'} | {r.inicio} → {r.fim} | {r.recebidas} "
            f"| {r.rejeitadas} | {r.inseridas} | {r.revisadas} | {r.duracao_ms / 1000:.1f}s |"
        )
    if resultado.erro_qualidade:
        linhas += ["", "**Qualidade:** falhou ao rodar as checagens"]
    else:
        linhas += ["", "```", *_linhas_qualidade(resultado.checagens), "```"]
    with open(caminho, "a", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


def main(argv: list[str] | None = None) -> None:
    _silenciar_agrobr()
    parser = argparse.ArgumentParser(prog="agro_pipeline")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("init-db", help="cria/atualiza o schema e o catálogo de séries").set_defaults(
        func=_init_db
    )

    for nome, ajuda in [
        ("run", "coleta incremental (desde o último dado gravado de cada série)"),
        ("backfill", "coleta o histórico completo a partir de --desde"),
    ]:
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("--desde", type=date.fromisoformat, default=config.DESDE_PADRAO,
                       help=f"data inicial AAAA-MM-DD (padrão {config.DESDE_PADRAO})")
        p.add_argument("--fonte", action="append", choices=["cepea", "bcb", "nasa_power"],
                       help="restringe a uma fonte (pode repetir)")
        p.set_defaults(func=_coletar)

    sub.add_parser("qualidade", help="roda as checagens de qualidade sobre o banco").set_defaults(
        func=_qualidade
    )

    args = parser.parse_args(argv)
    args.func(args)
