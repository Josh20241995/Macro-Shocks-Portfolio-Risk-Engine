# Product Roadmap

## Macro Shock Risk Engine — Development Roadmap

**Status:** Active development  
**Current Version:** 1.0.0  
**Owner:** Quantitative Research & Risk Engineering  

---

## Version 1.0 — Foundation (Current)

**Delivered:**
- Core pipeline: event detection → NLP → market context → scenario tree → risk scoring → portfolio impact
- 9-component composite risk score with regime and gap multipliers
- 8-scenario probability-weighted scenario tree
- Weekend gap corridor detection and amplification
- Lexicon-based hawkish/dovish scorer with transformer enhancement (optional)
- Policy surprise vector (7 dimensions)
- Portfolio impact engine with hedge recommendations across 6 asset classes
- Historical event study backtesting framework with look-ahead bias enforcement
- FastAPI REST server
- C# WPF operational dashboard
- C++ fast scorer with pybind11 bindings
- TimescaleDB + PostgreSQL schema with full audit trail
- CI/CD pipeline (GitHub Actions)
- Docker deployment with health checks and zero-downtime rollback

---

## Version 1.1 — Enhanced Intelligence *(Target: Q2 2025)*

### NLP Enhancement
- [ ] **FinBERT fine-tuning**: Fine-tune a financial domain transformer on the FOMC transcript corpus (2010-present). Expected improvement in hawkish/dovish classification accuracy: +8-12pp vs. generic sentence-transformers.
- [ ] **Section-aware parsing**: Split transcripts into prepared remarks, Q&A, and follow-up; weight each section differently in the ensemble.
- [ ] **Tone shift detection**: Detect meaningful changes in language between consecutive communications (e.g., "higher for longer" dropped from prepared remarks).
- [ ] **Uncertainty quantifier**: Separate "we are confident" language from "we remain uncertain" as a standalone dimension in the surprise vector.

### Regime Detection
- [ ] **HMM regime classifier**: Replace rule-based thresholds with a 4-state Hidden Markov Model trained on 2010-2024 market data. Expected improvement in regime transition detection: +15% lead time.
- [ ] **Correlation regime overlay**: Add cross-asset correlation breakdown as an explicit sub-score. Use rolling 63-day correlation vs. 252-day average.
- [ ] **Vol surface regime**: Incorporate VIX term structure slope and skew regime as separate vulnerability inputs.

### Scoring
- [ ] **Intraday re-scoring**: Re-compute the composite score every 15 minutes after an event for the first 4 hours as new market information is absorbed.
- [ ] **Confidence intervals**: Report 10th/50th/90th percentile score estimates based on NLP confidence and data completeness.

---

## Version 1.2 — Multi-Central-Bank *(Target: Q3 2025)*

- [ ] **ECB support**: Add ECB press conference detection and language model calibration (Lagarde communication style).
- [ ] **BOJ support**: Add BOJ Monetary Policy Meeting decisions; handle YCC policy-specific surprise dimensions.
- [ ] **BOE support**: Add Bank of England MPC decisions.
- [ ] **Coordinated CB action detection**: Detect simultaneous policy moves by multiple central banks (e.g., 2008, 2020 COVID responses) and amplify scenario tail weights.
- [ ] **G7/G20 statement monitoring**: Detect joint communiqués with policy language and classify as GEOPOLITICAL_SURPRISE.

---

## Version 1.3 — Options Surface Integration *(Target: Q4 2025)*

- [ ] **Options-implied scenario probabilities**: Use SPX options surface (OTM puts, risk reversals, variance swaps) to calibrate scenario probabilities directly from market pricing rather than using fixed priors.
- [ ] **Realized vs. implied vol regime**: Add realized vol / implied vol spread as a standalone vulnerability input.
- [ ] **Gamma exposure estimation**: Incorporate dealer gamma positioning (via public options flow data) to estimate potential for gamma-driven amplification of moves.
- [ ] **MOVE index integration**: Use MOVE index as a leading indicator of rates vol shock risk.
- [ ] **Vol surface term structure**: Detect inversion of vol term structure (near-term vol > long-term vol) as a standalone CRITICAL condition.

---

## Version 1.4 — Alternative Data *(Target: Q1 2026)*

- [ ] **Satellite / alternative data feeds**: Integrate alternative data proxies for economic activity (shipping, energy consumption) as leading indicators.
- [ ] **Options flow and positioning data**: Integrate CBOE ORATS or similar for daily put/call flow by strike and expiry.
- [ ] **Short interest data**: Use aggregate short interest as a crowding and forced-deleveraging proxy.
- [ ] **COT positioning**: Automate CFTC Commitment of Traders data ingestion and use net positioning as a contrarian signal.
- [ ] **Credit default swap curve**: Ingest CDS term structure to detect credit deterioration earlier than cash bond spreads.

---

## Version 2.0 — Autonomous Hedging *(Target: Q2 2026)*

**Requires:** Separate risk governance review and regulatory compliance analysis before activation.

- [ ] **Automatic pre-positioning**: For score > 75 on Friday-after-close events, automatically initiate a small pre-approved hedge position (e.g., 2% of equity beta in SPX puts) without PM approval, up to a pre-approved notional limit.
- [ ] **Dynamic hedge sizing**: Replace static sizing guidance with real-time Greek-based hedge sizing using live portfolio positions.
- [ ] **Feedback loop**: Track realized market outcomes vs. predictions; feed into automated recalibration of scenario weights.
- [ ] **FIX protocol integration**: Full FIX 4.4 order submission to OMS for pre-approved hedge instruments.
- [ ] **Cross-institution correlation**: Model joint Fed + ECB actions and their compounding effect on global risk.

---

## Ongoing Backlog (No Specific Version)

### Infrastructure
- [ ] Kubernetes migration (Helm charts, autoscaling)
- [ ] Multi-region deployment for disaster recovery
- [ ] HashiCorp Vault integration for secrets management (replace env vars)
- [ ] Prometheus + Grafana monitoring stack
- [ ] Automated model performance dashboard

### Research
- [ ] Geopolitical shock database: curate historical geopolitical events with market outcomes for backtesting
- [ ] Cross-asset contagion mapping: build empirical matrix of historical shock transmission between asset classes by regime
- [ ] Fed communication style index: track language complexity and uncertainty over time as a meta-signal

### Testing
- [ ] Property-based testing with Hypothesis for score boundary conditions
- [ ] Load testing for API server (k6)
- [ ] Chaos engineering: simulate data feed failures, database outages in staging

---

## Decisions Deferred

| Decision | Deferred Until | Reason |
|----------|---------------|--------|
| Fully autonomous execution | Version 2.0 | Risk governance + regulatory review required |
| LLM in critical scoring path | Version 1.1+ | Latency and non-determinism concerns; re-evaluate with faster models |
| Crypto as a leading indicator | Version 1.1 | Data quality and market microstructure too different from institutional markets |
| Real-time options pricing | Version 1.3 | Requires options feed license; justify ROI first |
