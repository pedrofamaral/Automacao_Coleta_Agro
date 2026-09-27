-- Schema do pipeline de dados do agronegócio.
-- Idempotente: pode ser aplicado várias vezes (python -m agro_pipeline init-db).
--
-- Modelo "longo": `serie` é o catálogo e `observacao` guarda (serie, data, valor).
-- `coleta` é a camada bruta (payload original de cada chamada a uma fonte) e
-- `execucao` registra cada rodada do pipeline.

-- Catálogo -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fonte (
    id       SMALLSERIAL PRIMARY KEY,
    codigo   TEXT NOT NULL UNIQUE,
    nome     TEXT NOT NULL,
    url      TEXT,
    licenca  TEXT
);

CREATE TABLE IF NOT EXISTS serie (
    id          SERIAL PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,
    fonte_id    SMALLINT NOT NULL REFERENCES fonte (id),
    categoria   TEXT NOT NULL CHECK (categoria IN ('preco', 'cambio', 'clima')),
    produto     TEXT,
    variavel    TEXT NOT NULL,
    local       TEXT,
    lat         NUMERIC(8, 5),
    lon         NUMERIC(8, 5),
    unidade     TEXT NOT NULL,
    frequencia  TEXT NOT NULL CHECK (frequencia IN ('diaria', 'semanal', 'mensal', 'anual')),
    -- calendário esperado da série, usado pela checagem de gaps
    calendario  TEXT NOT NULL CHECK (calendario IN ('dias_uteis', 'dias_corridos')),
    -- faixa fisicamente plausível, usada pela checagem de plausibilidade
    limite_min  DOUBLE PRECISION,
    limite_max  DOUBLE PRECISION,
    descricao   TEXT,
    ativa       BOOLEAN NOT NULL DEFAULT TRUE,
    criada_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Operação -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execucao (
    id             BIGSERIAL PRIMARY KEY,
    modo           TEXT NOT NULL CHECK (modo IN ('incremental', 'backfill', 'reprocessamento')),
    status         TEXT NOT NULL DEFAULT 'rodando'
                   CHECK (status IN ('rodando', 'sucesso', 'parcial', 'falha')),
    ambiente       TEXT NOT NULL,
    versao_codigo  TEXT,
    parametros     JSONB NOT NULL DEFAULT '{}',
    iniciada_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizada_em  TIMESTAMPTZ,
    erro           TEXT
);

CREATE TABLE IF NOT EXISTS coleta (
    id                 BIGSERIAL PRIMARY KEY,
    execucao_id        BIGINT NOT NULL REFERENCES execucao (id),
    fonte_id           SMALLINT NOT NULL REFERENCES fonte (id),
    metodo             TEXT NOT NULL,  -- ex.: 'agrobr.cepea.indicador', 'cepea.planilha'
    parametros         JSONB NOT NULL DEFAULT '{}',
    status             TEXT NOT NULL CHECK (status IN ('sucesso', 'falha')),
    tentativas         SMALLINT NOT NULL DEFAULT 1,
    duracao_ms         INTEGER,
    erro               TEXT,
    linhas_recebidas   INTEGER,
    linhas_rejeitadas  INTEGER,
    rejeicoes          JSONB NOT NULL DEFAULT '{}',  -- motivo -> quantidade
    linhas_inseridas   INTEGER,
    linhas_revisadas   INTEGER,
    payload            JSONB,
    hash_payload       TEXT,
    coletada_em        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS coleta_execucao_idx ON coleta (execucao_id);

-- Dados curados --------------------------------------------------------------

CREATE TABLE IF NOT EXISTS observacao (
    serie_id            INTEGER NOT NULL REFERENCES serie (id),
    data                DATE NOT NULL,
    valor               DOUBLE PRECISION NOT NULL,
    coleta_id           BIGINT NOT NULL REFERENCES coleta (id),
    primeira_coleta_em  TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizada_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (serie_id, data)
);

CREATE INDEX IF NOT EXISTS observacao_data_idx ON observacao (data);

-- Correções retroativas feitas pela fonte (valor mudou para uma data já gravada).
CREATE TABLE IF NOT EXISTS observacao_revisao (
    id              BIGSERIAL PRIMARY KEY,
    serie_id        INTEGER NOT NULL REFERENCES serie (id),
    data            DATE NOT NULL,
    valor_anterior  DOUBLE PRECISION NOT NULL,
    valor_novo      DOUBLE PRECISION NOT NULL,
    coleta_id       BIGINT NOT NULL REFERENCES coleta (id),
    revisada_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS observacao_revisao_serie_idx ON observacao_revisao (serie_id, data);

-- Qualidade ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS checagem_qualidade (
    id           BIGSERIAL PRIMARY KEY,
    execucao_id  BIGINT REFERENCES execucao (id),
    serie_id     INTEGER REFERENCES serie (id),
    regra        TEXT NOT NULL,
    severidade   TEXT NOT NULL CHECK (severidade IN ('info', 'aviso', 'erro')),
    aprovada     BOOLEAN NOT NULL,
    detalhe      JSONB NOT NULL DEFAULT '{}',
    criada_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS checagem_qualidade_execucao_idx ON checagem_qualidade (execucao_id);

-- Views ----------------------------------------------------------------------

-- Observações com os metadados da série, para consulta e inspeção.
CREATE OR REPLACE VIEW vw_observacao WITH (security_invoker = true) AS
SELECT s.codigo AS serie,
       s.categoria,
       s.produto,
       s.variavel,
       s.local,
       s.unidade,
       o.data,
       o.valor,
       o.coleta_id,
       o.atualizada_em
FROM observacao o
JOIN serie s ON s.id = o.serie_id;

-- vw_dataset_diario (uma coluna por série) é gerada a partir do catálogo pelo
-- init-db, ver agro_pipeline/db/inicializar.py.

-- Segurança (Supabase) -------------------------------------------------------
-- No Supabase, tabelas do schema public ficam acessíveis pela API REST com a chave
-- anon. RLS ligado sem nenhuma policy bloqueia esse acesso; o pipeline conecta como
-- dono das tabelas, que não é afetado pelo RLS.

ALTER TABLE fonte              ENABLE ROW LEVEL SECURITY;
ALTER TABLE serie              ENABLE ROW LEVEL SECURITY;
ALTER TABLE execucao           ENABLE ROW LEVEL SECURITY;
ALTER TABLE coleta             ENABLE ROW LEVEL SECURITY;
ALTER TABLE observacao         ENABLE ROW LEVEL SECURITY;
ALTER TABLE observacao_revisao ENABLE ROW LEVEL SECURITY;
ALTER TABLE checagem_qualidade ENABLE ROW LEVEL SECURITY;
