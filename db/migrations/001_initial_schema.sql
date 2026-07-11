-- Phase 1 schema: market data only (Betfair).
-- Phase 2 columns (form, class, weight, etc.) are additive — added in 002_form_features.sql.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────
-- Races
-- ─────────────────────────────────────────────
CREATE TABLE races (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    betfair_market_id   TEXT UNIQUE NOT NULL,
    track               TEXT NOT NULL,
    state               TEXT NOT NULL,          -- NSW | VIC | QLD | WA | SA | TAS | ACT | NT
    race_name           TEXT,
    race_number         INT,
    race_date           DATE NOT NULL,
    scheduled_jump_at   TIMESTAMPTZ NOT NULL,   -- always stored in UTC, display in state tz
    distance_m          INT,
    going               TEXT,                   -- Good | Soft | Heavy | Synthetic etc.
    field_size          INT,
    status              TEXT NOT NULL DEFAULT 'upcoming',  -- upcoming | open | closed | settled | void
    form_fetched_at     TIMESTAMPTZ,            -- last time nightly batch ran for this race
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_races_date ON races (race_date);
CREATE INDEX idx_races_status ON races (status);
CREATE INDEX idx_races_jump ON races (scheduled_jump_at);

-- ─────────────────────────────────────────────
-- Runners
-- ─────────────────────────────────────────────
CREATE TABLE runners (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    race_id                 UUID NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    betfair_selection_id    BIGINT NOT NULL,
    horse_name              TEXT NOT NULL,
    barrier                 INT,
    jockey                  TEXT,
    trainer                 TEXT,
    weight_kg               NUMERIC(5, 2),      -- Phase 1: may be null
    scratched               BOOLEAN NOT NULL DEFAULT FALSE,
    scratched_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (race_id, betfair_selection_id)
);

CREATE INDEX idx_runners_race ON runners (race_id);
CREATE INDEX idx_runners_scratched ON runners (scratched);

-- ─────────────────────────────────────────────
-- Odds ticks (append-only time series)
-- One row per runner per poll tick.
-- ─────────────────────────────────────────────
CREATE TABLE odds_ticks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    runner_id       UUID NOT NULL REFERENCES runners(id) ON DELETE CASCADE,
    ticked_at       TIMESTAMPTZ NOT NULL,
    win_back        NUMERIC(8, 2),      -- best available back price
    win_lay         NUMERIC(8, 2),      -- best available lay price
    win_traded_vol  NUMERIC(14, 2),     -- cumulative matched volume
    is_bsp          BOOLEAN DEFAULT FALSE,
    data_source     TEXT NOT NULL DEFAULT 'betfair_stream'
);

CREATE INDEX idx_ticks_runner_time ON odds_ticks (runner_id, ticked_at DESC);
CREATE INDEX idx_ticks_ticked_at ON odds_ticks (ticked_at DESC);

-- ─────────────────────────────────────────────
-- Predictions
-- One row per runner per model version (most recent is current prediction).
-- ─────────────────────────────────────────────
CREATE TABLE predictions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    runner_id               UUID NOT NULL REFERENCES runners(id) ON DELETE CASCADE,
    model_version           TEXT NOT NULL,
    predicted_at            TIMESTAMPTZ NOT NULL,
    win_prob                NUMERIC(6, 4),      -- [0, 1]
    place_prob              NUMERIC(6, 4),      -- [0, 1]
    confidence_score        NUMERIC(6, 4),      -- decays for data-sparse runners
    market_implied_prob     NUMERIC(6, 4),      -- overround-adjusted, at prediction time
    market_odds_at_pred     NUMERIC(8, 2),      -- raw decimal odds used for above
    edge                    NUMERIC(6, 4),      -- win_prob - market_implied_prob
    feature_snapshot        JSONB,              -- point-in-time features (audit trail)
    UNIQUE (runner_id, model_version, predicted_at)
);

CREATE INDEX idx_predictions_runner ON predictions (runner_id);
CREATE INDEX idx_predictions_model ON predictions (model_version);

-- ─────────────────────────────────────────────
-- Outcomes
-- Filled post-race by the results ingestion job.
-- ─────────────────────────────────────────────
CREATE TABLE outcomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    runner_id       UUID NOT NULL REFERENCES runners(id) ON DELETE CASCADE,
    race_id         UUID NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    finish_position INT,
    won             BOOLEAN NOT NULL DEFAULT FALSE,
    placed          BOOLEAN NOT NULL DEFAULT FALSE,  -- top 3
    bsp             NUMERIC(8, 2),                   -- Betfair Starting Price
    settled_at      TIMESTAMPTZ,
    UNIQUE (runner_id)
);

CREATE INDEX idx_outcomes_race ON outcomes (race_id);
CREATE INDEX idx_outcomes_won ON outcomes (won);

-- ─────────────────────────────────────────────
-- Model versions (registry)
-- ─────────────────────────────────────────────
CREATE TABLE model_versions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version             TEXT UNIQUE NOT NULL,
    is_production       BOOLEAN NOT NULL DEFAULT FALSE,
    training_cutoff     DATE NOT NULL,
    feature_set_version TEXT NOT NULL,          -- e.g. "s_tier_v1", "sa_tier_v1"
    brier_score         NUMERIC(8, 6),
    log_loss            NUMERIC(8, 6),
    market_beat_margin  NUMERIC(8, 6),          -- vs market-implied baseline, on hold-out set
    promoted_at         TIMESTAMPTZ,
    retired_at          TIMESTAMPTZ,
    metadata            JSONB,                  -- race count, feature importances, etc.
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enforce single production model at all times.
CREATE UNIQUE INDEX idx_model_versions_single_prod
    ON model_versions (is_production)
    WHERE is_production = TRUE;

-- ─────────────────────────────────────────────
-- updated_at trigger
-- ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_races_updated_at
    BEFORE UPDATE ON races
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_runners_updated_at
    BEFORE UPDATE ON runners
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
