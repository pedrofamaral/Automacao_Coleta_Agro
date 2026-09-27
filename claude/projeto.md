# Pipeline Automatizado de Coleta e Estruturação de Dados Públicos do Agronegócio Brasileiro

Projeto de Estágio Obrigatório (pré-TCC) — Ciência da Computação, PUC Minas (Campus Poços de Caldas).
Orientador: Prof. Leonardo Melo. Proposta já aprovada.

## Contexto

O objetivo é construir um **pipeline automatizado de coleta, tratamento e estruturação de dados
públicos do agronegócio brasileiro** (preços agrícolas, câmbio e clima), disponibilizando um
dataset historicamente consistente. A entrega central desta disciplina é a infraestrutura de
dados em si — não um sistema de previsão completo.

## Escopo

### Dentro do escopo (fazer agora)
- Pipeline ETL automatizado e agendado
- Modelo de dados (schema) normalizado para preços, câmbio e clima
- Coletores por fonte pública
- Checagens de qualidade de dados (valores ausentes, duplicatas, inconsistências)
- Um único experimento de validação com modelo baseline de ML (só para provar que o
  dataset é utilizável para previsão — não para otimizar a previsão em si)
- Testes de robustez do pipeline (falhas, reprocessamento, execução contínua)
- Documentação técnica

### Fora do escopo (por enquanto)
- Modelo de previsão otimizado/produtizado
- Camada de custo logístico (frete) e cálculo de preço líquido por praça
- Motor de decisão de venda
- Dashboard de visualização

Esses itens foram deliberadamente cortados por orientação do professor para caber no prazo da
disciplina. Não expandir para eles sem necessidade explícita.

## Fontes de dados

| Fonte | O que oferece | Observação |
|---|---|---|
| CEPEA/ESALQ | Preços diários (soja, milho, boi, etc.) | Sem API pública documentada; portal de consulta ao banco de dados |
| CONAB | Preços agropecuários + séries históricas (32 culturas desde 1976) | Fora do decreto de dados abertos, mas disponibiliza download |
| B3 | Futuros agropecuários | API oficial só B2B; usar provedor terceiro (ex.: brapi) se necessário |
| IBGE/SIDRA | Produção agrícola (PAM/PPM) | Dados abertos |
| NASA POWER | Variáveis climáticas | API pública |
| **agrobr** (Python) | Agrega 38+ fontes públicas brasileiras com API unificada | **Importante:** é uma camada de "fetch ao vivo", não acumula histórico sozinha — a persistência é responsabilidade do nosso pipeline |

Repositório: https://github.com/bruno-portfolio/agrobr

## MVP inicial sugerido

- Commodities: **soja e milho**
- Fontes prioritárias: **CEPEA e CONAB**
- Granularidade: **diária** (essas fontes só atualizam uma vez por dia; não faz sentido buscar de hora em hora)
- Expandir para outras commodities/fontes de forma incremental depois que o pipeline básico estiver estável

## Arquitetura sugerida

1. **Coleta (ETL)** — scripts Python usando `agrobr` como camada de fetch, com scraping complementar
   onde necessário
2. **Armazenamento** — PostgreSQL + TimescaleDB (schema normalizado: preços, câmbio, clima)
3. **Agendamento** — começar simples com `cron`; Airflow é um upgrade opcional se sobrar tempo
4. **Qualidade de dados** — checagens automatizadas (nulos, duplicatas, outliers, gaps na série temporal)
5. **Validação preditiva** — um experimento com modelo baseline (XGBoost) reportando MAE/RMSE
6. **Testes** — pytest cobrindo falhas de rede, reprocessamento e execução idempotente

## Stack tecnológica

- Python 3.x
- `agrobr`
- PostgreSQL + TimescaleDB (via Docker Compose local)
- pandas
- scikit-learn / XGBoost (somente para o experimento de validação)
- pytest
- cron (Airflow como evolução opcional)

## Estrutura de repositório sugerida

```
agro-data-pipeline/
├── README.md
├── pyproject.toml              # ou requirements.txt
├── docker-compose.yml          # Postgres + TimescaleDB local
├── src/
│   ├── collectors/             # um módulo por fonte
│   │   ├── cepea.py
│   │   ├── conab.py
│   │   └── __init__.py
│   ├── db/
│   │   ├── schema.sql
│   │   └── models.py
│   ├── quality/
│   │   └── checks.py
│   └── pipeline.py             # orquestra: coleta -> valida -> persiste
├── notebooks/
│   └── validacao_baseline.ipynb
├── tests/
│   └── ...
└── docs/
    └── ...
```

## Por onde começar (ordem sugerida)

1. **Ambiente** — criar venv, instalar `agrobr`, subir PostgreSQL + TimescaleDB via Docker Compose
2. **Exploração** — em um notebook, puxar uma amostra de soja/milho via `agrobr` (CEPEA e CONAB) e
   entender o formato/qualidade dos dados retornados
3. **Schema** — desenhar as tabelas (preços, câmbio, clima) e escrever `schema.sql`
4. **Primeiro coletor** — script que busca o preço diário de uma commodity e grava no banco
5. **Repetir** para as demais fontes/commodities do MVP
6. **Agendamento** — configurar `cron` para rodar o pipeline diariamente
7. **Qualidade de dados** — adicionar checagens automatizadas sobre o que já foi coletado
8. **Testes** — cobrir falhas de rede, reprocessamento e idempotência
9. **Experimento de validação** — treinar o baseline e reportar métricas de erro
10. **Documentação** — README técnico + notas para o relatório final da disciplina

## Coisas para lembrar durante o desenvolvimento

- Manter o escopo disciplinado — não expandir para previsão otimizada, logística ou dashboard
  nesta fase
- `agrobr` não acumula histórico sozinha — a persistência é responsabilidade do nosso pipeline
- Granularidade diária é suficiente e realista (CEPEA/CONAB atualizam uma vez por dia)
- Documentar decisões técnicas ao longo do caminho, para facilitar a redação do relatório final
