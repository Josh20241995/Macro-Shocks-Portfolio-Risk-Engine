# Macro Shock Risk Engine
### Asymmetric Policy Event Detection, Pricing, and Portfolio Response System

> **Classification:** Institutional Research & Production Infrastructure  
> **Language Stack:** Python 3.11 · C++17 · C# 10 (.NET 6)  
> **Maintained by:** Quantitative Research & Risk Engineering  

---

## What This System Does

The **Macro Shock Risk Engine (MSRE)** is an institutional-grade, cross-asset risk framework purpose-built to detect, price, and respond to asymmetric macro shock events — specifically those triggered by after-hours Federal Reserve communications, weekend emergency policy actions, surprise government statements, and related low-frequency, high-impact macro dislocations.

Unlike conventional intraday risk systems, the MSRE treats these events as **regime-changing tail catalysts**, not ordinary news flow. It is designed to answer three operational questions in near-real-time:

1. **How severe is this event?** → Composite risk score decomposed across liquidity, volatility, rates, equity, credit, FX, and policy dimensions.
2. **What will markets do?** → Probability-weighted scenario tree covering mild repricing through disorderly deleveraging.
3. **What should the portfolio do?** → Explicit, asset-class-specific hedging, exposure reduction, and execution guidance.

The engine is especially engineered for the **Friday-after-4pm / Saturday-Sunday / Monday-open** risk corridor, where market closure amplifies shock magnitude and first-price-discovery is deferred to futures opens or the Monday cash session.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MSRE SYSTEM ARCHITECTURE                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  DATA LAYER              INTELLIGENCE LAYER         OUTPUT LAYER        │
│  ──────────              ────────────────           ────────────        │
│  Market Prices    →      Event Detection     →      Risk Score          │
│  Yield Curves     →      NLP / Policy Parse  →      Scenario Tree       │
│  Vol Surfaces     →      Market Context      →      Portfolio Guidance  │
│  News/Transcripts →      Shock Propagation   →      Execution Flags     │
│  Economic Cal     →      Risk Scoring        →      Alerts              │
│  Futures/Options  →      Portfolio Impact    →      Audit Trail         │
│                                                                         │
│  PERFORMANCE LAYER       OPERATIONAL LAYER          UI LAYER            │
│  ─────────────────       ─────────────────          ────────            │
│  C++ Fast Scorer         Monitoring/Alerts           C# Dashboard       │
│  C++ Signal Eval         Kill Switch / OMS           Risk Heatmaps      │
│  C++ Math Utils          Pre/Post Trade Checks       Scenario Views     │
│                          Structured Logging          Event Timeline     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Module | Language | Responsibility |
|--------|----------|----------------|
| Event Detection & Classification | Python | Detect, classify, and score macro events by type, severity, and timing |
| NLP / Language Intelligence | Python | Parse policy language; generate hawkish/dovish vector, surprise score |
| Market Context Engine | Python | Ingest and normalize pre-event market state across all asset classes |
| Shock Propagation / Scenario Engine | Python | Scenario tree construction, probability weighting, regime-conditioned impact |
| Risk Scoring Engine | Python + C++ | Composite and sub-component risk scores with full explainability |
| Portfolio Impact Engine | Python | Asset-class-specific hedge and exposure recommendations |
| Backtesting & Simulation | Python | Historical event study, walk-forward validation, gap risk simulation |
| Monitoring & Alerting | Python | Threshold-based alerts, structured logging, audit trails |
| Execution / OMS Interface | Python | Pre-trade checks, kill switch, downstream system integration |
| Fast Scorer | C++ | Sub-millisecond signal evaluation for streaming event processing |
| Dashboard | C# WPF | Analyst and PM operational interface with live risk visualization |

---

## Module Descriptions

### A. Event Detection and Classification (`/python/src/macro_shock/event_detection/`)
Monitors structured event calendars (FRED, Bloomberg ECAL, custom feeds) and unstructured news. Detects scheduled and unscheduled Fed/government communications. Classifies events by type (scheduled post-close, unscheduled emergency, weekend action, geopolitical surprise). Assigns initial severity scores based on institution, speaker seniority, event recency, and timing relative to market hours. Special weekend-gap logic flags Friday-after-4pm events as maximum-gap-risk class.

### B. NLP / Language Intelligence (`/python/src/macro_shock/nlp/`)
Ingests transcript text, prepared remarks, and Q&A segments. Runs a two-stage pipeline: (1) rule-based hawkish/dovish lexicon scoring for interpretability and speed, (2) transformer embedding for semantic similarity to historical crisis/surprise events. Produces a structured **Policy Surprise Vector** with dimensions for rate path, inflation concern, financial stability, urgency, and policy reversal probability. All scores carry confidence intervals and interpretable justifications.

### C. Market Context Engine (`/python/src/macro_shock/market_context/`)
Normalizes pre-event cross-asset market state. Ingests equity indices, yields, curve slopes, credit spreads, VIX term structure, FX, commodities, breadth, options skew, realized-vs-implied vol spread, and liquidity proxies. Detects pre-existing vulnerability (e.g., elevated VIX, inverted curve, credit stress, thin liquidity) which amplifies shock impact. Produces a **Market Vulnerability Score** that scales expected impact.

### D. Shock Propagation / Scenario Engine (`/python/src/macro_shock/scenario_engine/`)
Builds a calibrated probability-weighted scenario tree from the event and market context inputs. Scenarios span mild surprise through emergency market intervention. Each branch carries probability, expected asset-class impact (in return standard deviations), time horizon, and liquidity assumptions. Regime classifier determines whether the current environment resembles a risk-on expansion, fragile risk-on, risk-off correction, or crisis regime — which conditions the scenario weights.

### E. Risk Scoring Engine (`/python/src/macro_shock/risk_scoring/`)
Produces a **Composite Macro Shock Risk Score** (0–100) decomposed into nine sub-scores. Each sub-score is bounded, normalized, and explained with contributing factors. The composite uses regime-conditioned weights — in crisis regimes, liquidity and rate shock weights increase; in normal regimes, policy ambiguity and equity downside dominate. The C++ fast scorer component mirrors the Python scoring logic at sub-millisecond latency for streaming use cases.

### F. Portfolio Impact Engine (`/python/src/macro_shock/portfolio_impact/`)
Translates risk scores and scenario outputs into portfolio-level recommendations. Handles equity books (beta hedge, reduce gross, tail protection via puts/collars), fixed income books (duration reduction, curve trades, credit spread hedges), and macro books (FX hedges, commodity overlays, vol position adjustments). Outputs are structured to interface with OMS/EMS systems. Supports override flags for PM discretion.

### G. Backtesting and Simulation (`/python/src/macro_shock/backtesting/`)
Historical event study framework covering prior FOMC press conferences, emergency Fed actions, major government communications, and geopolitical shocks. Supports pre/post event windows, overnight/weekend gap simulation, regime segmentation, slippage and liquidity stress assumptions, and walk-forward validation. Key metrics: Expected Shortfall, Max Drawdown, Gap Risk, Tail Loss, Vol-of-Vol, Correlation Breakdown Risk, Exposure-at-Risk. Explicit look-ahead-bias prevention via timestamp-strict data alignment.

### H. Monitoring and Alerting (`/python/src/macro_shock/monitoring/`)
Config-driven threshold alerting with four severity levels (CRITICAL, HIGH, MEDIUM, LOW). Structured JSON logging with full audit trail. Alert routing to downstream systems (Slack, PagerDuty, OMS). Exception handling and dead-man switch for missed heartbeats.

### I. Execution / Operational Layer (`/python/src/macro_shock/execution/`)
OMS/EMS interface layer with pre-trade risk checks, post-trade attribution hooks, kill switch logic, and human override support. Never fully automated — all recommendations require explicit approval except emergency de-risking below configured thresholds.

---

## Critical Design: The Weekend Gap Corridor

The system treats the following as a **Special Event Class** requiring dedicated logic:

```
Event occurs: Friday after 4:00 PM ET
↓
Equity cash markets: CLOSED
Options markets: CLOSED  
Credit markets: CLOSED (mostly)
↓
Limited price discovery via:
  - Equity index futures (CME Globex, limited liquidity)
  - FX spot markets (24h but thin weekend)
  - Crypto markets (continuous)
  - Treasury futures (limited)
↓
Monday 9:30 AM ET: First full-market price discovery
  → Potential for violent gap open
  → High probability of circuit breaker conditions
  → Forced deleveraging from margin calls
  → Correlated liquidation across asset classes
```

The weekend gap risk subsystem explicitly models:
- Hours since last cash market close
- Whether futures markets have already incorporated the shock
- Estimated gap magnitude from scenario-weighted impact
- Probability of trading halt at open (based on futures pre-open levels)
- Liquidity impairment at first tradable session

---

## Data Architecture

### Required Data Feeds

| Data Type | Update Freq | Source (Reference) | Validation | Storage |
|-----------|-------------|-------------------|------------|---------|
| Equity Index Levels | Real-time / EOD | Bloomberg, Refinitiv | Stale check < 15min | TimescaleDB |
| Treasury Yields (2y/5y/10y/30y) | Real-time / EOD | FRED, Bloomberg | Bounds check, stale | TimescaleDB |
| Yield Curve Slopes | Derived | Computed | Range validation | TimescaleDB |
| Credit Spreads (IG/HY/CDS) | EOD / intraday | Bloomberg, Markit | Stale, bounds | TimescaleDB |
| VIX / Vol Surface | Real-time | CBOE, Bloomberg | Missing imputation | TimescaleDB |
| FX Rates (DXY, EURUSD, USDJPY) | Real-time | Bloomberg, Reuters | Cross-rate consistency | TimescaleDB |
| Commodities (Gold, Oil, Copper) | Real-time | CME, Bloomberg | Range, stale | TimescaleDB |
| Futures Positioning | Daily (COT) | CFTC | Weekly lag acknowledged | PostgreSQL |
| Options Skew / Term Structure | EOD | CBOE, Bloomberg | Surface arbitrage checks | TimescaleDB |
| News Headlines | Real-time | Bloomberg News, Reuters | De-dup, relevance filter | Elasticsearch |
| Fed Transcripts | Event-driven | Fed.gov, scraped | Manual audit flag | S3 + PostgreSQL |
| Economic Calendar | Daily | Bloomberg ECAL, FRED | Pre-event validation | PostgreSQL |
| Market Closure Schedule | Annual | Exchange calendars | Annual review | PostgreSQL |
| Breadth / Internals | EOD / 15min | Bloomberg, exchanges | Count validation | TimescaleDB |

### Time Alignment Policy

All data is aligned to **UTC timestamps** with explicit timezone metadata. Pre-event market state snapshots are taken at the closest clean bar prior to the event timestamp with the following staleness thresholds:
- Equity / Futures: 15 minutes maximum staleness  
- Yields: 30 minutes maximum staleness  
- Credit: 60 minutes maximum staleness (lower liquidity)  
- Vol: 30 minutes maximum staleness  

Any data exceeding staleness thresholds is flagged and the system defaults to last-known-valid with an explicit impairment flag in the risk output.

---

## Model Architecture

The MSRE uses a **five-layer modeling hierarchy**:

```
Layer 1: Deterministic Rules
   Event classification, market closure detection, weekend gap logic
   → No estimation uncertainty, high reliability

Layer 2: Statistical Impact Models  
   Regression-based asset class impact estimation conditioned on historical analogs
   → Calibrated uncertainty bounds, regime-conditioned

Layer 3: NLP / Language Models
   Hawkish/Dovish scoring, policy surprise vector, semantic similarity
   → Two-stage: rule lexicon (fast) + transformer embeddings (richer)

Layer 4: Scenario Analysis
   Probability-weighted scenario tree, stress testing, tail scenario pricing
   → Explicit assumptions, Monte Carlo where appropriate

Layer 5: Portfolio Translation
   Factor-based exposure translation, hedge sizing, OMS formatting
   → Deterministic given upstream inputs
```

### Model Governance

- All models are versioned and stored in MLflow
- Re-calibration schedule: quarterly for statistical models, annually for scenario weights
- Out-of-sample validation required before any model update goes to production
- Champion/challenger framework for NLP models
- All NLP scores maintain a rule-based fallback

---

## Risk Scoring Formula

The Composite Macro Shock Risk Score `R_composite` is:

```
R_composite = Σ(w_i × S_i) × RegimeMultiplier × GapRiskMultiplier

where:
  S_i ∈ {Liquidity, Volatility, RateShock, EquityDownside, 
          CreditSpread, FX, Commodity, WeekendGap, PolicyAmbiguity}

  RegimeMultiplier ∈ [1.0, 2.0] based on regime classification
  GapRiskMultiplier ∈ [1.0, 1.5] based on time-since-close and gap conditions
  
  Weights w_i are regime-conditioned:
    Normal:  Liquidity=0.15, Vol=0.15, Rates=0.20, Equity=0.20, ...
    Crisis:  Liquidity=0.25, Vol=0.15, Rates=0.20, Equity=0.15, ...
```

Full formula derivation and calibration documented in `/docs/model_architecture.md`.

---

## Repository Structure

```
macro-shock-risk-engine/
├── README.md                          ← This file
├── pyproject.toml                     ← Python project config
├── requirements.txt                   ← Runtime dependencies
├── requirements-dev.txt               ← Dev/test dependencies
├── .env.example                       ← Environment variable template
├── docker-compose.yml                 ← Local development stack
├── Makefile                           ← Common developer commands
│
├── python/
│   ├── src/
│   │   └── macro_shock/
│   │       ├── event_detection/       ← Event detection & classification
│   │       ├── nlp/                   ← NLP & language intelligence
│   │       ├── market_context/        ← Market state ingestion & normalization
│   │       ├── scenario_engine/       ← Scenario tree & shock propagation
│   │       ├── risk_scoring/          ← Composite & sub-component scoring
│   │       ├── portfolio_impact/      ← Portfolio recommendations & hedges
│   │       ├── backtesting/           ← Event study & backtest framework
│   │       ├── monitoring/            ← Alerts, logging, audit trail
│   │       ├── execution/             ← OMS interface, kill switch, checks
│   │       ├── data/                  ← Ingestion, validation, alignment
│   │       └── orchestration/         ← Pipeline orchestration & scheduling
│   ├── tests/
│   │   ├── unit/                      ← Unit tests per module
│   │   ├── integration/               ← Integration tests
│   │   └── fixtures/                  ← Test fixtures & synthetic data
│   ├── configs/
│   │   ├── base.yaml                  ← Base configuration
│   │   ├── research.yaml              ← Research environment overrides
│   │   ├── staging.yaml               ← Staging environment overrides
│   │   └── production.yaml            ← Production environment overrides
│   ├── data_schema/                   ← Pydantic data models & schemas
│   └── notebooks/                     ← Research notebooks (not production)
│
├── cpp/
│   ├── src/
│   │   ├── scoring/                   ← Fast risk scorer
│   │   └── utils/                     ← Math, timestamp utilities
│   ├── include/                       ← Header files
│   ├── tests/                         ← C++ unit tests (Catch2)
│   ├── CMakeLists.txt                 ← Build configuration
│   └── bindings/                      ← pybind11 Python bindings
│
├── csharp/
│   ├── src/
│   │   └── MacroShockDashboard/       ← WPF operational dashboard
│   │       ├── ViewModels/            ← MVVM view models
│   │       ├── Views/                 ← XAML views
│   │       ├── Services/              ← API & data services
│   │       └── Models/                ← C# data models
│   └── tests/                         ← xUnit tests
│
├── docs/
│   ├── architecture.md                ← Full system architecture
│   ├── data_architecture.md           ← Data pipeline & schemas
│   ├── model_architecture.md          ← Model specs & calibration
│   ├── deployment.md                  ← Deployment guide & checklist
│   └── governance.md                  ← Model governance policy
│
├── examples/
│   ├── run_end_to_end.py              ← Minimal end-to-end example
│   └── synthetic_data_generator.py    ← Generate synthetic test data
│
└── scripts/
    ├── setup_env.sh                   ← Environment setup
    ├── run_backtest.sh                ← Backtest runner
    └── deploy_production.sh           ← Production deployment script
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- CMake 3.20+, GCC/Clang with C++17 support
- .NET 6 SDK (for C# dashboard)
- Docker & Docker Compose (for local data stack)

### Environment Setup

```bash
# Clone repository
git clone https://github.com/your-org/macro-shock-risk-engine.git
cd macro-shock-risk-engine

# Create Python environment
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env
# Edit .env with your data feed credentials and API keys

# Start local data stack (TimescaleDB, Redis, Elasticsearch)
docker-compose up -d

# Build C++ components
cd cpp && cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build
cd ..

# Run tests
make test

# Run end-to-end example with synthetic data
python examples/run_end_to_end.py --env research --use-synthetic-data
```

### Run the Risk Engine

```bash
# Real-time monitoring mode
python -m macro_shock.orchestration.pipeline --config configs/production.yaml --mode monitor

# Backtest mode
python scripts/run_backtest.sh --start 2020-01-01 --end 2024-01-01 --events all_fed

# Analyze a specific event
python -m macro_shock.orchestration.pipeline \
  --config configs/research.yaml \
  --mode event-analysis \
  --event-id "FED_PRESS_2022_11_02"
```

---

## Failure Modes and Limitations

### Known Limitations

1. **NLP Model Lag**: Transformer-based language models require ~2-5 seconds for inference. For events with sub-minute market impact, the rule-based lexicon layer is the operative signal.
2. **Data Feed Dependency**: System degrades gracefully when feeds are unavailable but cannot generate a full risk score without at minimum yields, VIX, and a market state snapshot.
3. **Model Calibration Decay**: Regime-conditioned weights are calibrated on historical events. Novel regime types (e.g., COVID-style simultaneous supply/demand shock) may produce under-estimated risk scores until recalibrated.
4. **Weekend Futures Liquidity**: Futures-based price discovery on weekends has thin liquidity; futures gap estimates carry wide uncertainty bounds that must be communicated to users.
5. **No Autonomous Execution**: The system generates recommendations but does not autonomously execute trades. All output requires PM or risk officer authorization.
6. **Correlation Instability**: Cross-asset correlations used in portfolio impact calculations are estimated on rolling windows and can break down sharply in tail events — exactly the regime where they matter most.

### Explicit Assumptions

- Event impact distributions are approximately log-normal conditioned on regime
- Historical event analogs are relevant; structural breaks in market microstructure are gradual
- Fed transcript language follows a consistent stylistic evolution; abrupt communication style changes may reduce NLP accuracy
- Futures markets open within 1 hour of event for typical weekend actions
- Options markets provide informative pre-event skew even for unscheduled events

---

## Deployment

See `/docs/deployment.md` for the full deployment checklist. Summary:

- **Research**: Local Docker stack, synthetic or historical data, no live feed connections  
- **Staging**: Full feed connections, production-equivalent config, no live OMS  
- **Production**: All feeds live, OMS connected, monitoring active, on-call rotation set  

Rollback procedure: tagged Docker images with `git tag` at every production deploy. Any production incident triggers immediate rollback and post-mortem within 24 hours.

---

## Testing

```bash
# Unit tests
pytest python/tests/unit/ -v --cov=macro_shock

# Integration tests (requires running Docker stack)
pytest python/tests/integration/ -v -m integration

# C++ tests
cd cpp/build && ctest --output-on-failure

# C# tests
cd csharp && dotnet test
```

Minimum coverage targets: **80% unit, 60% integration**. All risk scoring modules require 90%+.

---

## Security and Logging

- All API credentials stored in environment variables or HashiCorp Vault (production)
- No credentials in source code or config files
- Structured JSON logging via `structlog` with correlation IDs per event
- Log levels: DEBUG (research), INFO (staging), WARNING+ (production)
- Full audit trail for all risk score outputs and portfolio recommendations
- Read-only data feed credentials; write access isolated to OMS interface module
- Network egress restricted to approved data vendor endpoints in production

---
**License **

Copyright (c) 2026 Josh20241995. All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

---

*Macro Shock Risk Engine — Quantitative Research & Risk Engineering*  
*Build with rigor. Hedge with precision. Never mistake noise for signal.*
