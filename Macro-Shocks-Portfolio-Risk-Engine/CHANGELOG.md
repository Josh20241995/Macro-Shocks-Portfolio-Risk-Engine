# Changelog

All notable changes to the Macro Shock Risk Engine are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — Initial Production Release

### Added

**Core Risk Engine**
- Composite macro shock risk score [0-100] with 9 sub-components
- Regime-conditioned weights (4 regimes: expansion, fragile, risk-off, crisis)
- Weekend gap corridor multiplier [1.0–1.5× based on hours to next open]
- Regime multiplier [1.0–2.0×]
- Full explainability: every score has a primary driver and contributing factors list
- Severity classification: INFORMATIONAL / LOW / MEDIUM / HIGH / CRITICAL
- Action level mapping: NO_ACTION / MONITOR / REDUCE / HEDGE / EMERGENCY_DERISKING

**Event Detection and Classification**
- Multi-institution support: Fed, Treasury, White House, ECB, BOJ, BIS, IMF
- Automatic detection of emergency trigger phrases (35+ phrases)
- Weekend gap corridor detection with full timing context
- Severity scoring with institution weight × speaker seniority × event type × timing
- Market session state classification: OPEN / PRE_MARKET / AFTER_HOURS / CLOSED_WEEKEND / CLOSED_HOLIDAY

**NLP / Language Intelligence**
- Hawkish/dovish lexicon scorer: 80+ calibrated phrases
- Transformer embedding scorer (optional, sentence-transformers)
- 75%/25% lexicon/transformer ensemble
- Policy surprise vector: 7 dimensions (rate path, inflation, growth, balance sheet, financial stability, forward guidance, urgency)
- Crisis language detection (25+ crisis phrases)
- Policy reversal and forward guidance change detection

**Market Context Engine**
- Percentile-based vulnerability scoring for 7 market components
- Calibration knots for VIX, HY spreads, IG spreads, bid-ask, TED spread
- Amplification factor [1.0–2.0×] applied to scenario impacts
- Regime classification from vulnerability composite

**Scenario Engine**
- 8 named scenarios from "Benign / In-Line" to "Extraordinary Market Intervention"
- Empirically-calibrated prior probabilities (2010-2024 FOMC events)
- 3-step posterior update: surprise direction → regime → gap corridor amplification
- Probability-weighted expected equity, yield, VIX impacts
- 5th and 1st percentile tail loss estimates
- Monday gap estimate with confidence score for weekend events

**Portfolio Impact Engine**
- Asset-class-specific guidance: equity, fixed income, rates, FX, commodities, credit, volatility
- Sized hedge recommendations with urgency and PM approval flags
- Kill switch logic (score ≥ 90)
- Gross and net exposure reduction guidance
- Monday gap pre-positioning note for weekend events

**Backtesting Framework**
- Historical event study with walk-forward validation
- TimestampGuard enforcing look-ahead bias prevention at data access layer
- Transaction cost model with liquidity stress slippage scaling
- Strategy P&L estimation for hedge vs. unhedged comparison
- Risk metrics: Expected Shortfall, Max Drawdown, Gap Estimate Error, Precision@CRITICAL, Recall@CRITICAL

**Data Infrastructure**
- MarketStateSnapshot with 50+ fields across 8 market components
- Staleness checking and data quality scoring
- SyntheticFeedProvider for research and testing
- FREDFeedProvider for free yield data
- BloombergFeedProvider stub (requires blpapi license)
- CachedFeedProvider (Redis wrapper for any provider)
- TimescaleDB hypertable schema for market data and risk scores
- PostgreSQL schema for events, alerts, orders, model versions, calendar

**Monitoring and Alerting**
- Configurable threshold alerts (CRITICAL/HIGH/MEDIUM/LOW) for composite score, sub-scores, Monday gap, trading halt probability
- Alert routing: Slack, PagerDuty, OMS, log
- Append-only audit trail (JSONL + optional PostgreSQL)
- Heartbeat dead-man monitor
- Alert acknowledgment tracking with named attribution

**Execution / OMS Interface**
- Pre-trade risk check framework (5 checks per order)
- Order status lifecycle: PENDING_APPROVAL → APPROVED → SUBMITTED
- Kill switch review procedure (advisory only — no automatic execution)
- Post-trade attribution hooks
- Research mode skips OMS (log only)

**Infrastructure**
- FastAPI REST server with 6 endpoints
- C# WPF operational dashboard (MVVM, dark theme, live data binding)
- C++ fast risk scorer (sub-millisecond, mirrors Python scorer exactly)
- pybind11 Python bindings for C++ scorer
- GitHub Actions CI: lint → typecheck → unit tests → integration → C++ → E2E → Docker
- Docker multi-stage build (non-root, health checks)
- Zero-downtime production deployment script with auto-rollback
- Database migration manager
- Health check and smoke test scripts
- CLI entry point (`python -m macro_shock`)

**Testing**
- 120+ unit tests across 6 test modules
- 18 integration tests covering full pipeline
- 8 C++ unit tests with Catch2
- 14 C# unit tests with xUnit
- Synthetic data generator for research and CI

**Documentation**
- README (institutional-grade, with architecture diagrams and quick start)
- Architecture (`docs/architecture.md`)
- Data Architecture (`docs/data_architecture.md`)
- Model Architecture with full formulas (`docs/model_architecture.md`)
- Deployment guide with checklist (`docs/deployment.md`)
- Model Governance policy (`docs/governance.md`)
- Operational Runbook (`docs/runbook.md`)
- Product Roadmap (`docs/roadmap.md`)

---

## Planned — [1.1.0]

- FinBERT fine-tuning on FOMC transcript corpus
- HMM-based regime classifier
- Intraday re-scoring (15-min intervals post-event)
- Score confidence intervals
- ECB / BOJ / BOE support

See `docs/roadmap.md` for full details.
