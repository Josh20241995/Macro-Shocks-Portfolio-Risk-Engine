-- scripts/init_timescaledb.sql
-- TimescaleDB schema initialization for the Macro Shock Risk Engine.
-- Applied automatically on first container start via docker-compose.
-- For production: apply via migration tool with version tracking.

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ============================================================
-- Market Snapshots (time-series)
-- ============================================================
CREATE TABLE IF NOT EXISTS market_snapshots (
    timestamp               TIMESTAMPTZ     NOT NULL,
    snapshot_id             UUID            DEFAULT gen_random_uuid(),
    source                  TEXT,

    -- Equity
    spx_level               DOUBLE PRECISION,
    spx_1d_return           DOUBLE PRECISION,
    spx_5d_return           DOUBLE PRECISION,
    spx_from_52w_high       DOUBLE PRECISION,
    nasdaq_level            DOUBLE PRECISION,
    nasdaq_1d_return        DOUBLE PRECISION,
    russell_2000_level      DOUBLE PRECISION,

    -- Yields
    yield_2y                DOUBLE PRECISION,
    yield_5y                DOUBLE PRECISION,
    yield_10y               DOUBLE PRECISION,
    yield_30y               DOUBLE PRECISION,
    slope_2_10_bps          DOUBLE PRECISION,
    real_yield_10y          DOUBLE PRECISION,
    breakeven_10y           DOUBLE PRECISION,

    -- Volatility
    vix_spot                DOUBLE PRECISION,
    vix_1m                  DOUBLE PRECISION,
    vix_3m                  DOUBLE PRECISION,
    vix_term_slope          DOUBLE PRECISION,
    realized_vol_1m         DOUBLE PRECISION,
    vvix                    DOUBLE PRECISION,
    move_index              DOUBLE PRECISION,
    put_call_ratio          DOUBLE PRECISION,
    skew_25d                DOUBLE PRECISION,

    -- Credit
    hy_spread_bps           DOUBLE PRECISION,
    ig_spread_bps           DOUBLE PRECISION,
    em_spread_bps           DOUBLE PRECISION,
    hy_1d_change_bps        DOUBLE PRECISION,
    ig_1d_change_bps        DOUBLE PRECISION,

    -- Liquidity
    bid_ask_spx_bps         DOUBLE PRECISION,
    ted_spread_bps          DOUBLE PRECISION,
    libor_ois_bps           DOUBLE PRECISION,
    liquidity_score         DOUBLE PRECISION,

    -- FX
    dxy_index               DOUBLE PRECISION,
    eurusd                  DOUBLE PRECISION,
    usdjpy                  DOUBLE PRECISION,
    gbpusd                  DOUBLE PRECISION,
    dxy_1d_return           DOUBLE PRECISION,

    -- Commodities
    gold_spot               DOUBLE PRECISION,
    wti_crude               DOUBLE PRECISION,
    brent_crude             DOUBLE PRECISION,
    copper_spot             DOUBLE PRECISION,
    gold_1d_return          DOUBLE PRECISION,
    oil_1d_return           DOUBLE PRECISION,

    -- Breadth
    advance_decline_ratio   DOUBLE PRECISION,
    pct_above_200ma         DOUBLE PRECISION,
    pct_above_50ma          DOUBLE PRECISION,

    -- Quality flags
    data_quality            DOUBLE PRECISION    DEFAULT 1.0,
    has_critical_gap        BOOLEAN             DEFAULT FALSE,
    stale_fields            TEXT[]
);

SELECT create_hypertable('market_snapshots', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_ts
    ON market_snapshots (timestamp DESC);

-- Hourly OHLC materialized view for dashboard charting
CREATE MATERIALIZED VIEW IF NOT EXISTS market_snapshots_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp)    AS hour,
    first(spx_level, timestamp)         AS spx_open,
    max(spx_level)                      AS spx_high,
    min(spx_level)                      AS spx_low,
    last(spx_level, timestamp)          AS spx_close,
    avg(vix_spot)                       AS vix_avg,
    last(yield_10y, timestamp)          AS yield_10y_last,
    last(hy_spread_bps, timestamp)      AS hy_spread_last
FROM market_snapshots
GROUP BY hour
WITH NO DATA;

-- ============================================================
-- Risk Scores (time-series)
-- ============================================================
CREATE TABLE IF NOT EXISTS risk_scores (
    timestamp               TIMESTAMPTZ     NOT NULL,
    score_id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                UUID,
    generated_at            TIMESTAMPTZ     NOT NULL,

    composite_score         DOUBLE PRECISION NOT NULL,
    severity                TEXT            NOT NULL,
    regime                  TEXT            NOT NULL,
    action_level            TEXT            NOT NULL,
    regime_multiplier       DOUBLE PRECISION,
    gap_risk_multiplier     DOUBLE PRECISION,

    -- Sub-scores
    liquidity_score         DOUBLE PRECISION,
    volatility_score        DOUBLE PRECISION,
    rate_shock_score        DOUBLE PRECISION,
    equity_down_score       DOUBLE PRECISION,
    credit_spread_score     DOUBLE PRECISION,
    fx_risk_score           DOUBLE PRECISION,
    commodity_score         DOUBLE PRECISION,
    weekend_gap_score       DOUBLE PRECISION,
    policy_ambig_score      DOUBLE PRECISION,

    -- Metadata
    data_quality            DOUBLE PRECISION,
    score_reliability       TEXT,
    summary                 TEXT,
    primary_drivers         TEXT[]
);

SELECT create_hypertable('risk_scores', 'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_risk_scores_event
    ON risk_scores (event_id);
CREATE INDEX IF NOT EXISTS idx_risk_scores_severity
    ON risk_scores (severity, timestamp DESC);

-- ============================================================
-- Scenario Trees (time-series)
-- ============================================================
CREATE TABLE IF NOT EXISTS scenario_trees (
    timestamp               TIMESTAMPTZ     NOT NULL,
    tree_id                 UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                UUID,
    regime                  TEXT,
    n_scenarios             INT,
    expected_equity_pct     DOUBLE PRECISION,
    expected_yield_bps      DOUBLE PRECISION,
    expected_vix_change     DOUBLE PRECISION,
    tail_loss_5pct          DOUBLE PRECISION,
    tail_loss_1pct          DOUBLE PRECISION,
    monday_gap_estimate_pct DOUBLE PRECISION,
    monday_gap_confidence   DOUBLE PRECISION,
    scenarios_json          JSONB
);

SELECT create_hypertable('scenario_trees', 'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

-- ============================================================
-- Retention Policies (production: keep 5 years of market data)
-- ============================================================
-- Uncomment and adjust for production:
-- SELECT add_retention_policy('market_snapshots', INTERVAL '5 years');
-- SELECT add_retention_policy('risk_scores',      INTERVAL '7 years');

COMMENT ON TABLE market_snapshots IS
    'Time-series market data snapshots. Partitioned by day.';
COMMENT ON TABLE risk_scores IS
    'MSRE composite and sub-component risk scores. Partitioned weekly.';
COMMENT ON TABLE scenario_trees IS
    'Probability-weighted scenario tree outputs per event.';
