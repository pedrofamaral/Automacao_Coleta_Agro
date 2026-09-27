# Registro de decisões técnicas

Cada decisão relevante entra aqui com data, contexto e justificativa — isso vira material
direto para o capítulo de metodologia/implementação do relatório.

Formato:

```
## AAAA-MM-DD — Título curto
**Decisão:** o que foi escolhido
**Alternativas:** o que foi considerado e descartado
**Motivo:** por quê
```

---

## 2026-09-27 — Prazo e contexto
**Decisão:** entrega do Estágio Obrigatório (pré-TCC) em **20/10/2026**. Objetivo final do TCC
é previsão de preços com ML; nesta etapa, entrega = pipeline de dados + 1 experimento baseline.

## 2026-09-27 — CONAB fora do MVP de preços
**Decisão:** MVP de preços usa só CEPEA (soja, milho). CONAB vira fonte mensal opcional.
**Alternativas:** manter CONAB como segunda fonte de preço diário.
**Motivo:** o `agrobr` não expõe preço diário da CONAB (só safras, balanço e custo de produção,
mensais) e documenta problema no download das séries de soja/milho.

## 2026-09-27 — Fontes de câmbio e clima
**Decisão:** câmbio = BCB PTAX (compra e venda, diário). Clima = NASA POWER diário, 7 variáveis,
em 3 pontos de regiões produtoras: Sorriso-MT (−12,55; −55,71), Rio Verde-GO (−17,80; −50,93),
Cascavel-PR (−24,96; −53,46).
**Motivo:** ambos são APIs públicas sem autenticação, com histórico longo (NASA desde 1981).
Pontos representam produção de soja/milho, não a praça de formação de preço (Paranaguá/Campinas).

## 2026-09-27 — Postgres puro, sem TimescaleDB
**Decisão:** PostgreSQL 16 sem extensões.
**Alternativas:** PostgreSQL + TimescaleDB.
**Motivo:** volume da ordem de dezenas de milhares de linhas — hypertables não trazem ganho
mensurável; e Postgres puro roda em qualquer hospedagem gratuita (Neon, Supabase).

## 2026-09-27 — Hospedagem: GitHub Actions + Supabase
**Decisão:** agendamento e execução via GitHub Actions (cron diário `0 22 * * *` = 19h BRT);
banco no **Supabase** (plano gratuito, 500 MB; PostgreSQL 17.6, região us-west-2), conexão
pelo **Session pooler** (porta 5432). O mesmo banco é usado desde o desenvolvimento.
**Alternativas:** Neon (equivalente em recursos); Postgres local no Docker (descartado: a
virtualização está desligada na BIOS do notebook); cron/Agendador de Tarefas no PC; Vercel.
**Motivo:** coleta contínua exige máquina sempre disponível — PC desligado quebra a série.
Supabase escolhido pelo editor de tabelas/SQL (útil para inspeção e prints do relatório).
Conexão direta do Supabase gratuito é só IPv6, por isso o pooler (necessário para o GitHub
Actions). Volume estimado < 100 MB (~200 mil observações + payloads brutos). Vercel é voltado
a funções web com timeout curto, não a jobs em lote. Subir cedo gera ~2 semanas de execuções
registradas como evidência para o relatório.

## 2026-09-27 — Modelo de dados "longo" (catálogo de séries + observações)
**Decisão:** tabelas `serie` (catálogo) + `observacao` (serie_id, data, valor), em vez de uma
tabela por domínio (preco/cambio/clima). Dataset de ML sai de uma view pivotada.
**Motivo:** fontes com frequências diferentes e novas séries entram sem alterar o schema;
checagens de qualidade são escritas uma vez para todas as séries.

## 2026-09-27 — Camada bruta, revisões e log de execução
**Decisão:** toda coleta guarda o payload original (JSONB) em `coleta`; valores alterados
retroativamente pela fonte são registrados em `observacao_revisao`; cada rodada gera uma linha
em `execucao`.
**Motivo:** permite reprocessar sem depender da fonte, rastrear a origem de cada valor, provar
idempotência e medir a operação do pipeline (taxa de sucesso, completude).

## 2026-09-27 — Ferramentas
**Decisão:** Python 3.13 + venv/pip; `agrobr` (API síncrona em `agrobr.sync`); SQLAlchemy Core
com SQL explícito + psycopg 3; pytest.

## 2026-09-27 — Teste de viabilidade das fontes (agrobr 1.1.0)
Resultado de chamadas reais:

| Fonte | Chamada | Resultado |
|---|---|---|
| CEPEA soja | `cepea.indicador('soja', inicio='2000-01-01')` | **só 15 dias úteis** (04–25/09/2026), praça Paranaguá/PR, BRL/sc60kg, 0,7 s |
| CEPEA milho | idem | só 15 dias úteis, praça Campinas/SP |
| CEPEA planilha | `GET cepea.esalq.usp.br/br/indicador/series/soja.aspx?id=92` e `milho.aspx?id=77` | **série completa**: soja desde 13/03/2006 (5.122 dias), milho desde 02/08/2004 (5.518 dias); colunas R$ e US$; valores recentes idênticos aos do agrobr |
| BCB PTAX | `bcb.ptax(data_inicial='01/01/2004', ...)` | 5.710 dias desde 02/01/2004, 0,8 s. **Datas no formato dd/mm/aaaa** |
| NASA POWER | `clima_ponto(-12.55, -55.71, '2004-01-01', ...)` | 8.305 dias, 46 s, 2 últimos dias nulos (atraso da fonte) |

Achados:
- O agrobr lê a página de indicador do CEPEA, que só exibe ~15 dias; o cache DuckDB dele só
  acumula se for chamado diariamente. **Nosso pipeline é quem constrói o histórico.**
- A planilha do CEPEA é `.xls` com cabeçalho OLE corrompido: ler com
  `pd.read_excel(..., engine="xlrd", engine_kwargs={"ignore_workbook_corruption": True})`.
  4 linhas de cabeçalho; dados a partir da linha 5 (Data dd/mm/aaaa, À vista R$, À vista US$).
- NASA `WS2M` (vento) vem com média 0,11 m/s em Sorriso — valor idêntico na API crua da NASA,
  logo é característica da fonte, não bug. Tratar como variável suspeita (checagem de
  plausibilidade) e não usar como feature sem justificativa.

## 2026-09-27 — CEPEA: coletor híbrido (planilha + agrobr)
**Decisão:** backfill do CEPEA pela planilha oficial (série completa); coleta diária pelo
`agrobr` (janela de 15 dias úteis). Se o último dado no banco for mais antigo que a janela
do agrobr (pipeline parado >3 semanas), o coletor cai automaticamente para a planilha.
**Alternativas:** só planilha todo dia (400 KB, funciona, mas não usa o agrobr); só agrobr
(sem histórico).
**Motivo:** histórico longo é pré-requisito do ML; a coleta diária via agrobr traz parser
mantido e metadados de proveniência; o fallback cobre o cenário de indisponibilidade.
Divergências entre as duas fontes no mesmo dia viram checagem de qualidade.

## 2026-09-27 — Bloco 2 (banco) concluído: detalhes do schema
**Decisão:**
- Schema em `src/agro_pipeline/db/schema.sql`, idempotente; aplicado por
  `python -m agro_pipeline init-db` (rodado 2× seguidas sem erro no Supabase).
- Catálogo (3 fontes, 25 séries) definido em código (`catalogo.py`) e sincronizado no banco
  por upsert; série retirada do catálogo fica `ativa = FALSE`, sem apagar histórico.
- Cada série carrega `calendario` (dias úteis vs corridos → checagem de gaps) e
  `limite_min`/`limite_max` (faixa plausível → checagem de plausibilidade). As regras de
  qualidade ficam guiadas pelo catálogo, sem constantes espalhadas no código.
- `vw_dataset_diario` é **gerada a partir do catálogo** (uma coluna por série diária, uma linha
  por dia corrido entre a primeira e a última observação); nova série vira coluna sozinha.
- `observacao_revisao` referencia `serie`, não `observacao`, para o reprocessamento poder
  reconstruir `observacao` sem violar FK.
- **Segurança no Supabase:** tabelas do schema `public` ficam expostas na API REST com a chave
  `anon`. RLS ligado em todas as tabelas (sem policies) e views com `security_invoker = true`.
  Verificado: o papel `anon` enxerga 0 linhas; o pipeline (dono das tabelas) não é afetado.
- `config.py` normaliza a `DATABASE_URL` (driver `postgresql+psycopg`, `sslmode=require` fora do
  localhost), então a string copiada do painel funciona sem edição.

## 2026-09-27 — Bloco 3 (coletores + backfill) concluído
**Implementação:**
- Coletores como `Tarefa`s independentes (`collectors/`): CEPEA soja, CEPEA milho, PTAX e
  NASA × 3 pontos = 6 tarefas; cada uma gera 1 linha em `coleta`. Interface
  `buscar(inicio, fim)` (fala com a fonte, devolve payload bruto) + `transformar(registros)`
  (pura; reutilizável no reprocessamento).
- Retry com backoff exponencial (3 tentativas, 2 s/4 s). Falha isolada por tarefa → execução
  `parcial`; CLI sai com código 1 se algo falhar (alerta do GitHub Actions).
- Validação de entrada (`validacao.py`) guiada pelo catálogo; motivos gravados em
  `coleta.rejeicoes`: nulo, data futura, não positivo, fora da faixa, unidade/praça divergente,
  duplicada, série desconhecida.
- Gravação idempotente (`repositorio.gravar_observacoes`): COPY para tabela temporária →
  revisões registradas → upsert que só altera valor que mudou (tolerância 1e-9).
- Janela incremental = última data gravada − 10 dias de sobreposição; série sem dado cai no
  histórico completo (então `run` num banco vazio também faz o backfill).
- Log do structlog do agrobr filtrado para WARNING (sem isso sai debug com traceback).

**Resultados (execuções #1 e #2, local → Supabase):**

| Tarefa | Método | Recebidas | Inseridas | Período |
|---|---|---|---|---|
| cepea.soja | planilha | 5.122 | 5.122 | 13/03/2006 – 25/09/2026 |
| cepea.milho | planilha | 5.518 | 5.518 | 02/08/2004 – 25/09/2026 |
| bcb.ptax | agrobr | 5.710 | 11.418 (venda + compra) | 02/01/2004 – 25/09/2026 |
| nasa × 3 pontos | agrobr | 8.306 cada | 58.118 cada | 01/01/2004 – 24/09/2026 |

- Total: **196.412 observações**, banco com 31 MB. Backfill em 2 min 54 s; incremental em 18 s.
- **Idempotência comprovada:** a execução incremental logo após o backfill inseriu 0 e revisou 0.
- **Consistência entre fontes:** na incremental o CEPEA veio pelo agrobr (página do indicador)
  e os valores coincidiram exatamente com os da planilha (0 revisões).
- **PTAX:** o payload do BCB trouxe 1 data duplicada (2 boletins no mesmo dia); a transformação
  mantém o último boletim (fechamento).
- **NASA:** 24 valores nulos por ponto no backfill (últimos ~3 dias ainda não publicados; a
  radiação tem atraso maior, até 22/09). Rejeitados como `nulo` e recuperados nas próximas
  execuções graças à sobreposição de 10 dias.

## 2026-09-27 — Bloco 4 (automação) concluído
**Implementação:** repositório https://github.com/pedrofamaral/Automacao_Coleta_Agro (público).
- `.github/workflows/coleta-diaria.yml`: cron `0 22 * * *` (19h BRT) + disparo manual
  (`run`/`backfill`); `concurrency` impede duas coletas simultâneas; roda `init-db` antes
  (sincroniza catálogo) e depois o comando; `DATABASE_URL` vem do secret do repositório.
- `.github/workflows/testes.yml`: pytest a cada push.
- CLI escreve a tabela da execução no resumo do run (`GITHUB_STEP_SUMMARY`).

**Resultado:** testes verdes no Actions; primeira coleta na nuvem (execução #3,
`ambiente = github_actions`, versão `05a5e49`) com sucesso em 15 s. **O CEPEA respondeu a
partir de IP de datacenter nos EUA** (risco de bloqueio pelo Cloudflare não se confirmou),
porém levou 6,4 s contra 0,8 s localmente — convém registrar a fonte efetiva usada pelo agrobr
(`return_meta=True` → `selected_source`) para saber se veio do CEPEA ou do espelho.
Nada inserido (dados do dia já estavam no banco), como esperado.

## 2026-09-27 — Painel Streamlit como ferramenta interna (após o bloco 5)
**Decisão:** construir um painel Streamlit **local** de inspeção e análise exploratória
(operação do pipeline, qualidade das séries, exploração para as features do ML), depois do
bloco 5, com ~1 dia de esforço.
**Enquadramento:** não é o "dashboard de visualização" cortado do escopo — é ferramenta de
apoio às entregas de robustez, qualidade e validação. **Pendente: ok do orientador** (Pedro vai
comentar com ele).
**Motivo:** cronograma ~1 semana adiantado; gráficos servem de evidência no relatório.
Publicação na web (Streamlit Cloud) só com um usuário de banco somente leitura.

## 2026-09-27 — Bloco 5 (qualidade) concluído
**Implementação** (`quality/checks.py`): regras que **não alteram dados**, só geram alertas em
`checagem_qualidade`; rodam ao fim de toda execução e pelo comando `qualidade`. Parâmetros
por série no catálogo (`defasagem_max`, `tipico_min/max`, `NAO_PUBLICA`).

| Regra | Aplica a | Severidade | Reprova quando |
|---|---|---|---|
| completude | todas | aviso | falta dia esperado nos últimos 30 dias |
| defasagem | todas | **erro** (CLI sai com 1) | dias sem dado > máximo (CEPEA 3 úteis, PTAX 2 úteis, NASA 7 corridos) |
| saltos | preço, câmbio | aviso | z-score robusto do log-retorno > 6 nos últimos 30 dias |
| valores_repetidos | preço, câmbio | aviso | ≥ 5 dias seguidos com o mesmo valor nos últimos 30 dias |
| faixa_tipica | clima | aviso | mediana de 365 dias fora da faixa típica |
| rejeicoes, revisoes | execução | info | — (contagens) |

**Calibração com os dados reais:**
- Calendário = feriados da B3 (`holidays.financial_holidays("BVMF")`, inclui carnaval e Corpus
  Christi). PTAX bate 100% (0 faltantes, 0 extras em 5.709 dias). O CEPEA também não publica em
  24/12 e 31/12 — com isso soja fica 99,84% completa (8 faltantes) e milho 99,73% (15).
- Saltos: sem piso, o MAD zera em trechos parados e a soja dava 160 alarmes falsos. Com piso de
  1%/dia e limite z = 6 restam 9 (soja), 3 (milho), 3 (PTAX) — eventos reais: crise de 10/2008,
  "Joesley Day" 18/05/2017, seca nos EUA 07/2012. Por isso a regra alerta e não rejeita.

**Achados de qualidade nas fontes (material para o relatório):**
1. **Soja CEPEA congelada em R$:** 82 dias úteis seguidos em R$ 61,17 (29/09/2014 → 26/01/2015)
   na planilha oficial, enquanto a coluna em US$ varia (79 valores distintos no período). 11,1%
   dos dias da soja não têm variação (milho 1,8%, PTAX 0,5%). **Tratar no ML** (reconstruir
   R$ = US$ × PTAX ou excluir o trecho).
2. **Vento NASA em Sorriso/MT:** mediana anual 0,08 m/s (Rio Verde 1,78; Cascavel 0,73) —
   só esse ponto é suspeito.
3. **Radiação NASA 07/09/2026 nula** nos 3 pontos, ainda nula na fonte.

**Correção de desenho encontrada pela checagem:** a janela incremental (última data − 10 dias)
nunca revisitaria um buraco no meio da série. NASA passou a reconsultar 30 dias (= janela
recente da completude): lacuna recente sinalizada é recuperada sozinha quando a fonte publicar.

**Proveniência do CEPEA:** `coleta.parametros.proveniencia` guarda `selected_source`,
`attempted_sources`, `from_cache` do agrobr. Localmente veio do **cache DuckDB do agrobr**;
no Actions (sem cache) mostrará a fonte real.

**Testes:** 23 unitários (7 novos de qualidade, com séries sintéticas contendo cada problema).

---

## Questões em aberto

- [x] ~~Profundidade do histórico do CEPEA via agrobr~~ — 15 dias; resolvido com a planilha.
- [x] ~~Praça de cada indicador~~ — soja Paranaguá/PR, milho Campinas/SP.
- [x] ~~Registrar a fonte efetiva do agrobr~~ — feito no bloco 5 (`proveniencia`).
- [ ] Tratamento do trecho congelado da soja (2014-09-29 → 2015-01-26) no experimento de ML.
- [ ] Vento de Sorriso/MT: excluir das features ou justificar.
- [ ] Ok do orientador para o painel Streamlit como ferramenta interna.
- [ ] Série de PTAX: usar `cotacao_venda` como principal (padrão de mercado) — confirmar.
- [ ] **Licenças** — CEPEA é CC BY-NC 4.0 (ok para uso acadêmico, exige atribuição);
      documentar a licença de cada fonte no README.
