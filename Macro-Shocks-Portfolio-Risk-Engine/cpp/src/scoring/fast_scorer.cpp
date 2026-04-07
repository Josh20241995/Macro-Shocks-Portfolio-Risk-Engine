/**
 * src/scoring/fast_scorer.cpp
 *
 * Fast Risk Scorer Implementation.
 * See fast_scorer.hpp for interface documentation.
 */

#include "fast_scorer.hpp"
#include <cmath>
#include <algorithm>

namespace msre {

// ---------------------------------------------------------------------------
// Public Interface
// ---------------------------------------------------------------------------

CompositeScoreResult FastRiskScorer::score(
    const MarketInputs&    market,
    const SurpriseInputs&  surprise,
    const EventInputs&     event,
    const ScenarioSummary& scenario
) const noexcept {
    CompositeScoreResult result{};
    result.error_code = 0;
    result.regime = market.regime;

    const int ri = static_cast<int>(market.regime);
    const float* weights = REGIME_WEIGHTS[ri];
    result.regime_multiplier  = REGIME_MULTIPLIERS[ri];
    result.gap_risk_multiplier = compute_gap_multiplier(event);

    // Compute each sub-score
    result.sub_scores[LIQUIDITY]     = {score_liquidity(market, surprise, scenario),  0.0f, weights[LIQUIDITY]};
    result.sub_scores[VOLATILITY]    = {score_volatility(market, surprise, scenario), 0.0f, weights[VOLATILITY]};
    result.sub_scores[RATE_SHOCK]    = {score_rate_shock(market, surprise, scenario), 0.0f, weights[RATE_SHOCK]};
    result.sub_scores[EQUITY_DOWN]   = {score_equity_downside(market, scenario),      0.0f, weights[EQUITY_DOWN]};
    result.sub_scores[CREDIT_SPREAD] = {score_credit_spread(market, scenario),        0.0f, weights[CREDIT_SPREAD]};
    result.sub_scores[FX_RISK]       = {score_fx(surprise, scenario),                0.0f, weights[FX_RISK]};
    result.sub_scores[COMMODITY]     = {score_commodity(scenario),                    0.0f, weights[COMMODITY]};
    result.sub_scores[WEEKEND_GAP]   = {score_weekend_gap(event, surprise),           0.0f, weights[WEEKEND_GAP]};
    result.sub_scores[POLICY_AMBIG]  = {score_policy_ambiguity(surprise),             0.0f, weights[POLICY_AMBIG]};

    // Compute weighted contributions
    float raw_composite = 0.0f;
    for (int i = 0; i < N_SUB_SCORES; ++i) {
        result.sub_scores[i].weighted_contribution =
            result.sub_scores[i].score * result.sub_scores[i].weight;
        raw_composite += result.sub_scores[i].weighted_contribution;
    }

    // Apply multipliers and clamp
    result.composite_score = clamp(
        raw_composite * result.regime_multiplier * result.gap_risk_multiplier,
        SCORE_MIN, SCORE_MAX
    );
    result.severity = score_to_severity(result.composite_score);

    return result;
}

float FastRiskScorer::score_fast(
    const MarketInputs&    market,
    const SurpriseInputs&  surprise,
    const EventInputs&     event,
    const ScenarioSummary& scenario
) const noexcept {
    auto result = score(market, surprise, event, scenario);
    return result.composite_score;
}

// ---------------------------------------------------------------------------
// Sub-Score Implementations
// ---------------------------------------------------------------------------

float FastRiskScorer::score_liquidity(
    const MarketInputs&    m,
    const SurpriseInputs&  s,
    const ScenarioSummary& sc
) const noexcept {
    // Component 1: Pre-event bid-ask stress
    float liq_vuln = percentile_rank(m.bid_ask_spx_bps, 0.5f, 1.0f, 1.5f, 3.0f, 6.0f);
    float c1 = liq_vuln * 50.0f;

    // Component 2: Expected liquidity impairment from scenario tree
    float c2 = sc.expected_liquidity_impairment * 30.0f;

    // Component 3: Urgency signal
    float c3 = s.urgency_surprise * 20.0f;

    return clamp(c1 + c2 + c3, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::score_volatility(
    const MarketInputs&    m,
    const SurpriseInputs&  s,
    const ScenarioSummary& sc
) const noexcept {
    // Component 1: Current VIX level
    float vix_score = clamp((m.vix_spot - 12.0f) / (40.0f - 12.0f) * 35.0f, 0.0f, 35.0f);

    // Component 2: Expected VIX change (positive only)
    float exp_vix_pos = std::fmax(sc.expected_vix_change, 0.0f);
    float c2 = clamp(exp_vix_pos / 20.0f * 35.0f, 0.0f, 35.0f);

    // Component 3: Surprise magnitude
    float c3 = s.composite_magnitude * 30.0f;

    return clamp(vix_score + c2 + c3, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::score_rate_shock(
    const MarketInputs&    m,
    const SurpriseInputs&  s,
    const ScenarioSummary& sc
) const noexcept {
    // Component 1: Rate path surprise magnitude
    float c1 = std::fabs(s.rate_path_surprise) * 40.0f;

    // Component 2: Expected 10Y yield change magnitude
    float exp_yld = std::fabs(sc.expected_yield_10y_bps);
    float c2 = clamp(exp_yld / 30.0f * 35.0f, 0.0f, 35.0f);

    // Component 3: Yield curve context (inversion amplifies rate shock)
    float slope_bps = (m.yield_10y - m.yield_2y) * 100.0f;
    float c3 = slope_bps < 0.0f ? clamp(std::fabs(slope_bps) / 100.0f * 25.0f, 0.0f, 25.0f) : 5.0f;

    return clamp(c1 + c2 + c3, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::score_equity_downside(
    const MarketInputs&    m,
    const ScenarioSummary& sc
) const noexcept {
    // Component 1: Expected equity downside (negative scenarios only)
    float neg_exp = std::fmax(-sc.expected_equity_impact_pct, 0.0f);
    float c1 = clamp(neg_exp / 5.0f * 40.0f, 0.0f, 40.0f);

    // Component 2: Tail loss severity
    float tail_sev = std::fabs(std::fmin(sc.tail_loss_5pct, 0.0f));
    float c2 = clamp(tail_sev / 10.0f * 35.0f, 0.0f, 35.0f);

    // Component 3: Pre-existing drawdown vulnerability
    float drawdown = std::fabs(std::fmin(m.spx_from_52w_high, 0.0f));
    float c3 = clamp(drawdown / 0.20f * 25.0f, 0.0f, 25.0f);

    return clamp(c1 + c2 + c3, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::score_credit_spread(
    const MarketInputs&    m,
    const ScenarioSummary& sc
) const noexcept {
    // Component 1: Pre-event HY spread level
    float hy_vuln = percentile_rank(m.hy_spread_bps, 250.0f, 320.0f, 420.0f, 550.0f, 700.0f);
    float c1 = hy_vuln * 40.0f;

    // Component 2: Tail scenario probability (proxy for spread widening risk)
    float c2 = sc.tail_scenario_probability * 35.0f;

    // Component 3: Trading halt probability as contagion signal
    float c3 = sc.trading_halt_probability * 25.0f;

    return clamp(c1 + c2 + c3, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::score_fx(
    const SurpriseInputs&  s,
    const ScenarioSummary& sc
) const noexcept {
    // FX score: driven by surprise direction/magnitude
    float c1 = s.composite_magnitude * 50.0f;
    float c2 = std::fabs(s.financial_stability_surprise) > 0.3f
               ? std::fabs(s.financial_stability_surprise) * 20.0f
               : 3.0f;
    return clamp(c1 + c2, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::score_commodity(
    const ScenarioSummary& sc
) const noexcept {
    // Simplified: use tail scenario probability as proxy
    return clamp(sc.tail_scenario_probability * 60.0f + 5.0f, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::score_weekend_gap(
    const EventInputs&    e,
    const SurpriseInputs& s
) const noexcept {
    if (!e.is_after_hours && !e.is_weekend) return 0.0f;

    // Component 1: Gap duration score
    float max_gap_hours = 60.0f;
    float duration_score = clamp(e.hours_until_next_open / max_gap_hours * 40.0f, 0.0f, 40.0f);

    // Component 2: Surprise during gap
    float gap_boost = e.full_weekend_gap ? 1.3f : 1.0f;
    float c2 = clamp(s.composite_magnitude * 30.0f * gap_boost, 0.0f, 30.0f);

    // Component 3: Urgency during gap
    float c3 = s.urgency_surprise * 30.0f;

    return clamp(duration_score + c2 + c3, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::score_policy_ambiguity(
    const SurpriseInputs& s
) const noexcept {
    // Low surprise confidence = high ambiguity
    // Note: confidence not directly in SurpriseInputs; approximate from magnitude/direction
    float ambiguity_proxy = 1.0f - std::fabs(s.net_direction);  // Low directional signal = ambiguous
    float c1 = ambiguity_proxy * 40.0f;
    float c2 = s.forward_guidance_changed ? 30.0f : 5.0f;
    float c3 = s.policy_reversal_language ? 30.0f : 5.0f;

    return clamp(c1 + c2 + c3, SCORE_MIN, SCORE_MAX);
}

float FastRiskScorer::compute_gap_multiplier(const EventInputs& e) const noexcept {
    if (!e.is_after_hours && !e.is_weekend) return 1.0f;
    if (e.full_weekend_gap) {
        float hours = e.hours_until_next_open > 0.0f ? e.hours_until_next_open : 60.0f;
        return clamp(1.2f + (hours / 60.0f) * 0.3f, 1.0f, 1.5f);
    }
    return 1.2f;
}

} // namespace msre
