# Model Architecture

## Macro Shock Risk Engine — Quantitative Model Specification

---

## 1. Model Hierarchy

The MSRE uses a five-layer modeling hierarchy. Each layer feeds the next. No layer is allowed to read data from layers above it in the hierarchy (enforced by module structure and reviewed in code review).

```
Layer 1: Deterministic Rules           ← event_detection/
Layer 2: Statistical Impact Models     ← market_context/
Layer 3: NLP / Language Models         ← nlp/
Layer 4: Scenario Analysis             ← scenario_engine/
Layer 5: Portfolio Translation         ← portfolio_impact/
```

---

## 2. Layer 1: Event Classification (Deterministic)

### 2.1 Severity Score Formula

```
S_event = min(
    Institution_Weight × 30
    + Speaker_Seniority × [0, 20]
    + EventType_Base × [5, 25]
    + Timing_Boost × [0, 35]
    + Emergency_Content_Boost × [0, 35],
    100
)

where:
  Institution_Weight ∈ {Fed=1.0, Treasury=0.85, White House=0.80, ECB=0.75, ...}
  Speaker_Seniority:
    High (Chair, President): +20
    Medium (Governor, VP):   +10
    Other:                   +5
  EventType_Base:
    UNSCHEDULED_EMERGENCY:     25
    INTERMEETING_RATE_ACTION:  25
    FINANCIAL_STABILITY:       22
    WEEKEND_POLICY_ACTION:     20
    PRESS_CONFERENCE:          15
    SCHEDULED_POST_CLOSE:      12
    CONGRESSIONAL_TESTIMONY:   10
  Timing_Boost:
    Full weekend gap:     +25
    After hours (weekday):+15
    Normal intraday:        0
  Emergency_Content_Boost:
    Any emergency trigger phrase detected: +35 (once)
```

### 2.2 Event Type Classification Logic

```python
Priority order (first match wins):
  1. Emergency phrase detected in text → UNSCHEDULED_EMERGENCY
  2. "inter.?meeting|unscheduled.?rate" regex → INTERMEETING_RATE_ACTION
  3. ≥ 2 financial stability phrases → FINANCIAL_STABILITY_STATEMENT
  4. Event day is Saturday or Sunday → WEEKEND_POLICY_ACTION
  5. "press conference" or "q&a" in text, after-hours → SCHEDULED_POST_CLOSE
  6. "congress|senate|testimony|hearing" → CONGRESSIONAL_TESTIMONY
  7. Geopolitical keyword list → GEOPOLITICAL_SURPRISE
  8. After-hours or pre-market → SCHEDULED_POST_CLOSE
  9. Default → PRESS_CONFERENCE
```

---

## 3. Layer 2: Market Vulnerability Scoring (Statistical)

### 3.1 Percentile-Based Normalization

Each raw market metric is converted to a vulnerability score in [0, 1] via piecewise linear interpolation through calibration knots:

```
vuln_score(x; p10, p25, p50, p75, p90) =
    0.00                          if x ≤ p10
    linear_interp(x; p10→0.10,   if p10 < x ≤ p25
                    p25→0.25)
    linear_interp(x; p25→0.25,   if p25 < x ≤ p50
                    p50→0.50)
    ... (and so on)
    1.00                          if x ≥ p90

Calibration knots (2010-2024 historical):
  VIX:           (12.0, 15.0, 18.5, 25.0, 35.0)
  HY spread bps: (250,  320,  420,  550,  700)
  IG spread bps: (50,   70,   100,  140,  190)
  Bid-ask bps:   (0.5,  1.0,  1.5,  3.0,  6.0)
  TED spread bps:(10,   15,   25,   45,   80)
```

### 3.2 Composite Vulnerability Score

```
V = Σ(w_i × vuln_i) / Σ(w_i)  [weights renormalized for missing data]

Component weights:
  Liquidity:   0.25
  Volatility:  0.20
  Credit:      0.20
  Yield Curve: 0.10
  Breadth:     0.10
  Funding:     0.10
  Positioning: 0.05

Amplification Factor = 1.0 + min(V, 1.0) ∈ [1.0, 2.0]
```

### 3.3 Regime Classification (Rule-Based)

```
if vol_vuln > 0.80 AND credit_vuln > 0.70 AND liq_vuln > 0.70:
    regime = CRISIS

elif V > 0.65 AND (vol_vuln > 0.55 OR credit_vuln > 0.55):
    regime = RISK_OFF_CORRECTION

elif V < 0.30 AND vol_vuln < 0.35:
    regime = RISK_ON_EXPANSION

elif 0.30 ≤ V < 0.65:
    regime = FRAGILE_RISK_ON

else:
    regime = UNKNOWN
```

*Note: A Hidden Markov Model (HMM) regime classifier is planned for MSRE v1.1. The rule-based classifier is retained as fallback due to its interpretability and stability.*

---

## 4. Layer 3: NLP Language Scoring

### 4.1 Lexicon Scorer

For a given text T, the raw hawkish score is:

```
raw_hawkish = Σ_{phrase p in HAWKISH_LEXICON} w_p × f(count_p)

where:
  w_p = phrase weight (calibrated, ∈ [0.4, 1.0])
  f(n) = 1 + sqrt(n-1) for n > 1  (diminishing returns for repetition)
        = 1             for n = 1

overall_score = clip(
    (raw_hawkish - raw_dovish) / (raw_hawkish + raw_dovish + ε),
    -1.0, 1.0
)

confidence = min(total_signal / 5.0, 1.0)
  where total_signal = raw_hawkish + raw_dovish
```

### 4.2 Ensemble (Lexicon + Transformer)

When the transformer scorer is available:

```
overall_score_ensemble = (1 - w_t) × score_lexicon + w_t × score_transformer
  where w_t = 0.25  (transformer weight)
```

### 4.3 Policy Surprise Dimensions

The surprise magnitude along each dimension d is:

```
surprise_d = clip(actual_score_d - expected_score_d, -1, 1)

composite_surprise_magnitude = Σ(w_d × |surprise_d|) / Σ(w_d)

Dimension weights:
  rate_path:            0.30
  inflation_outlook:    0.20
  growth_outlook:       0.15
  balance_sheet:        0.10
  financial_stability:  0.15
  forward_guidance:     0.05
  urgency:              0.05

Weekend/emergency amplification:
  composite_magnitude_amplified = min(composite_magnitude × 1.3, 1.0)  [if full_weekend_gap]
```

---

## 5. Layer 4: Scenario Tree

### 5.1 Prior Scenario Probabilities

Eight named scenarios with empirically-estimated prior probabilities (2010-2024 FOMC events):

| Scenario | Prior P | Expected Equity | Expected 10Y (bps) | VIX Δ |
|----------|---------|----------------|-------------------|-------|
| Benign / In-Line | 0.30 | -0.5% | +3 | 0 |
| Mild Hawkish Surprise | 0.25 | -1.8% | +12 | +2.5 |
| Mild Dovish Surprise | 0.20 | +1.5% | -10 | -2.0 |
| Significant Hawkish Shock | 0.10 | -4.5% | +28 | +8.0 |
| Disorderly Risk-Off | 0.07 | -7.5% | +15 | +18 |
| Emergency Crisis Easing | 0.03 | -8.0% | -40 | +25 |
| Extraordinary Market Intervention | 0.01 | -12.0% | -60 | +40 |
| Significant Dovish Accommodation | 0.04 | +3.5% | -20 | -5.0 |

### 5.2 Posterior Probability Update

Priors are updated by three conditioning factors applied sequentially:

**Step 1: Surprise Direction Conditioning**
```
For scenario s with direction d_s (hawkish or dovish):
  boost_s = 1 + magnitude × 1.5  if direction aligns with s
  boost_s = max(1 - magnitude × 0.8, 0.05)  if direction opposes s
  
Benign scenario: boost = max(1 - magnitude × 2.0, 0.05)
Tail scenarios: additional boost of (1 + urgency × 1.0) if urgency > 0.5
Crisis scenarios: 3× boost if crisis_language_detected
```

**Step 2: Regime Conditioning**
```
Tail scenario multiplier by regime:
  RISK_ON_EXPANSION:   0.50
  FRAGILE_RISK_ON:     1.00
  RISK_OFF_CORRECTION: 1.80
  CRISIS:              4.00
  RECOVERY:            0.70
```

**Step 3: Weekend Gap Amplification**
```
For tail/adverse scenarios when full_weekend_gap = True:
  impact = impact × gap_amp  where gap_amp ∈ [1.25, 1.40]
  trading_halt_prob = min(base_halt_prob × 2.0, 0.95)
  forced_deleveraging_risk = min(base_delev × 1.5, 1.0)
```

**Final normalization:**
```
p_s = raw_score_s / Σ(raw_score_i)   [ensures Σ p_i = 1.0]
```

### 5.3 Expected Values and Tail Statistics

```
E[equity] = Σ(p_s × equity_impact_s)
E[10Y yield] = Σ(p_s × yield_10y_s)
E[VIX] = Σ(p_s × vix_change_s)

Tail loss (5th pct): sort scenarios by equity_impact ascending,
  find the cumulative probability that reaches 0.05

Monday gap estimate = E[equity] × 0.85
  (futures absorb ~15% of expected move before Monday open)
```

---

## 6. Layer 5: Composite Risk Score

### 6.1 Master Formula

```
R_composite = min(Σ(w_i × S_i) × M_regime × M_gap, 100)

where:
  S_i ∈ [0, 100]     = sub-scores (9 components)
  w_i                = regime-conditioned weights (sum to 1.0)
  M_regime ∈ [1, 2]  = regime multiplier
  M_gap ∈ [1, 1.5]   = weekend gap multiplier
```

### 6.2 Sub-Score Formulas

**S_liquidity** (Liquidity Risk):
```
= min(
    vuln_liquidity × 50           [pre-event stress]
  + E[liquidity_impairment] × 30  [expected from scenario tree]
  + urgency_surprise × 20,        [policy urgency signal]
  100
)
```

**S_volatility** (Volatility Risk):
```
= min(
    [(VIX - 12) / (40 - 12)] × 35        [VIX level percentile]
  + max(E[ΔVIX], 0) / 20 × 35            [expected vol expansion]
  + composite_surprise_magnitude × 30,   [policy shock magnitude]
  100
)
```

**S_rate_shock** (Rate Shock Risk):
```
= min(
    |rate_path_surprise| × 40             [surprise direction/magnitude]
  + |E[Δ10Y yield]| / 30 × 35            [expected yield move]
  + [curve_inversion_score × 25 or 5],   [curve shape amplifier]
  100
)

curve_inversion_score = min(|slope_2_10| / 100, 1.0)  if slope_2_10 < 0
                       else 0
```

**S_equity_downside** (Equity Downside Risk):
```
= min(
    max(-E[equity], 0) / 5 × 40           [expected downside]
  + |min(tail_loss_5pct, 0)| / 10 × 35   [tail severity]
  + drawdown_from_52w_high / 0.20 × 25,  [pre-existing vulnerability]
  100
)
```

**S_weekend_gap** (Weekend Gap Risk):
```
= 0  if not (is_after_hours or is_weekend)

otherwise:
= min(
    hours_until_next_open / 60 × 40    [gap duration]
  + composite_magnitude × 30 × gap_boost  [surprise × gap amplifier]
  + urgency_surprise × 30,            [urgency during gap]
  100
)

gap_boost = 1.3 if full_weekend_gap else 1.0
```

### 6.3 Regime Multiplier

```
M_regime:
  RISK_ON_EXPANSION:   1.00
  FRAGILE_RISK_ON:     1.15
  RISK_OFF_CORRECTION: 1.35
  CRISIS:              2.00
  RECOVERY:            1.05
  UNKNOWN:             1.10
```

### 6.4 Gap Multiplier

```
M_gap:
  if not (is_after_hours or is_weekend): M_gap = 1.00
  elif full_weekend_gap:
    M_gap = clip(1.2 + (hours_until_open / 60) × 0.3, 1.0, 1.5)
  else (regular after-hours):
    M_gap = 1.20
```

### 6.5 Severity Thresholds

```
composite_score ∈ [75, 100] → CRITICAL
composite_score ∈ [55,  75) → HIGH
composite_score ∈ [35,  55) → MEDIUM
composite_score ∈ [15,  35) → LOW
composite_score ∈ [ 0,  15) → INFORMATIONAL
```

---

## 7. Model Tradeoffs and Design Decisions

### 7.1 Speed vs. Interpretability

| Component | Fast Option | Rich Option | Choice Made | Rationale |
|-----------|------------|-------------|-------------|-----------|
| Language scoring | Lexicon (< 1ms) | LLM (1-30s) | Lexicon primary, transformer optional | Real-time requirement; interpretability for risk officers |
| Regime detection | Rule thresholds (< 1ms) | HMM (100ms) | Rules now, HMM in v1.1 | Stability over accuracy; fewer false positives |
| Scenario weights | Fixed scenarios | Full Monte Carlo | Named scenarios | Interpretable; PM can challenge specific scenarios |
| Impact estimation | Historical regression | ML model | Regression (calibrated percentiles) | Fewer parameters; no overfitting to sparse crisis data |

### 7.2 Precision vs. Recall for Catastrophic Events

For CRITICAL events (composite ≥ 75), the system is tuned toward **high recall over high precision**:

```
Cost of false negative (missing a true crisis) >>> Cost of false positive (unnecessary hedge)
```

This means the system may generate CRITICAL alerts that do not materialize as severe market moves. This is intentional and acceptable. The hedge recommendations are advisory (not automated), so a false positive costs only PM attention and option premium — not a forced deleveraging.

Minimum required recall@CRITICAL: **0.75** (must catch 75% of true crisis events)  
Maximum acceptable false positive rate: **40%** (at most 4 in 10 CRITICAL alerts are false alarms)

### 7.3 Static Rules vs. Learned Models

Key arguments for retaining rule-based layers:

1. **Sample size**: Crisis regimes have < 20 historical events; machine learning would overfit
2. **Auditability**: Risk officers and regulators can inspect and challenge a ruleset; they cannot inspect a neural network weight matrix
3. **Stability**: Rules are stable under model updates; ML models can shift behavior unexpectedly
4. **Speed**: Rules execute in microseconds; ML models require milliseconds to seconds

The transformer NLP layer is the only component where a learned model is primary, and even there, the lexicon scorer is the mandatory fallback.

---

## 8. Calibration Methodology

### 8.1 Lexicon Weights

Lexicon phrase weights were calibrated by:
1. Collecting all FOMC press conference transcripts 2010-2024
2. Labeling each event with a realized market severity (quartile of SPX next-day return)
3. Running logistic regression with phrase presence/absence as features
4. Using regression coefficients (rescaled to [-1, +1]) as phrase weights
5. Manual review and override for phrases with counterintuitive signs

Calibration frequency: **semi-annually** or after major communication style changes.

### 8.2 Vulnerability Percentile Calibration

Calibration percentiles (p10, p25, p50, p75, p90) are estimated from the historical distribution of each metric over the 2010-2024 period using the empirical CDF. Updates are triggered by:
- Structural market changes (e.g., post-COVID vol regime)
- Quarterly review showing significant distribution shift

### 8.3 Scenario Weight Calibration

Base scenario probabilities estimated from:
1. Count FOMC events by outcome severity (2010-2024)
2. Map outcome to named scenario using SPX return, VIX change, yield change
3. Compute empirical frequency as base probability
4. Adjust for known sample biases (crisis events over-weight in 2020-2022 subsample)

The conditioning update factors (direction, regime, urgency multipliers) are expert-calibrated, not statistically estimated, due to insufficient crisis data.
