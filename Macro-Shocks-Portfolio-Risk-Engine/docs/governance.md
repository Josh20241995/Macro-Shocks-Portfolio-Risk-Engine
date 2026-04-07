# Model Governance Policy

## Macro Shock Risk Engine — Model Governance and Risk Controls

**Version:** 1.0  
**Owner:** Quantitative Research & Risk Engineering  
**Review Cycle:** Annually, or after any material model change  

---

## 1. Purpose

This document defines the model governance framework for the MSRE. It establishes standards for model development, validation, deployment, monitoring, and retirement. All models in this system are subject to these controls regardless of complexity.

---

## 2. Model Inventory

| Model ID | Description | Type | Owner | Last Calibrated | Next Review |
|----------|-------------|------|-------|----------------|-------------|
| MSRE-NLP-001 | Hawkish/Dovish Lexicon Scorer | Rule-based | Quant Research | 2024-Q4 | 2025-Q2 |
| MSRE-NLP-002 | Transformer Embedding Scorer | ML (sentence-transformers) | Quant Research | 2024-Q4 | 2025-Q4 |
| MSRE-MKT-001 | Market Vulnerability Scorer | Statistical (percentile-based) | Risk Engineering | 2024-Q3 | 2025-Q1 |
| MSRE-SCN-001 | Scenario Tree Weight Engine | Statistical + Rule-based | Quant Research | 2024-Q3 | 2025-Q1 |
| MSRE-RSK-001 | Composite Risk Scorer | Weighted formula | Quant Research | 2024-Q4 | 2025-Q2 |
| MSRE-REG-001 | Regime Classifier | Rule-based thresholds | Risk Engineering | 2024-Q3 | 2025-Q1 |

---

## 3. Model Development Standards

### 3.1 Code Requirements

- All models must be implemented in the production code repository (no shadow Excel models)
- All parameters must be explicitly documented with calibration rationale
- All models must be reproducible from a fixed random seed where stochastic
- Unit tests must cover ≥ 90% of scoring logic
- All models must have a rule-based fallback for when data is unavailable

### 3.2 Calibration Requirements

- Calibration data must use only information available at calibration time
- Training/validation split must be temporal (not random) to respect causal ordering
- Minimum sample sizes per regime:
  - Normal regime: ≥ 50 events
  - Crisis regime: ≥ 10 events (acknowledged small sample risk)
  - Weekend events: ≥ 15 events
- All calibrations must document assumed market structure (e.g., pre-QE vs. post-QE)

### 3.3 Forbidden Practices

- **No look-ahead bias**: validation data must be strictly posterior to training data
- **No p-hacking**: parameter search must be documented; no undisclosed iterations
- **No data snooping**: test set cannot be used during model development
- **No implicit assumptions**: all assumptions must be stated explicitly in code comments and documentation

---

## 4. Model Validation Framework

### 4.1 Pre-Deployment Validation

Every model change requires:

1. **Backtesting Report**: Walk-forward validation on the full historical event corpus
2. **Metric Comparison**: All KPIs compared to current production model (champion/challenger)
3. **Stress Test**: Model behavior in the 5 most extreme historical events
4. **Sensitivity Analysis**: How sensitive is the score to ±10% perturbation in each input?
5. **Independent Review**: At least one quant engineer not involved in development

### 4.2 Key Performance Indicators

| KPI | Minimum Threshold | Target |
|-----|------------------|--------|
| Score-to-severity correlation | ≥ 0.30 | ≥ 0.50 |
| Precision@CRITICAL (score ≥ 75) | ≥ 0.60 | ≥ 0.75 |
| Recall@CRITICAL | ≥ 0.75 | ≥ 0.85 |
| Weekend gap estimate MAE | ≤ 3.0% | ≤ 2.0% |
| False CRITICAL rate | ≤ 40% | ≤ 25% |
| Mean score in benign events | ≤ 35 | ≤ 25 |

### 4.3 Champion/Challenger Process

When a new model version is proposed:

1. New model runs in "shadow mode" (parallel to production, no output to OMS/alerts)
2. Shadow mode minimum duration: 2 weeks for minor changes, 4 weeks for major changes
3. Shadow mode must include at least one live macro event if possible
4. Champion/challenger report must show KPI comparison across all metrics
5. Risk officer must approve before challenger becomes champion

---

## 5. Ongoing Monitoring

### 5.1 Automated Monitoring

The following checks run automatically in production:

- **Score drift**: Alert if mean composite score deviates > 15 points from 90-day rolling average
- **Calibration decay**: Alert if out-of-sample score accuracy drops below minimum threshold
- **Input distribution shift**: Alert if key market inputs (VIX, HY spreads) are outside 5-year historical range for > 10 consecutive days
- **NLP confidence drift**: Alert if mean NLP confidence score drops below 0.4 over 30-day window

### 5.2 Scheduled Reviews

| Review | Frequency | Participants |
|--------|-----------|-------------|
| Model performance review | Quarterly | Quant Research, Risk Engineering |
| Full model audit | Annually | All teams + independent reviewer |
| Emergency review | After any extreme market event | All teams |
| Post-event analysis | After each CRITICAL alert | Quant Research |

### 5.3 Model Degradation Triggers

The following events trigger an immediate model review:

- Any CRITICAL alert that was not followed by a severe market event (false positive)
- Any severe market event (SPX < -5% intraday, VIX > 35) where MSRE score was < 45
- Any scoring error or pipeline failure in production
- Any market regime change that was not detected by the regime classifier within 5 trading days

---

## 6. Model Retirement and Replacement

A model is retired when:

- Replacement model has demonstrated superior KPIs over at least 2 validation periods
- Risk officer has approved the replacement
- Migration plan has been tested in staging
- Legacy model code is archived (not deleted) with a deprecation notice

---

## 7. Documentation Requirements

Every model must maintain:

- **Model Card**: Purpose, inputs, outputs, limitations, calibration date
- **Calibration Report**: Data used, parameters fitted, out-of-sample results
- **Change Log**: Every change with date, rationale, and approver
- **Assumption Register**: Every explicit assumption with justification

---

## 8. Limitations and Known Issues

### 8.1 Structural Limitations

1. **Crisis regime sample size**: Historical crises are rare. Crisis regime calibration is based on fewer than 20 events and carries high uncertainty.
2. **Correlation instability**: Cross-asset correlations used in portfolio impact scoring are estimated on rolling windows and break down precisely in tail events.
3. **Communication style evolution**: The Fed's communication style has evolved significantly (Greenspan → Bernanke → Yellen → Powell). NLP models trained primarily on recent vintages may not generalize well to future style shifts.
4. **Emergency event rarity**: Unscheduled emergency events are too rare for reliable statistical calibration. Scenario weights in emergency mode rely heavily on expert judgment.
5. **Weekend liquidity estimation**: Futures-based gap estimates assume liquid futures markets. In a genuine financial crisis, futures themselves may be illiquid.

### 8.2 Explicit Assumptions

1. Event impact distributions are approximately log-normal conditioned on regime
2. The current FOMC communication framework is broadly stable
3. Historical event analogs are relevant to current market structure
4. The 8-scenario tree captures the dominant modes of market response
5. Regime classification changes gradually; abrupt regime shifts may cause temporary misclassification
6. Volatility term structure inversion is a reliable crisis indicator (calibrated 2010-2024)

### 8.3 What the Model Does NOT Do

- Provide real-time intraday signals (not designed for tick data)
- Replace PM judgment — all outputs are advisory
- Guarantee a specific market outcome
- Detect every possible macro shock type (geopolitical events outside the configured institution list are not scored)
- Provide legal or compliance guidance
