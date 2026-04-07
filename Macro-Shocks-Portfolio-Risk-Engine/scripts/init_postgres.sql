-- scripts/init_postgres.sql
-- PostgreSQL relational metadata schema for the Macro Shock Risk Engine.
-- Applied automatically on first container start.

-- ============================================================
-- Macro Events Catalog
-- ============================================================
CREATE TABLE IF NOT EXISTS macro_events (
    event_id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    detected_at             TIMESTAMPTZ     NOT NULL,
    event_timestamp         TIMESTAMPTZ     NOT NULL,
    event_type              TEXT            NOT NULL,
    severity                TEXT            NOT NULL,
    severity_score          DOUBLE PRECISION,
    institution             TEXT            NOT NULL,
    speaker                 TEXT,
    speaker_role            TEXT,
    title                   TEXT            NOT NULL,
    description             TEXT,
    source_url              TEXT,
    is_scheduled            BOOLEAN         DEFAULT TRUE,
    is_weekend              BOOLEAN         DEFAULT FALSE,
    is_after_hours          BOOLEAN         DEFAULT FALSE,
    full_weekend_gap        BOOLEAN         DEFAULT FALSE,
    market_session          TEXT,
    hours_until_open        DOUBLE PRECISION,
    minutes_since_close     DOUBLE PRECISION,
    headline_summary        TEXT,
    raw_text                TEXT,
    metadata_json           JSONB,
    created_at              TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp
    ON macro_events (event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_institution
    ON macro_events (institution, event_type);
CREATE INDEX IF NOT EXISTS idx_events_weekend
    ON macro_events (full_weekend_gap) WHERE full_weekend_gap = TRUE;

-- ============================================================
-- Alert History
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_history (
    alert_id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                UUID            REFERENCES macro_events(event_id) ON DELETE SET NULL,
    score_id                UUID,
    generated_at            TIMESTAMPTZ     NOT NULL,
    level                   TEXT            NOT NULL,
    title                   TEXT            NOT NULL,
    message                 TEXT,
    composite_score         DOUBLE PRECISION,
    triggered_thresholds    TEXT[],
    routing_targets         TEXT[],
    requires_acknowledgment BOOLEAN         DEFAULT FALSE,
    acknowledged            BOOLEAN         DEFAULT FALSE,
    acknowledged_by         TEXT,
    acknowledged_at         TIMESTAMPTZ,
    created_at              TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_generated
    ON alert_history (generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_level
    ON alert_history (level, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_unacked
    ON alert_history (acknowledged, level)
    WHERE acknowledged = FALSE AND level = 'CRITICAL';

-- ============================================================
-- OMS Order Audit Trail
-- ============================================================
CREATE TABLE IF NOT EXISTS order_audit (
    order_id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                UUID,
    risk_score_id           UUID,
    asset_class             TEXT,
    instrument              TEXT,
    action                  TEXT,
    urgency                 TEXT,
    sizing_guidance         TEXT,
    rationale               TEXT,
    estimated_cost_bps      DOUBLE PRECISION,
    status                  TEXT            NOT NULL DEFAULT 'PENDING_APPROVAL',
    authorized_by           TEXT,
    authorized_at           TIMESTAMPTZ,
    submitted_at            TIMESTAMPTZ,
    failure_reason          TEXT,
    pre_trade_result        JSONB,
    created_at              TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_status
    ON order_audit (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_event
    ON order_audit (event_id);

-- ============================================================
-- Model Version Registry
-- ============================================================
CREATE TABLE IF NOT EXISTS model_versions (
    version_id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id                TEXT            NOT NULL,     -- e.g. 'MSRE-NLP-001'
    version                 TEXT            NOT NULL,
    description             TEXT,
    environment             TEXT            NOT NULL DEFAULT 'research',
    is_active               BOOLEAN         DEFAULT FALSE,
    deployed_at             TIMESTAMPTZ,
    deployed_by             TEXT,
    calibration_date        DATE,
    calibration_data_range  TEXT,
    out_of_sample_accuracy  DOUBLE PRECISION,
    precision_at_critical   DOUBLE PRECISION,
    recall_at_critical      DOUBLE PRECISION,
    notes                   TEXT,
    config_json             JSONB,
    created_at              TIMESTAMPTZ     DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_model_active
    ON model_versions (model_id, environment)
    WHERE is_active = TRUE;

-- ============================================================
-- Backtest Event Archive (historical event records)
-- ============================================================
CREATE TABLE IF NOT EXISTS backtest_events (
    event_id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    event_date              TIMESTAMPTZ     NOT NULL,
    event_type              TEXT            NOT NULL,
    is_weekend              BOOLEAN         DEFAULT FALSE,
    institution             TEXT            NOT NULL,
    speaker                 TEXT,
    description             TEXT,
    actual_policy_stance    TEXT,

    -- Realized outcomes (populated post-event)
    realized_spx_return     DOUBLE PRECISION,
    realized_10y_yield_chg  DOUBLE PRECISION,
    realized_vix_change     DOUBLE PRECISION,
    realized_hy_spread_chg  DOUBLE PRECISION,
    trading_halt_occurred   BOOLEAN         DEFAULT FALSE,
    emergency_action_followed BOOLEAN       DEFAULT FALSE,

    data_validated          BOOLEAN         DEFAULT FALSE,
    data_source             TEXT,
    created_at              TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_date
    ON backtest_events (event_date DESC);

-- ============================================================
-- Market Calendar (holiday/early close schedule)
-- ============================================================
CREATE TABLE IF NOT EXISTS market_calendar (
    calendar_id             UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    calendar_date           DATE            NOT NULL UNIQUE,
    exchange                TEXT            NOT NULL DEFAULT 'NYSE',
    is_holiday              BOOLEAN         DEFAULT FALSE,
    is_early_close          BOOLEAN         DEFAULT FALSE,
    early_close_time        TIME,
    holiday_name            TEXT,
    notes                   TEXT,
    created_at              TIMESTAMPTZ     DEFAULT NOW()
);

-- Insert 2024-2026 US NYSE holidays
INSERT INTO market_calendar (calendar_date, is_holiday, holiday_name) VALUES
    ('2024-01-01', TRUE, 'New Year Day'),
    ('2024-01-15', TRUE, 'MLK Day'),
    ('2024-02-19', TRUE, 'Presidents Day'),
    ('2024-03-29', TRUE, 'Good Friday'),
    ('2024-05-27', TRUE, 'Memorial Day'),
    ('2024-06-19', TRUE, 'Juneteenth'),
    ('2024-07-04', TRUE, 'Independence Day'),
    ('2024-09-02', TRUE, 'Labor Day'),
    ('2024-11-28', TRUE, 'Thanksgiving'),
    ('2024-12-25', TRUE, 'Christmas'),
    ('2025-01-01', TRUE, 'New Year Day'),
    ('2025-01-20', TRUE, 'MLK Day'),
    ('2025-02-17', TRUE, 'Presidents Day'),
    ('2025-04-18', TRUE, 'Good Friday'),
    ('2025-05-26', TRUE, 'Memorial Day'),
    ('2025-06-19', TRUE, 'Juneteenth'),
    ('2025-07-04', TRUE, 'Independence Day'),
    ('2025-09-01', TRUE, 'Labor Day'),
    ('2025-11-27', TRUE, 'Thanksgiving'),
    ('2025-12-25', TRUE, 'Christmas'),
    ('2026-01-01', TRUE, 'New Year Day'),
    ('2026-01-19', TRUE, 'MLK Day'),
    ('2026-02-16', TRUE, 'Presidents Day'),
    ('2026-04-03', TRUE, 'Good Friday'),
    ('2026-05-25', TRUE, 'Memorial Day'),
    ('2026-06-19', TRUE, 'Juneteenth'),
    ('2026-07-03', TRUE, 'Independence Day'),
    ('2026-09-07', TRUE, 'Labor Day'),
    ('2026-11-26', TRUE, 'Thanksgiving'),
    ('2026-12-25', TRUE, 'Christmas')
ON CONFLICT (calendar_date) DO NOTHING;

-- Early closes (1 PM ET)
INSERT INTO market_calendar (calendar_date, is_early_close, early_close_time, holiday_name) VALUES
    ('2024-11-29', TRUE, '13:00', 'Black Friday'),
    ('2024-12-24', TRUE, '13:00', 'Christmas Eve'),
    ('2025-11-28', TRUE, '13:00', 'Black Friday'),
    ('2025-12-24', TRUE, '13:00', 'Christmas Eve')
ON CONFLICT (calendar_date) DO NOTHING;

COMMENT ON TABLE macro_events     IS 'All detected and classified macro events.';
COMMENT ON TABLE alert_history    IS 'Complete audit trail of all emitted risk alerts.';
COMMENT ON TABLE order_audit      IS 'OMS order audit trail — append only.';
COMMENT ON TABLE model_versions   IS 'Model version registry and calibration history.';
COMMENT ON TABLE backtest_events  IS 'Historical events archive for backtesting.';
COMMENT ON TABLE market_calendar  IS 'NYSE holiday and early-close schedule.';
