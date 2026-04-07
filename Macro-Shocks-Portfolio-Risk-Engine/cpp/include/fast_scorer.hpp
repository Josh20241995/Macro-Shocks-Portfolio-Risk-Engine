/**
 * include/fast_scorer.hpp
 *
 * Fast Risk Scorer — C++ Implementation
 *
 * Mirrors the Python CompositeRiskScorer at sub-millisecond latency.
 * Used for streaming event evaluation where Python overhead is unacceptable.
 *
 * Design:
 * - No heap allocation in hot path
 * - All inputs passed by const reference or value
 * - No exceptions in scoring path (use error codes)
 * - Thread-safe (stateless computation)
 * - pybind11 bindings in cpp/bindings/fast_scorer_bindings.cpp
 *
 * Latency target: < 500 microseconds for full composite score
 */

#pragma once

#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <string_view>

namespace msre {

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

constexpr float SCORE_MIN = 0.0f;
constexpr float SCORE_MAX = 100.0f;
constexpr int N_SUB_SCORES = 9;

// Regime enum (mirrors Python RegimeType)
enum class Regime : uint8_t {
    RiskOnExpansion = 0,
    FragileRiskOn   = 1,
    RiskOffCorrection = 2,
    Crisis          = 3,
    Recovery        = 4,
    Unknown         = 5,
};

// Severity enum
enum class Severity : uint8_t {
    Informational = 0,
    Low           = 1,
    Medium        = 2,
    High          = 3,
    Critical      = 4,
};

// ---------------------------------------------------------------------------
// Input Structures (POD — no heap allocation)
// ---------------------------------------------------------------------------

struct MarketInputs {
    float vix_spot;                 // VIX index level
    float hy_spread_bps;            // HY CDX spread in bps
    float ig_spread_bps;            // IG CDX spread in bps
    float yield_2y;                 // 2-year yield
    float yield_10y;                // 10-year yield
    float bid_ask_spx_bps;          // SPX bid-ask spread in bps
    float ted_spread_bps;           // TED spread in bps
    float spx_from_52w_high;        // SPX drawdown from 52w high (negative)
    float advance_decline_ratio;    // Breadth A/D ratio
    float put_call_ratio;           // Options put/call ratio
    float vvix;                     // Vol-of-vol index
    Regime regime;                  // Pre-classified regime
};

struct SurpriseInputs {
    float composite_magnitude;      // [0, 1]
    float net_direction;            // [-1, +1]
    float rate_path_surprise;       // [-1, +1]
    float urgency_surprise;         // [0, 1]
    float financial_stability_surprise; // [-1, +1]
    bool  crisis_language_detected;
    bool  policy_reversal_language;
    bool  forward_guidance_changed;
};

struct EventInputs {
    bool  is_after_hours;
    bool  is_weekend;
    bool  full_weekend_gap;
    float hours_until_next_open;    // 0 if market open
    float event_severity_score;     // [0, 100]
};

struct ScenarioSummary {
    float expected_equity_impact_pct;
    float expected_yield_10y_bps;
    float expected_vix_change;
    float tail_loss_5pct;
    float tail_loss_1pct;
    float expected_liquidity_impairment;  // [0, 1]
    float tail_scenario_probability;      // sum of tail scenario probs
    float trading_halt_probability;
    float monday_gap_estimate_pct;        // 0 if not weekend event
};

// ---------------------------------------------------------------------------
// Output Structures
// ---------------------------------------------------------------------------

struct SubScore {
    float score;                    // [0, 100]
    float weighted_contribution;
    float weight;
};

struct CompositeScoreResult {
    float composite_score;          // [0, 100]
    Severity severity;
    Regime  regime;
    float   regime_multiplier;
    float   gap_risk_multiplier;

    // Sub-scores indexed by SubScoreIndex
    SubScore sub_scores[N_SUB_SCORES];

    // Error code: 0 = success
    int error_code;
};

// Sub-score index constants
enum SubScoreIndex : int {
    LIQUIDITY     = 0,
    VOLATILITY    = 1,
    RATE_SHOCK    = 2,
    EQUITY_DOWN   = 3,
    CREDIT_SPREAD = 4,
    FX_RISK       = 5,
    COMMODITY     = 6,
    WEEKEND_GAP   = 7,
    POLICY_AMBIG  = 8,
};

// ---------------------------------------------------------------------------
// Regime Weight Table (matches Python REGIME_WEIGHTS)
// ---------------------------------------------------------------------------
// Indexed as weights[Regime][SubScoreIndex]

constexpr float REGIME_WEIGHTS[6][N_SUB_SCORES] = {
    // RiskOnExpansion
    {0.10f, 0.10f, 0.22f, 0.22f, 0.12f, 0.08f, 0.05f, 0.06f, 0.05f},
    // FragileRiskOn
    {0.15f, 0.15f, 0.20f, 0.18f, 0.12f, 0.07f, 0.05f, 0.05f, 0.03f},
    // RiskOffCorrection
    {0.20f, 0.18f, 0.18f, 0.16f, 0.12f, 0.07f, 0.04f, 0.03f, 0.02f},
    // Crisis
    {0.28f, 0.18f, 0.15f, 0.12f, 0.12f, 0.07f, 0.03f, 0.03f, 0.02f},
    // Recovery
    {0.12f, 0.12f, 0.22f, 0.22f, 0.12f, 0.08f, 0.05f, 0.04f, 0.03f},
    // Unknown
    {0.15f, 0.15f, 0.20f, 0.18f, 0.12f, 0.08f, 0.05f, 0.04f, 0.03f},
};

constexpr float REGIME_MULTIPLIERS[6] = {
    1.00f,  // RiskOnExpansion
    1.15f,  // FragileRiskOn
    1.35f,  // RiskOffCorrection
    2.00f,  // Crisis
    1.05f,  // Recovery
    1.10f,  // Unknown
};

// ---------------------------------------------------------------------------
// FastRiskScorer — Core Scoring Class
// ---------------------------------------------------------------------------

class FastRiskScorer {
public:
    FastRiskScorer() = default;
    ~FastRiskScorer() = default;

    // Non-copyable for thread-safety clarity
    FastRiskScorer(const FastRiskScorer&) = delete;
    FastRiskScorer& operator=(const FastRiskScorer&) = delete;

    /**
     * Primary entry point. Computes the full composite risk score.
     * All computation is on the stack — no heap allocation.
     *
     * @param market    Pre-event market state inputs
     * @param surprise  Policy surprise vector inputs
     * @param event     Event timing and classification inputs
     * @param scenario  Scenario tree summary inputs
     * @return CompositeScoreResult
     */
    CompositeScoreResult score(
        const MarketInputs&   market,
        const SurpriseInputs& surprise,
        const EventInputs&    event,
        const ScenarioSummary& scenario
    ) const noexcept;

    /**
     * Compute only the composite score (faster path).
     * Use when sub-score decomposition is not needed.
     */
    float score_fast(
        const MarketInputs&   market,
        const SurpriseInputs& surprise,
        const EventInputs&    event,
        const ScenarioSummary& scenario
    ) const noexcept;

    /**
     * Classify regime from market inputs.
     * Mirrors Python MarketVulnerabilityScorer._classify_regime.
     */
    static Regime classify_regime(const MarketInputs& market) noexcept;

    /**
     * Convert composite score to severity level.
     */
    static Severity score_to_severity(float score) noexcept;

private:
    float score_liquidity(const MarketInputs&, const SurpriseInputs&, const ScenarioSummary&) const noexcept;
    float score_volatility(const MarketInputs&, const SurpriseInputs&, const ScenarioSummary&) const noexcept;
    float score_rate_shock(const MarketInputs&, const SurpriseInputs&, const ScenarioSummary&) const noexcept;
    float score_equity_downside(const MarketInputs&, const ScenarioSummary&) const noexcept;
    float score_credit_spread(const MarketInputs&, const ScenarioSummary&) const noexcept;
    float score_fx(const SurpriseInputs&, const ScenarioSummary&) const noexcept;
    float score_commodity(const ScenarioSummary&) const noexcept;
    float score_weekend_gap(const EventInputs&, const SurpriseInputs&) const noexcept;
    float score_policy_ambiguity(const SurpriseInputs&) const noexcept;

    float compute_gap_multiplier(const EventInputs&) const noexcept;

    static float percentile_rank(float value, float p10, float p25, float p50, float p75, float p90) noexcept;
    static float clamp(float v, float lo, float hi) noexcept;
};

// ---------------------------------------------------------------------------
// Inline Utility Implementations
// ---------------------------------------------------------------------------

inline float FastRiskScorer::clamp(float v, float lo, float hi) noexcept {
    return v < lo ? lo : (v > hi ? hi : v);
}

inline Severity FastRiskScorer::score_to_severity(float score) noexcept {
    if (score >= 75.0f) return Severity::Critical;
    if (score >= 55.0f) return Severity::High;
    if (score >= 35.0f) return Severity::Medium;
    if (score >= 15.0f) return Severity::Low;
    return Severity::Informational;
}

inline Regime FastRiskScorer::classify_regime(const MarketInputs& m) noexcept {
    // Mirror of Python _classify_regime — same threshold logic
    // Simplified: uses VIX and HY spread as primary regime signals
    float vix_vuln = percentile_rank(m.vix_spot, 12.0f, 15.0f, 18.5f, 25.0f, 35.0f);
    float credit_vuln = percentile_rank(m.hy_spread_bps, 250.0f, 320.0f, 420.0f, 550.0f, 700.0f);
    float liq_vuln = percentile_rank(m.bid_ask_spx_bps, 0.5f, 1.0f, 1.5f, 3.0f, 6.0f);

    if (vix_vuln > 0.80f && credit_vuln > 0.70f && liq_vuln > 0.70f) return Regime::Crisis;
    float composite = (vix_vuln * 0.35f + credit_vuln * 0.35f + liq_vuln * 0.30f);
    if (composite > 0.65f) return Regime::RiskOffCorrection;
    if (composite < 0.30f) return Regime::RiskOnExpansion;
    return Regime::FragileRiskOn;
}

inline float FastRiskScorer::percentile_rank(
    float value, float p10, float p25, float p50, float p75, float p90
) noexcept {
    if (value <= p10) return 0.0f;
    if (value >= p90) return 1.0f;
    float knots_x[5] = {p10, p25, p50, p75, p90};
    float knots_y[5] = {0.10f, 0.25f, 0.50f, 0.75f, 0.90f};
    for (int i = 0; i < 4; ++i) {
        if (knots_x[i] <= value && value <= knots_x[i+1]) {
            float t = (value - knots_x[i]) / (knots_x[i+1] - knots_x[i]);
            return knots_y[i] + t * (knots_y[i+1] - knots_y[i]);
        }
    }
    return 0.5f;
}

} // namespace msre
