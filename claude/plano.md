# Plano — Pipeline automatizado de dados do agronegócio (pré-TCC, entrega 20/10/2026)

## Contexto

O objetivo final do TCC é **prever preços agrícolas com ML**. A entrega do estágio obrigatório
(20/10/2026, faltam cerca de 3 semanas) é a **infraestrutura de dados**: um pipeline que coleta
todo dia, guarda o histórico de forma consistente e rastreável, e prova com um experimento
baseline que o dataset serve para previsão.

A pasta está vazia, exceto por `CLAUDE.md` e `claude/`. Ambiente disponível: Windows 11,
Python 3.13, Docker 29, git. Não há `uv` nem `gh`.

### O que a pesquisa no agrobr (v1.1.0) mudou em relação ao .md original
- **CEPEA funciona, mas por um espelho.** O site oficial bloqueia acesso programático via
  Cloudflare. O agrobr lê o CEPEA pelo espelho do Notícias Agrícolas, usando
  `cepea.indicador('soja', inicio, fim)`. O contrato `preco_diario` retorna as colunas
  `data, produto, praca, valor, unidade, fonte`, só com dias úteis e valores > 0.
  **Não está documentado até que ano o histórico vai.** Esse é o maior risco e precisa ser
  verificado no dia 1.
- **A CONAB não tem preço diário no agrobr.** Só oferece safras, balanço e custo, com
  frequência mensal, e o download de soja/milho tem problema conhecido. Por isso a CONAB
  **sai do MVP de preços** e vira uma fonte mensal opcional.
- **Câmbio:** `bcb.ptax(data_inicial, data_final)` retorna `cotacao_compra` e `cotacao_venda`.
- **Clima:** `nasa_power.clima_ponto(lat, lon, inicio, fim)` retorna dados diários desde 1981
  com 7 variáveis (`temp_media`, `temp_max`, `temp_min`, `precip_mm`, `umidade_rel`,
  `radiacao_mj`, `vento_ms`). Há um atraso de cerca de 2 dias.
- A API do agrobr é assíncrona. Vamos usar os wrappers síncronos em `agrobr.sync`.

## Decisões recomendadas (registrar em `claude/decisoes.md`)
1. **Postgres 16 puro, sem TimescaleDB.** O volume é pequeno (dezenas de milhares de linhas)
   e isso deixa o banco portável para os planos gratuitos de hospedagem.
2. **Hospedagem mínima = GitHub Actions (agendador e execução) + Neon Postgres (plano
   gratuito, 0,5 GB).** Custo zero. O Vercel **não serve** para isso: ele é feito para
   funções web com timeout curto, não para jobs em lote. Só faria sentido para o dashboard,
   que está fora do escopo.
3. **Subir para a nuvem cedo, por volta de 06/10**, e não "depois". Coleta contínua é um
   requisito, e o PC desligado quebra a série. Com duas semanas rodando sozinho, a tabela
   `execucao` vira evidência numérica para o relatório. O PC fica só para desenvolvimento
   (Postgres no Docker).
4. **Modelo "longo" (catálogo de séries + observações)** em vez de uma tabela por domínio.
   Preço, câmbio e clima viram séries do mesmo formato. Adicionar uma fonte nova, ou lidar
   com frequências diferentes (diária ou mensal), não exige mudar o schema. O dataset de ML
   sai de uma view pivotada.
5. **Camada bruta guardada.** Cada coleta salva o payload original em JSONB. Isso permite
   reprocessar sem chamar a fonte de novo e garante a rastreabilidade de cada valor.
6. **Ambiente com venv + pip** (sem uv), acesso ao banco por SQLAlchemy Core com SQL
   explícito e psycopg 3.

## Séries do MVP
| Código | Fonte | Unidade |
|---|---|---|
| `cepea.soja` (praça conforme o agrobr retornar, provavelmente Paranaguá) | CEPEA | BRL/sc60kg |
| `cepea.milho` (provavelmente Campinas) | CEPEA | BRL/sc60kg |
| `bcb.ptax_venda`, `bcb.ptax_compra` | BCB | BRL/USD |
| `nasa.<ponto>.<variavel>`: 3 pontos × 7 variáveis | NASA POWER | °C, mm, %, MJ/m², m/s |

Pontos de clima (regiões produtoras): Sorriso-MT (−12,55; −55,71), Rio Verde-GO (−17,80; −50,93)
e Cascavel-PR (−24,96; −53,46).
Opcional, se sobrar tempo: `conab.safras` mensal (estimativa de produção).

## Schema (`src/agro_pipeline/db/schema.sql`, idempotente com `IF NOT EXISTS`)
- `fonte` (id, codigo único, nome, url, licenca)
- `serie`: é o catálogo. Campos: id, codigo único, fonte_id, categoria (preco/cambio/clima),
  produto, variavel, local, lat, lon, unidade, frequencia (diaria/mensal/anual), ativa
- `execucao`: uma linha por rodada do pipeline. Campos: id, iniciada_em, finalizada_em,
  modo (incremental/backfill/reprocessamento), status (rodando/sucesso/parcial/falha),
  ambiente (local/github_actions), versao_codigo (sha do git)
- `coleta`: camada bruta, uma linha por chamada a uma fonte. Campos: id, execucao_id,
  fonte_id, parametros JSONB, tentativas, duracao_ms, status, erro, linhas_recebidas,
  linhas_inseridas, linhas_revisadas, payload JSONB, hash_payload
- `observacao`: é o dado curado. **PK (serie_id, data)**. Campos: valor DOUBLE PRECISION,
  coleta_id, primeira_coleta_em, atualizada_em
- `observacao_revisao`: guarda as correções retroativas feitas pelas fontes. Campos:
  serie_id, data, valor_anterior, valor_novo, coleta_id, revisada_em
- `checagem_qualidade`: id, execucao_id, serie_id, regra, severidade (info/aviso/erro),
  aprovada, detalhe JSONB
- `vw_dataset_diario`: pivô com uma linha por dia e uma coluna por série. É a entrada do ML.

## Fluxo do pipeline (`pipeline.py`)
1. Abre uma `execucao`.
2. Para cada coletor, **isolando falhas** (uma fonte quebrada não derruba as outras e a
   execução fica com status `parcial`):
   - Calcula a janela. No modo incremental, vai de `max(data) − N dias` até hoje. A
     sobreposição captura revisões e o atraso de 2 dias da NASA. No modo backfill, vai de
     `--desde` até hoje.
   - Chama o agrobr com retry (3 tentativas e backoff exponencial) e grava a `coleta` com o
     payload bruto.
   - Transforma o resultado no formato canônico `(serie_codigo, data, valor)` e aplica a
     validação de entrada: tipo, `valor > 0` para preços, data não futura, sem duplicatas e
     unidade igual à do catálogo.
   - Grava tudo numa transação: insere o que é novo, registra em `observacao_revisao` os
     valores que mudaram e ignora os iguais. **Isso garante idempotência.**
3. Roda as checagens de qualidade e grava os resultados em `checagem_qualidade`.
4. Fecha a execução. Se o status for `falha`, o processo sai com código ≠ 0 e o GitHub
   Actions manda e-mail.

**Comandos (CLI):**
- `python -m agro_pipeline init-db`
- `run`: incremental
- `backfill --desde 2010-01-01 [--fonte cepea]`
- `reprocessar --desde ...`: reconstrói `observacao` a partir de `coleta.payload`
- `qualidade`

## Regras de qualidade (`quality/checks.py`)
- **Gaps:** dias úteis sem valor, usando o calendário de feriados do Brasil (lib `holidays`).
  Para o clima, conta dias corridos.
- **Outliers:** variação diária acima de um limite, ou z-score robusto (MAD) numa janela de
  60 dias.
- **Defasagem:** último dado mais antigo que N dias úteis. Detecta quando uma fonte quebrou
  em silêncio.
- **Rejeições na validação de entrada:** nulos, valores ≤ 0, duplicatas no payload.
- **Revisões:** contagem por execução, apenas informativa.

## Estrutura do repositório (raiz = `TCC/`, que vira o repo git)
```
TCC/
├── CLAUDE.md, claude/              # contexto (já existe)
├── README.md, pyproject.toml, .env.example, .gitignore, docker-compose.yml
├── src/agro_pipeline/
│   ├── __main__.py, cli.py, config.py, catalogo.py   # catálogo = séries do MVP
│   ├── collectors/ base.py, cepea.py, bcb.py, nasa_power.py
│   ├── db/ schema.sql, conexao.py, repositorio.py    # upsert, revisões, execução
│   ├── quality/checks.py
│   └── pipeline.py
├── tests/ unit/ (agrobr mockado)  integration/ (Postgres do docker)
├── notebooks/ 01_exploracao.ipynb, 02_validacao_baseline.ipynb
├── .github/workflows/ coleta-diaria.yml, testes.yml
└── docs/
```
Cada coletor implementa a mesma interface: `buscar(inicio, fim) -> payload bruto` e
`transformar(payload) -> DataFrame canônico`. Isso deixa os testes simples, com transformação
pura e busca mockada.

## Cronograma (27/09 → 20/10)
| Período | Entrega |
|---|---|
| **27/09–29/09** | Ambiente (venv, docker-compose com Postgres) e notebook 01. **Validar até onde vai o histórico do CEPEA**, a praça de cada indicador e o formato real das colunas. |
| 30/09–04/10 | Schema, repositório, coletores CEPEA e BCB, CLI `run` e `backfill`, backfill histórico. |
| 05/10–07/10 | Coletor NASA POWER. Criação do Neon e do workflow `coleta-diaria.yml` (cron `0 22 * * *` = 19h de Brasília, depois da publicação do CEPEA). **Pipeline rodando sozinho.** |
| 08/10–12/10 | Checagens de qualidade, testes de robustez, workflow de testes. |
| 13/10–16/10 | Notebook 02: baseline ingênuo (amanhã = hoje) e sazonal contra XGBoost com lags de preço, câmbio e clima. Validação walk-forward, com MAE, RMSE e MAPE para horizontes de 1 e 5 dias. |
| 17/10–20/10 | README, docs, métricas de operação tiradas da tabela `execucao` e folga. |

## Dificuldades previstas e mitigação
1. ~~**Histórico curto do CEPEA pelo espelho.**~~ **Confirmado e resolvido em 27/09:** o
   agrobr só traz 15 dias, mas a planilha oficial (`/br/indicador/series/<produto>.aspx?id=`)
   baixa automaticamente a série completa (soja desde 2006, milho desde 2004). O coletor
   CEPEA fica híbrido (ver `decisoes.md`).
2. **Espelho HTML frágil** (se o layout mudar, a coleta quebra). Mitigação: checagem de
   defasagem, status de falha e e-mail do GitHub Actions. Fixar a versão do agrobr.
3. **CONAB sem preço diário.** Já foi cortada do MVP, como explicado acima.
4. **Pegadinhas do GitHub Actions.** O cron pode atrasar alguns minutos, e em repositório
   público ele é desativado após 60 dias sem commits. Nada disso afeta o prazo.
5. **Falsos positivos de gap** em fins de semana e feriados. Solução: calendário de dias úteis.
6. **Pouca amostra para ML** se o histórico for curto. O experimento só precisa provar
   viabilidade, e a comparação com o baseline ingênuo é o que dá significado às métricas.

## Verificação
- `docker compose up -d`, depois `python -m agro_pipeline init-db`, depois `backfill` e
  `run`. Conferir no banco as contagens por série e as lacunas.
- **Idempotência:** rodar `run` duas vezes seguidas. A segunda deve dar 0 inserções e
  0 revisões.
- `pytest` cobrindo:
  - transformações;
  - regras de qualidade com fixtures que têm gaps e outliers;
  - falha de rede simulada (retry, coleta com status `falha`, demais fontes seguem,
    execução `parcial`);
  - revisão simulada (1 linha em `observacao_revisao`);
  - reprocessamento (apagar `observacao` e reconstruir a partir das coletas com resultado
    idêntico).
- **Na nuvem:** `workflow_dispatch` manual e depois execuções agendadas diárias. Evidência:
  consulta de % de sucesso e completude na tabela `execucao`.
- **Notebook 02** roda de ponta a ponta a partir de `vw_dataset_diario`.

## Primeiro passo após aprovação
Registrar as decisões 1–6 em `claude/decisoes.md`. Depois, `git init`, criar o esqueleto
(pyproject, docker-compose, .gitignore, .env.example) e o notebook 01 de exploração para
validar o CEPEA.
