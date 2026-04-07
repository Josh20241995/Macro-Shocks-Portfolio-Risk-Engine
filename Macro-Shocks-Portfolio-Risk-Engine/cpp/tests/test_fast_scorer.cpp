/**
 * tests/test_fast_scorer.cpp
 *
 * Unit tests for the FastRiskScorer.
 * Uses Catch2 v3 test framework.
 */

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include "fast_scorer.hpp"

using namespace msre;
using Catch::Matchers::WithinAbs;
using Catch::Matchers::WithinRel;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

MarketInputs make_normal_market() {
    return MarketInputs{
        .vix_spot               = 16.0f,
        .hy_spread_bps          = 380.0f,
        .ig_spread_bps          = 85.0f,
        .yield_2y               = 4.5f,
        .yield_10y              = 4.0f,
        .bid_ask_spx_bps        = 1.2f,
        .ted_spread_bps         = 18.0f,
        .spx_from_52w_high      = -0.03f,
        .advance_decline_ratio  = 0.55f,
        .put_call_ratio         = 0.82f,
        .vvix                   = 93.0f,
        .regime                 = Regime::FragileRiskOn,
    };
}

MarketInputs make_crisis_market() {
    return MarketInputs{
        .vix_spot               = 45.0f,
        .hy_spread_bps          = 820.0f,
        .ig_spread_bps          = 210.0f,
        .yield_2y               = 3.5f,
        .yield_10y              = 3.0f,
        .bid_ask_spx_bps        = 7.5f,
        .ted_spread_bps         = 95.0f,
        .spx_from_52w_high      = -0.32f,
        .advance_decline_ratio  = 0.18f,
        .put_call_ratio         = 1.4f,
        .vvix                   = 140.0f,
        .regime                 = Regime::Crisis,
    };
}

SurpriseInputs make_large_hawkish_surprise() {
    return SurpriseInputs{
        .composite_magnitude            = 0.80f,
        .net_direction                  = 0.75f,
        .rate_path_surprise             = 0.75f,
        .urgency_surprise               = 0.50f,
        .financial_stability_surprise   = 0.20f,
        .crisis_language_detected       = false,
        .policy_reversal_language       = false,
        .forward_guidance_changed       = true,
    };
}

SurpriseInputs make_emergency_crisis_surprise() {
    return SurpriseInputs{
        .composite_magnitude            = 0.95f,
        .net_direction                  = -0.90f,
        .rate_path_surprise             = -0.90f,
        .urgency_surprise               = 0.95f,
        .financial_stability_surprise   = -0.85f,
        .crisis_language_detected       = true,
        .policy_reversal_language       = true,
        .forward_guidance_changed       = true,
    };
}

SurpriseInputs make_benign_surprise() {
    return SurpriseInputs{
        .composite_magnitude            = 0.10f,
        .net_direction                  = 0.05f,
        .rate_path_surprise             = 0.05f,
        .urgency_surprise               = 0.02f,
        .financial_stability_surprise   = 0.0f,
        .crisis_language_detected       = false,
        .policy_reversal_language       = false,
        .forward_guidance_changed       = false,
    };
}

EventInputs make_weekday_intraday_event() {
    return EventInputs{
        .is_after_hours         = false,
        .is_weekend             = false,
        .full_weekend_gap       = false,
        .hours_until_next_open  = 0.0f,
        .event_severity_score   = 60.0f,
    };
}

EventInputs make_weekend_event() {
    return EventInputs{
        .is_after_hours         = false,
        .is_weekend             = true,
        .full_weekend_gap       = true,
        .hours_until_next_open  = 55.0f,
        .event_severity_score   = 90.0f,
    };
}

ScenarioSummary make_benign_scenario() {
    return ScenarioSummary{
        .expected_equity_impact_pct     = -0.5f,
        .expected_yield_10y_bps         = 3.0f,
        .expected_vix_change            = 0.5f,
        .tail_loss_5pct                 = -1.5f,
        .tail_loss_1pct                 = -3.0f,
        .expected_liquidity_impairment  = 0.02f,
        .tail_scenario_probability      = 0.04f,
        .trading_halt_probability       = 0.0f,
        .monday_gap_estimate_pct        = 0.0f,
    };
}

ScenarioSummary make_severe_scenario() {
    return ScenarioSummary{
        .expected_equity_impact_pct     = -6.5f,
        .expected_yield_10y_bps         = 25.0f,
        .expected_vix_change            = 18.0f,
        .tail_loss_5pct                 = -12.0f,
        .tail_loss_1pct                 = -22.0f,
        .expected_liquidity_impairment  = 0.70f,
        .tail_scenario_probability      = 0.35f,
        .trading_halt_probability       = 0.12f,
        .monday_gap_estimate_pct        = -8.0f,
    };
}


// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

TEST_CASE("Score is always in [0, 100]", "[fast_scorer][bounds]") {
    FastRiskScorer scorer;

    SECTION("Normal market, benign surprise") {
        auto result = scorer.score(
            make_normal_market(), make_benign_surprise(),
            make_weekday_intraday_event(), make_benign_scenario()
        );
        REQUIRE(result.composite_score >= 0.0f);
        REQUIRE(result.composite_score <= 100.0f);
        REQUIRE(result.error_code == 0);
    }

    SECTION("Crisis market, emergency surprise, weekend") {
        auto result = scorer.score(
            make_crisis_market(), make_emergency_crisis_surprise(),
            make_weekend_event(), make_severe_scenario()
        );
        REQUIRE(result.composite_score >= 0.0f);
        REQUIRE(result.composite_score <= 100.0f);
        REQUIRE(result.error_code == 0);
    }
}

TEST_CASE("Crisis scenario scores higher than benign", "[fast_scorer][ordering]") {
    FastRiskScorer scorer;

    auto benign = scorer.score_fast(
        make_normal_market(), make_benign_surprise(),
        make_weekday_intraday_event(), make_benign_scenario()
    );
    auto crisis = scorer.score_fast(
        make_crisis_market(), make_emergency_crisis_surprise(),
        make_weekend_event(), make_severe_scenario()
    );

    REQUIRE(crisis > benign);
    REQUIRE(crisis > 70.0f);   // Should be CRITICAL
    REQUIRE(benign < 45.0f);   // Should be LOW-MEDIUM
}

TEST_CASE("Weekend gap multiplier is applied", "[fast_scorer][gap_risk]") {
    FastRiskScorer scorer;

    auto market = make_normal_market();
    auto surprise = make_large_hawkish_surprise();
    auto scenario = make_severe_scenario();

    auto intraday = scorer.score(market, surprise, make_weekday_intraday_event(), scenario);
    auto weekend  = scorer.score(market, surprise, make_weekend_event(), scenario);

    // Weekend event should score higher due to gap multiplier
    REQUIRE(weekend.composite_score > intraday.composite_score);
    REQUIRE(weekend.gap_risk_multiplier > 1.0f);
    REQUIRE(intraday.gap_risk_multiplier == 1.0f);
}

TEST_CASE("Regime multiplier is correct", "[fast_scorer][regime]") {
    FastRiskScorer scorer;

    auto surprise = make_large_hawkish_surprise();
    auto event = make_weekday_intraday_event();
    auto scenario = make_severe_scenario();

    MarketInputs normal_market = make_normal_market();
    normal_market.regime = Regime::RiskOnExpansion;

    MarketInputs crisis_market = make_crisis_market();
    crisis_market.regime = Regime::Crisis;

    auto normal_result = scorer.score(normal_market, surprise, event, scenario);
    auto crisis_result = scorer.score(crisis_market, surprise, event, scenario);

    REQUIRE(normal_result.regime_multiplier == 1.0f);
    REQUIRE(crisis_result.regime_multiplier == 2.0f);
    REQUIRE(crisis_result.composite_score > normal_result.composite_score);
}

TEST_CASE("Severity classification is consistent", "[fast_scorer][severity]") {
    REQUIRE(FastRiskScorer::score_to_severity(0.0f)  == Severity::Informational);
    REQUIRE(FastRiskScorer::score_to_severity(14.9f) == Severity::Informational);
    REQUIRE(FastRiskScorer::score_to_severity(15.0f) == Severity::Low);
    REQUIRE(FastRiskScorer::score_to_severity(34.9f) == Severity::Low);
    REQUIRE(FastRiskScorer::score_to_severity(35.0f) == Severity::Medium);
    REQUIRE(FastRiskScorer::score_to_severity(54.9f) == Severity::Medium);
    REQUIRE(FastRiskScorer::score_to_severity(55.0f) == Severity::High);
    REQUIRE(FastRiskScorer::score_to_severity(74.9f) == Severity::High);
    REQUIRE(FastRiskScorer::score_to_severity(75.0f) == Severity::Critical);
    REQUIRE(FastRiskScorer::score_to_severity(100.0f) == Severity::Critical);
}

TEST_CASE("Regime classification", "[fast_scorer][regime_classify]") {
    MarketInputs calm = make_normal_market();
    calm.vix_spot = 13.0f;
    calm.hy_spread_bps = 290.0f;
    calm.bid_ask_spx_bps = 0.8f;
    REQUIRE(FastRiskScorer::classify_regime(calm) == Regime::RiskOnExpansion);

    MarketInputs stressed = make_normal_market();
    stressed.vix_spot = 30.0f;
    stressed.hy_spread_bps = 580.0f;
    stressed.bid_ask_spx_bps = 4.5f;
    REQUIRE(FastRiskScorer::classify_regime(stressed) == Regime::RiskOffCorrection);

    REQUIRE(FastRiskScorer::classify_regime(make_crisis_market()) == Regime::Crisis);
}

TEST_CASE("Sub-score count is correct", "[fast_scorer][sub_scores]") {
    FastRiskScorer scorer;
    auto result = scorer.score(
        make_normal_market(), make_large_hawkish_surprise(),
        make_weekday_intraday_event(), make_severe_scenario()
    );
    // All sub-scores should be in [0, 100]
    for (int i = 0; i < N_SUB_SCORES; ++i) {
        REQUIRE(result.sub_scores[i].score >= 0.0f);
        REQUIRE(result.sub_scores[i].score <= 100.0f);
        REQUIRE(result.sub_scores[i].weight > 0.0f);
    }
}

TEST_CASE("score_fast matches full score composite", "[fast_scorer][consistency]") {
    FastRiskScorer scorer;
    auto market   = make_normal_market();
    auto surprise = make_large_hawkish_surprise();
    auto event    = make_weekend_event();
    auto scenario = make_severe_scenario();

    float fast   = scorer.score_fast(market, surprise, event, scenario);
    auto  full   = scorer.score(market, surprise, event, scenario);

    REQUIRE_THAT(fast, WithinAbs(full.composite_score, 0.001f));
}

TEST_CASE("Deterministic: same inputs same output", "[fast_scorer][determinism]") {
    FastRiskScorer scorer;
    auto market   = make_crisis_market();
    auto surprise = make_emergency_crisis_surprise();
    auto event    = make_weekend_event();
    auto scenario = make_severe_scenario();

    float score1 = scorer.score_fast(market, surprise, event, scenario);
    float score2 = scorer.score_fast(market, surprise, event, scenario);
    float score3 = scorer.score_fast(market, surprise, event, scenario);

    REQUIRE_THAT(score1, WithinAbs(score2, 0.0001f));
    REQUIRE_THAT(score2, WithinAbs(score3, 0.0001f));
}
