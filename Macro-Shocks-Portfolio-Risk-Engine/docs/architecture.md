# System Architecture

## Macro Shock Risk Engine (MSRE) — Technical Architecture

---

## 1. Overview

The MSRE is a five-layer, cross-language risk intelligence system purpose-built for asymmetric macro shock events. It is not a signal-generating trading system; it is a risk *measurement and guidance* system that tells portfolio managers how much risk a policy event represents and what to do about it before, during, and after market closure.

---

## 2. Architectural Principles

### 2.1 Layered Modeling (No Magic Boxes)

```
Layer 1 ── Deterministic Rules
           Event classification, market closure detection, weekend gap identification.
           Always interpretable. Never fail silently.

Layer 2 ── Statistical Impact Models
           Percentile-based vulnerability scoring, calibrated scenario weights,
           historical regime conditioning. Explicit uncertainty bounds.

Layer 3 ── NLP / Language Models
           Two-stage: lexicon (fast, interpretable) + transformer (richer context).
           Lexicon is always the operative signal; transformer is additive.

Layer 4 ── Scenario Analysis
           Probability-weighted named scenario tree. Explicit impact estimates.
           Stress-tested at 5th and 1st percentile tail outcomes.

Layer 5 ── Portfolio Translation
           Factor-based hedge sizing. Asset-class-specific guidance.
           Always advisory; never automated.
```

### 2.2 Fail-Safe Degradation

Every module that fails or lacks data must:
1. Log the failure with structured context
2. Mark the stage as failed in `PipelineRunContext.failed_stages`
3. Return a conservative default (not silence, not zero)
4. Communicate data quality via score reliability flags

### 2.3 Strict Temporal Ordering

In both real-time and backtest mode, the system enforces that no data from after the event timestamp is used in any signal computation. The `TimestampGuard` class in the backtesting module enforces this at the data-access level, not just by convention.

---

## 3. Data Flow Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  EXTERNAL INPUTS                                                      │
│  News Feeds / Event Calendars / Transcripts / Market Data Feeds       │
└─────────────────────────┬────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────┐
│  Event Detection & Calendar     │  ← Deterministic classification
│  event_detection/detector.py    │    Weekend gap corridor logic
│  event_detection/calendar.py    │    Severity scoring
└─────────────────────────┬───────┘
                          │ MacroEvent
                          ▼
        ┌─────────────────┴─────────────────┐
        │                                   │
        ▼                                   ▼
┌──────────────────┐              ┌──────────────────────┐
│  NLP Intelligence│              │  Market Context      │
│  nlp/            │              │  market_context/     │
│  - Lexicon score │              │  - Vulnerability     │
│  - Transformer   │              │  - Regime classify   │
│  - Surprise vec  │              │  - Data quality      │
└────────┬─────────┘              └──────────┬───────────┘
         │ PolicySurpriseVector              │ VulnerabilityComponents
         └─────────────────┬────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Scenario Engine       │
              │  scenario_engine/      │
              │  - 8 named scenarios   │
              │  - Regime conditioning │
              │  - Gap amplification   │
              └────────────┬───────────┘
                           │ ScenarioTree
                           ▼
              ┌────────────────────────┐
              │  Risk Scoring Engine   │  ← 9 sub-scores
              │  risk_scoring/         │    Regime multiplier
              │  Python + C++ fast     │    Gap multiplier
              └────────────┬───────────┘
                           │ CompositeRiskScore
                           ▼
              ┌────────────────────────┐
              │  Portfolio Impact      │
              │  portfolio_impact/     │
              │  - Per asset class     │
              │  - Hedge recs          │
              │  - Kill switch flag    │
              └────────────┬───────────┘
                           │ PortfolioImpactReport
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
  ┌─────────────────┐         ┌──────────────────┐
  │  Alert Manager  │         │  OMS Interface   │
  │  monitoring/    │         │  execution/      │
  │  - Threshold    │         │  - Pre-trade     │
  │  - Routing      │         │  - Auth required │
  │  - Audit trail  │         │  - Kill switch   │
  └────────┬────────┘         └──────────┬───────┘
           │                             │
           ▼                             ▼
  Slack/PagerDuty/OMS           Pending Orders Queue
                                (Requires PM Auth)
```

---

## 4. Weekend Gap Corridor Architecture

The weekend gap corridor is the system's most critical special case. When an event occurs in this window, the entire scoring and portfolio guidance pathway applies amplification factors.

```
Event Timeline (Friday 4pm ET to Monday 9:30am ET):

  Fri 4:00pm ─── Equity Cash Markets CLOSE
                │
                │  ES Futures reopen at 4:15pm
                │  (limited liquidity, thin book)
                │
  Fri 4:00pm+ ──── EVENT OCCURS ← Gap corridor begins
                │
                │  Hours_until_open = (Mon 9:30am - event_time)
                │  full_weekend_gap = True
                │  gap_risk_multiplier = 1.2 + (hours/60) × 0.3 ∈ [1.2, 1.5]
                │
  Sat 00:00 ─── Weekend. FX open (thin). Crypto open.
                │  Futures have limited liquidity.
                │  No equity price discovery.
                │
  Sun 23:00 ─── CME ES futures reopen (Sunday night)
                │  First material price discovery for most portfolios
                │
  Mon 9:30am ─── Equity cash markets OPEN
                │  First full price discovery
                │  Margin calls triggered if gap large
                │  Correlation spike risk maximum
                │
Amplification:
  scenario impacts × 1.25–1.40
  trading halt probability × 2.0
  forced deleveraging risk × 1.5
  monday_gap_estimate = E[equity_impact] × 0.85 (futures absorb ~15%)
```

---

## 5. Language Processing Architecture

```
Input Text
    │
    ├─── Stage 1: Lexicon Scorer (always runs, < 1ms)
    │    - 80+ hawkish/dovish phrase dictionary
    │    - Diminishing returns for repeated phrases
    │    - Boolean flags: crisis_language, policy_reversal
    │    - Component scores: rate_path, inflation, growth, financial_stability
    │    Output: HawkishDovishScore (method="lexicon")
    │
    ├─── Stage 2: Transformer Scorer (optional, 2-5s)
    │    - sentence-transformers/all-MiniLM-L6-v2
    │    - Cosine similarity to curated hawkish/dovish anchors
    │    - Fallback: disabled if library unavailable
    │    Output: float in [-1, +1]
    │
    └─── Ensemble: 75% lexicon + 25% transformer
         Output: HawkishDovishScore (method="ensemble")
              │
              ▼
    PolicySurpriseEngine
    - Compare to prior expected stance
    - Compute directional surprise per dimension
    - Amplify for weekend/emergency events
    Output: PolicySurpriseVector (7 dimensions + composite)
```

**Why not an LLM in the critical path?**

LLMs (GPT-4, Claude, etc.) are not used in the real-time scoring path because:
1. Latency: 500ms–5s API calls are unacceptable for event-driven risk
2. Non-determinism: same input can produce different outputs across calls
3. Cost: hundreds of API calls per event across backtest corpus
4. Interpretability: auditors need reproducible, explainable scores

LLMs are used *offline* for lexicon improvement, corpus analysis, and anchor sentence generation.

---

## 6. C++ Integration Architecture

The Python risk scorer and the C++ fast scorer are **semantically equivalent**. The C++ scorer is used when:
- Streaming event processing requires < 1ms evaluation
- Multiple events arrive simultaneously (parallel scoring)
- The Python GIL would create latency spikes

```
                              ┌──────────────────┐
                              │  Python Pipeline  │
                              │  (orchestration)  │
                              └────────┬──────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
              ▼                        ▼                        ▼
   ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
   │  Python Scorer   │    │  C++ Fast Scorer │    │  C++ Fast Scorer │
   │  (full features) │    │  via pybind11    │    │  (streaming)     │
   │  - All sub-scores│    │  - Sub-ms latency│    │  - Tick data     │
   │  - Full explain  │    │  - Same math     │    │  - No GIL        │
   └──────────────────┘    └──────────────────┘    └──────────────────┘
         ↑                        ↑
    Detailed report          Fast score only
    (post-event)             (real-time gate)
```

The C++ bindings are generated via pybind11. The Python interface is:
```python
import msre_fast_scorer as fast
result = fast.score(market_inputs, surprise_inputs, event_inputs, scenario_summary)
```

---

## 7. Database Architecture

```
TimescaleDB (time-series market data)
├── market_snapshots        ← Equity, yields, vol, credit, FX, commodities
├── risk_scores             ← All composite and sub-scores with timestamps
├── scenario_trees          ← Stored scenario tree outputs
└── alert_history           ← All emitted alerts

PostgreSQL (relational metadata)
├── macro_events            ← Event catalog with classification
├── backtest_events         ← Historical events with realized outcomes
├── model_versions          ← Model registry and calibration history
├── order_audit             ← OMS order log
└── market_calendar         ← Holiday and early-close dates

Elasticsearch (text search)
├── news_headlines          ← Raw and processed headlines
├── transcripts             ← Full event transcripts
└── audit_logs              ← Structured operational logs

Redis (operational cache)
├── latest_risk_score       ← Hot cache for dashboard API
├── active_events           ← Currently monitored events
└── alert_state             ← Alert acknowledgment state
```

---

## 8. Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  PRODUCTION ENVIRONMENT                                          │
│                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐                  │
│  │  Event Monitor   │    │  Market Data      │                  │
│  │  (Python worker) │    │  Collector        │                  │
│  │  Polls feeds     │    │  (Python worker)  │                  │
│  └────────┬─────────┘    └────────┬──────────┘                  │
│           │                       │                             │
│           └───────────┬───────────┘                             │
│                       │                                         │
│                       ▼                                         │
│          ┌────────────────────────┐                             │
│          │  Pipeline Orchestrator │                             │
│          │  (Python, async)       │                             │
│          └────────────┬───────────┘                             │
│                       │                                         │
│         ┌─────────────┼─────────────┐                           │
│         ▼             ▼             ▼                           │
│    TimescaleDB    PostgreSQL    Elasticsearch                   │
│                                                                  │
│         ┌─────────────────────────┐                             │
│         │  REST API (FastAPI)     │ ← Dashboard reads here      │
│         └─────────────────────────┘                             │
│                                                                  │
│    ┌──────────────────────────────────┐                         │
│    │  C# WPF Dashboard               │ ← Analyst/PM interface  │
│    │  (reads from REST API)          │                         │
│    └──────────────────────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. Security Architecture

- All credentials via environment variables or HashiCorp Vault (production)
- No secrets in source code or configuration files
- Data feed access: read-only credentials, IP whitelisted
- OMS interface: write access isolated, MFA required
- Dashboard: read-only API token per user
- Audit logs: append-only, signed (tamper-evident)
- Network: production pipeline runs in isolated VPC/VLAN
- Log retention: 7 years (regulatory compliance)

---

## 10. Performance Targets

| Component | Target Latency | Actual (measured) |
|-----------|---------------|-------------------|
| Event detection (single) | < 50ms | ~5ms |
| Lexicon NLP score | < 5ms | < 1ms |
| Transformer NLP score | < 5s | 2-4s (CPU) |
| Vulnerability scoring | < 20ms | ~8ms |
| Scenario tree build | < 50ms | ~15ms |
| Python composite scorer | < 100ms | ~40ms |
| C++ fast scorer | < 1ms | ~0.3ms |
| Full pipeline (no transformer) | < 500ms | ~200ms |
| Full pipeline (with transformer) | < 10s | ~5s |
| Dashboard API response | < 200ms | ~80ms (cached) |
