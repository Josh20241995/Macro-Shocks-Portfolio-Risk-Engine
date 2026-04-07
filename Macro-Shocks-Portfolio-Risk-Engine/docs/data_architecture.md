# Data Architecture

## Macro Shock Risk Engine — Data Pipeline and Schema Reference

---

## 1. Data Taxonomy

The MSRE consumes seven categories of data. Each category serves a distinct function in the risk assessment pipeline.

| Category | Role in MSRE | Latency Tolerance | Staleness Risk |
|----------|-------------|-------------------|----------------|
| Market Prices (Equity, Rates, Vol) | Pre-event state; vulnerability scoring | < 15 min | HIGH — stale vol/rates distort risk score |
| Credit Spreads | Credit risk sub-score; contagion signal | < 60 min | MEDIUM — credit updates less frequently |
| FX Rates | FX risk sub-score; safe-haven signals | < 15 min | HIGH — FX is 24h market |
| Commodities | Commodity shock sub-score; risk-off proxy | < 30 min | MEDIUM |
| News / Transcripts | NLP input; policy surprise vector | Near real-time | CRITICAL — delay means delayed scoring |
| Economic Calendar | Event scheduling; advance warning | Daily | LOW — calendar doesn't change intraday |
| Market Closure Data | Weekend gap corridor logic | Annual | LOW — holiday schedule is static |

---

## 2. Data Sources (Reference Architecture)

These are institutional-grade data sources. Free/alternative sources are noted where applicable.

### 2.1 Market Prices

**Primary:** Bloomberg B-PIPE (real-time streaming)  
**Secondary:** Refinitiv Elektron / LSEG Data Platform  
**Research fallback:** FRED (Federal Reserve Economic Data) for EOD yields  
**Free alternative:** Yahoo Finance (yfinance) — research only, not production

Key fields consumed:
```
SPX Index              → EquityMarketSnapshot.spx_level
NDX Index              → EquityMarketSnapshot.nasdaq_level
RTY Index              → EquityMarketSnapshot.russell_2000_level
VIX Index              → VolatilitySnapshot.vix_spot
VIX3M Index            → VolatilitySnapshot.vix_3m
VVIX Index             → VolatilitySnapshot.vvix
MOVE Index             → VolatilitySnapshot.move_index
GT2 Govt (2Y yield)    → YieldCurveSnapshot.y2
GT10 Govt (10Y yield)  → YieldCurveSnapshot.y10
GT30 Govt (30Y yield)  → YieldCurveSnapshot.y30
TIPSIY10 Index         → YieldCurveSnapshot.real_yield_10
USGGBE10 Index         → YieldCurveSnapshot.breakeven_10
DXY Curncy             → FXSnapshot.dxy_index
EURUSD Curncy          → FXSnapshot.eurusd
USDJPY Curncy          → FXSnapshot.usdjpy
CL1 Comdty (WTI)       → CommoditySnapshot.wti_crude
GC1 Comdty (Gold)      → CommoditySnapshot.gold_spot
HG1 Comdty (Copper)    → CommoditySnapshot.copper_spot
```

### 2.2 Credit Spreads

**Primary:** Markit iBoxx (IG/HY OAS), CDX indices  
**Secondary:** Bloomberg (LUACOAS, HUC0OAS)  
**Research fallback:** FRED (BAMLC0A0CM, BAMLH0A0HYM2)

```
CDX.NA.IG             → CreditMarketSnapshot.ig_spread_bps
CDX.NA.HY             → CreditMarketSnapshot.hy_spread_bps
EMBI+ Spread          → CreditMarketSnapshot.em_spread_bps
```

### 2.3 Liquidity Proxies

**Primary:** Bloomberg (bid-ask computed from Level 2 data)  
**Secondary:** SOFR/Fed Funds OIS spreads (FRED), TED spread (FRED)

```
USSO1Z BGN Curncy (OIS)  → LiquiditySnapshot.funding_spread_libor_ois
TED spread (TEDRATE)      → LiquiditySnapshot.ted_spread_bps
SRPSOFR Index             → LiquiditySnapshot.repo_rate_overnight
```

### 2.4 Market Breadth / Internals

**Primary:** Bloomberg (NYSE advance/decline, new highs/lows)  
**Secondary:** Barchart, computed from constituent data  

```
NYADV / NYDEC          → MarketBreadthSnapshot.advance_decline_ratio
NYHL                   → MarketBreadthSnapshot.new_highs_lows_ratio
SPX members % > 200MA  → MarketBreadthSnapshot.pct_above_200ma (computed)
```

### 2.5 News and Transcripts

**Primary:** Bloomberg News (BN <GO>), Reuters News  
**Secondary:** Federal Reserve website (federalreserve.gov/newsevents)  
**Supplemental:** EDGAR (SEC filings), Congressional hearing transcripts  

Processing pipeline:
```
Raw headline/transcript
        ↓
Text preprocessing (lowercase, remove markup, segment by speaker)
        ↓
Section identification (prepared remarks vs. Q&A)
        ↓
NLP scoring (lexicon + optional transformer)
        ↓
PolicySurpriseVector
```

### 2.6 Economic Calendar

**Primary:** Bloomberg ECAL (Economic Calendar function)  
**Secondary:** Investing.com calendar API  
**FOMC schedule:** Official Fed calendar (federalreserve.gov/monetarypolicy/fomccalendars)

Ingested fields: event_name, release_date, release_time, consensus_estimate, actual_value, prior_value

### 2.7 Market Closure and Holiday Data

**Source:** NYSE official holiday calendar (updated annually in January)  
**Storage:** Hardcoded in `MarketCalendar._default_us_holidays()` with annual review  
**Override:** JSON file at `configs/holidays.json`

---

## 3. Data Validation Rules

Every field has explicit validation before it enters the pipeline.

### 3.1 Bounds Checking

| Field | Valid Range | On Violation |
|-------|------------|--------------|
| VIX | [5, 100] | Flag stale, use last known valid |
| HY Spread | [100, 3000] bps | Flag, use last valid |
| IG Spread | [20, 800] bps | Flag, use last valid |
| Yield (any) | [-2.0, 20.0] % | Flag stale |
| SPX | [500, 15000] | Flag stale |
| DXY | [60, 160] | Flag stale |
| Put/Call Ratio | [0.2, 3.0] | Flag stale |
| Advance/Decline | [0.0, 1.0] | Flag stale |

### 3.2 Staleness Thresholds

```python
MAX_STALENESS = {
    "equity":     timedelta(minutes=15),
    "yields":     timedelta(minutes=30),
    "credit":     timedelta(minutes=60),
    "volatility": timedelta(minutes=30),
    "fx":         timedelta(minutes=15),
    "commodities":timedelta(minutes=30),
    "breadth":    timedelta(minutes=60),   # EOD data acceptable
    "liquidity":  timedelta(minutes=45),
}
```

When a data point exceeds its staleness threshold:
1. The field is marked `stale=True` in its snapshot object
2. The last known valid value is retained (not set to None)
3. The overall `data_completeness` score is reduced
4. A warning is added to `PipelineRunContext.warnings`
5. The risk score `reliability` is downgraded if > 2 fields are stale

### 3.3 Cross-Validation Checks

- **Yield curve arbitrage**: If y2 > y10 by more than 300bps, flag as possible data error
- **VIX/SPX consistency**: If VIX drops > 10 points with SPX up < 1%, flag for review
- **Credit/equity divergence**: If HY spreads tight 200bps while SPX falls > 5%, flag
- **FX cross-rate**: EUR/USD × USD/JPY should approximately equal EUR/JPY; discrepancy > 2% flagged

---

## 4. Time Alignment Policy

All data alignment in MSRE follows strict UTC-based rules.

### 4.1 Canonical Timestamp Format

All timestamps stored and exchanged as:
- UTC-aware `datetime` objects in Python
- ISO 8601 with timezone offset in JSON/API
- UTC timestamp in database columns

**No naive datetimes anywhere in the system.** All display conversion to ET is done at the presentation layer (dashboard, reports).

### 4.2 Pre-Event Snapshot Construction

The pre-event market state is constructed by:
1. Taking the latest clean bar for each data type where `bar_timestamp <= event_timestamp`
2. Applying staleness checks to each field
3. Computing data_completeness as fraction of expected fields populated
4. Flagging the snapshot if data_completeness < 0.5 or critical fields (yields, vol) are missing

```
event_timestamp = T

Pre-event state uses:
  equity:     max bar where bar_time <= T - 0min (most recent before event)
  yields:     max bar where bar_time <= T - 0min
  vol:        max bar where bar_time <= T - 0min
  credit:     max bar where bar_time <= T - 60min  (less frequent updates)
  breadth:    max bar where bar_time <= T - 240min (EOD is acceptable)
```

### 4.3 Holiday and Market Closure Alignment

- All session state calculations use the `MarketCalendar` class
- ET (America/New_York) is used for all US market session logic
- The calendar handles DST transitions automatically via `zoneinfo`
- Early close days (e.g., Christmas Eve, Black Friday) are explicitly enumerated

---

## 5. Data Storage Schema

### 5.1 TimescaleDB — Market Data

```sql
-- market_snapshots hypertable (partitioned by time)
CREATE TABLE market_snapshots (
    timestamp           TIMESTAMPTZ NOT NULL,
    snapshot_type       TEXT NOT NULL,       -- 'equity', 'yields', 'vol', etc.
    source              TEXT,
    spx_level           DOUBLE PRECISION,
    spx_1d_return       DOUBLE PRECISION,
    spx_from_52w_high   DOUBLE PRECISION,
    vix_spot            DOUBLE PRECISION,
    vix_3m              DOUBLE PRECISION,
    yield_2y            DOUBLE PRECISION,
    yield_10y           DOUBLE PRECISION,
    yield_30y           DOUBLE PRECISION,
    slope_2_10_bps      DOUBLE PRECISION,
    hy_spread_bps       DOUBLE PRECISION,
    ig_spread_bps       DOUBLE PRECISION,
    dxy_index           DOUBLE PRECISION,
    eurusd              DOUBLE PRECISION,
    gold_spot           DOUBLE PRECISION,
    wti_crude           DOUBLE PRECISION,
    bid_ask_spx_bps     DOUBLE PRECISION,
    ted_spread_bps      DOUBLE PRECISION,
    advance_decline_ratio DOUBLE PRECISION,
    data_quality        DOUBLE PRECISION DEFAULT 1.0,
    stale               BOOLEAN DEFAULT FALSE
);

SELECT create_hypertable('market_snapshots', 'timestamp',
    chunk_time_interval => INTERVAL '1 day');

CREATE INDEX ON market_snapshots (timestamp DESC, snapshot_type);

-- Continuous aggregate: hourly OHLC for dashboard charts
CREATE MATERIALIZED VIEW market_snapshots_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS hour,
    snapshot_type,
    first(spx_level, timestamp) AS spx_open,
    max(spx_level) AS spx_high,
    min(spx_level) AS spx_low,
    last(spx_level, timestamp) AS spx_close,
    avg(vix_spot) AS vix_avg,
    last(yield_10y, timestamp) AS yield_10y_last
FROM market_snapshots
GROUP BY hour, snapshot_type;
```

### 5.2 TimescaleDB — Risk Scores

```sql
CREATE TABLE risk_scores (
    timestamp           TIMESTAMPTZ NOT NULL,
    score_id            UUID PRIMARY KEY,
    event_id            UUID,
    composite_score     DOUBLE PRECISION NOT NULL,
    severity            TEXT NOT NULL,
    regime              TEXT NOT NULL,
    action_level        TEXT NOT NULL,
    regime_multiplier   DOUBLE PRECISION,
    gap_risk_multiplier DOUBLE PRECISION,
    -- Sub-scores
    liquidity_score     DOUBLE PRECISION,
    volatility_score    DOUBLE PRECISION,
    rate_shock_score    DOUBLE PRECISION,
    equity_down_score   DOUBLE PRECISION,
    credit_spread_score DOUBLE PRECISION,
    fx_risk_score       DOUBLE PRECISION,
    commodity_score     DOUBLE PRECISION,
    weekend_gap_score   DOUBLE PRECISION,
    policy_ambig_score  DOUBLE PRECISION,
    -- Metadata
    data_quality        DOUBLE PRECISION,
    score_reliability   TEXT,
    summary             TEXT
);

SELECT create_hypertable('risk_scores', 'timestamp',
    chunk_time_interval => INTERVAL '7 days');
```

### 5.3 PostgreSQL — Event Catalog

```sql
CREATE TABLE macro_events (
    event_id            UUID PRIMARY KEY,
    detected_at         TIMESTAMPTZ NOT NULL,
    event_timestamp     TIMESTAMPTZ NOT NULL,
    event_type          TEXT NOT NULL,
    severity            TEXT NOT NULL,
    severity_score      DOUBLE PRECISION,
    institution         TEXT NOT NULL,
    speaker             TEXT,
    speaker_role        TEXT,
    title               TEXT NOT NULL,
    is_scheduled        BOOLEAN DEFAULT TRUE,
    is_weekend          BOOLEAN DEFAULT FALSE,
    full_weekend_gap    BOOLEAN DEFAULT FALSE,
    hours_until_open    DOUBLE PRECISION,
    minutes_since_close DOUBLE PRECISION,
    raw_text            TEXT,
    headline_summary    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ON macro_events (event_timestamp DESC);
CREATE INDEX ON macro_events (institution, event_type);
```

### 5.4 PostgreSQL — Alert History

```sql
CREATE TABLE alert_history (
    alert_id                UUID PRIMARY KEY,
    event_id                UUID REFERENCES macro_events(event_id),
    score_id                UUID,
    generated_at            TIMESTAMPTZ NOT NULL,
    level                   TEXT NOT NULL,
    title                   TEXT NOT NULL,
    message                 TEXT,
    composite_score         DOUBLE PRECISION,
    triggered_thresholds    TEXT[],
    routing_targets         TEXT[],
    requires_acknowledgment BOOLEAN DEFAULT FALSE,
    acknowledged            BOOLEAN DEFAULT FALSE,
    acknowledged_by         TEXT,
    acknowledged_at         TIMESTAMPTZ
);

CREATE INDEX ON alert_history (generated_at DESC, level);
```

---

## 6. Missing Data Handling

### 6.1 Decision Tree

```
Data field requested
        │
        ├── Data available and within staleness limit?
        │   YES → Use data as-is
        │
        ├── Data available but stale (exceeds staleness limit)?
        │   → Use data with stale=True flag
        │   → Add warning to pipeline context
        │   → Reduce data_completeness score
        │
        ├── Data not available at all?
        │   → Set field to None
        │   → Reduce data_completeness score
        │   → If critical field (yield_10y, vix_spot): set has_critical_data_gap=True
        │
        └── has_critical_data_gap=True?
            → score_reliability = "LOW"
            → Include explicit warning in risk score summary
            → Do NOT suppress scoring — generate advisory score with caveats
```

### 6.2 Imputation Strategy

**We do NOT impute missing values in production.** Missing data is represented as `None` with explicit flags. This prevents silent errors from corrupting risk scores.

The only exception is in the vulnerability scorer's composite calculation, where missing components are excluded and the remaining weights are renormalized. This is clearly documented in `MarketVulnerabilityScorer.score()`.

---

## 7. Data Reproducibility

Every risk score output includes:
- `score_id`: UUID for the specific computation
- `generated_at`: UTC timestamp of computation
- `event_id`: Links to the triggering event record
- `overall_data_quality`: Fraction of expected data populated
- `score_reliability`: HIGH/MEDIUM/LOW based on data completeness

Any score can be reproduced by:
1. Fetching the `event_id` record from `macro_events`
2. Querying `market_snapshots` for the closest bar before `event_timestamp`
3. Re-running the pipeline with `environment=research` and that market state

This reproducibility chain is tested in the integration test suite.
