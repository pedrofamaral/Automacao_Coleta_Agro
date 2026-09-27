# TCC — Pipeline de dados públicos do agronegócio

Contexto do projeto (escopo, fontes, arquitetura): @claude/projeto.md
Plano aprovado (schema, fluxo, cronograma até 20/10/2026): @claude/plano.md
Decisões técnicas, resultados e questões em aberto: @claude/decisoes.md

## Como trabalhar neste projeto

- Responder em português (pt-BR).
- Respeitar o escopo: não propor previsão otimizada, frete/logística, motor de decisão ou
  dashboard de produto sem pedido explícito — foram cortados pelo orientador. (O painel
  Streamlit existe como ferramenta interna de inspeção/EDA, ver decisoes.md.)
- Toda decisão técnica relevante (tecnologia, schema, trade-off) deve ser registrada em
  `claude/decisoes.md` com data e justificativa — é insumo para o relatório final.
- Ambiente de desenvolvimento: Windows 11, sem Docker (virtualização desligada na BIOS).
  Banco é o Supabase (conexão em `.env`, nunca commitar). Repositório:
  https://github.com/pedrofamaral/Automacao_Coleta_Agro

## Comandos (a partir da raiz, com `.venv`)

```
.venv/Scripts/python -m pytest                      # testes unitários
.venv/Scripts/python -m agro_pipeline init-db       # schema + catálogo (idempotente)
.venv/Scripts/python -m agro_pipeline run           # coleta incremental + qualidade
.venv/Scripts/python -m agro_pipeline backfill      # histórico completo (desde 2004)
.venv/Scripts/python -m agro_pipeline qualidade     # só as checagens
.venv/Scripts/streamlit run painel/app.py           # painel interno
```
No terminal do Windows, usar `PYTHONIOENCODING=utf-8` se a saída quebrar acentos.
A coleta roda sozinha no GitHub Actions todo dia às 19h (BRT).

## Status (atualizar ao fim de cada sessão)

- Blocos 1–5 prontos (fundação, banco, coletores + backfill, automação, qualidade) + painel.
- Painel aprovado pelo Pedro no teste local (27/09).
- **Pedido do Pedro (próxima sessão):** documentar cada módulo e a ideia por trás dele
  (coletores, validação, repositório, pipeline, qualidade, painel) — `docs/arquitetura.md` +
  README, escrito para servir de base ao relatório.
- **Próximos:** bloco 6 (testes de robustez com banco: falha de rede, revisão, reprocessamento
  — falta o comando `reprocessar`), bloco 7 (experimento baseline × XGBoost, walk-forward;
  tratar trecho congelado da soja 2014-09-29 → 2015-01-26), bloco 8 (README e relatório).
