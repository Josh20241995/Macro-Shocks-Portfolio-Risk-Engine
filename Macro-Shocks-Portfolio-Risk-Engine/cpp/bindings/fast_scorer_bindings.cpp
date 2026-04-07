/**
 * cpp/bindings/fast_scorer_bindings.cpp
 *
 * pybind11 Python bindings for the FastRiskScorer.
 *
 * After building, the module is importable from Python as:
 *   import msre_fast_scorer as fast
 *   result = fast.score(market, surprise, event, scenario)
 *
 * Build: cmake -B build && cmake --build build
 * Install: cmake --install build (copies to python/src/macro_shock/risk_scoring/)
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "fast_scorer.hpp"

namespace py = pybind11;
using namespace msre;

PYBIND11_MODULE(msre_fast_scorer, m) {
    m.doc() = "Macro Shock Risk Engine — C++ Fast Risk Scorer";

    // ---------------------------------------------------------------------------
    // Enums
    // ---------------------------------------------------------------------------

    py::enum_<Regime>(m, "Regime")
        .value("RiskOnExpansion",   Regime::RiskOnExpansion)
        .value("FragileRiskOn",     Regime::FragileRiskOn)
        .value("RiskOffCorrection", Regime::RiskOffCorrection)
        .value("Crisis",            Regime::Crisis)
        .value("Recovery",          Regime::Recovery)
        .value("Unknown",           Regime::Unknown)
        .export_values();

    py::enum_<Severity>(m, "Severity")
        .value("Informational", Severity::Informational)
        .value("Low",           Severity::Low)
        .value("Medium",        Severity::Medium)
        .value("High",          Severity::High)
        .value("Critical",      Severity::Critical)
        .export_values();

    // ---------------------------------------------------------------------------
    // Input Structs
    // ---------------------------------------------------------------------------

    py::class_<MarketInputs>(m, "MarketInputs")
        .def(py::init<>())
        .def_readwrite("vix_spot",              &MarketInputs::vix_spot)
        .def_readwrite("hy_spread_bps",         &MarketInputs::hy_spread_bps)
        .def_readwrite("ig_spread_bps",         &MarketInputs::ig_spread_bps)
        .def_readwrite("yield_2y",              &MarketInputs::yield_2y)
        .def_readwrite("yield_10y",             &MarketInputs::yield_10y)
        .def_readwrite("bid_ask_spx_bps",       &MarketInputs::bid_ask_spx_bps)
        .def_readwrite("ted_spread_bps",        &MarketInputs::ted_spread_bps)
        .def_readwrite("spx_from_52w_high",     &MarketInputs::spx_from_52w_high)
        .def_readwrite("advance_decline_ratio", &MarketInputs::advance_decline_ratio)
        .def_readwrite("put_call_ratio",        &MarketInputs::put_call_ratio)
        .def_readwrite("vvix",                  &MarketInputs::vvix)
        .def_readwrite("regime",                &MarketInputs::regime)
        .def("__repr__", [](const MarketInputs& m) {
            return "<MarketInputs vix=" + std::to_string(m.vix_spot)
                 + " hy=" + std::to_string(m.hy_spread_bps) + "bps>";
        });

    py::class_<SurpriseInputs>(m, "SurpriseInputs")
        .def(py::init<>())
        .def_readwrite("composite_magnitude",          &SurpriseInputs::composite_magnitude)
        .def_readwrite("net_direction",                &SurpriseInputs::net_direction)
        .def_readwrite("rate_path_surprise",           &SurpriseInputs::rate_path_surprise)
        .def_readwrite("urgency_surprise",             &SurpriseInputs::urgency_surprise)
        .def_readwrite("financial_stability_surprise", &SurpriseInputs::financial_stability_surprise)
        .def_readwrite("crisis_language_detected",     &SurpriseInputs::crisis_language_detected)
        .def_readwrite("policy_reversal_language",     &SurpriseInputs::policy_reversal_language)
        .def_readwrite("forward_guidance_changed",     &SurpriseInputs::forward_guidance_changed);

    py::class_<EventInputs>(m, "EventInputs")
        .def(py::init<>())
        .def_readwrite("is_after_hours",        &EventInputs::is_after_hours)
        .def_readwrite("is_weekend",            &EventInputs::is_weekend)
        .def_readwrite("full_weekend_gap",      &EventInputs::full_weekend_gap)
        .def_readwrite("hours_until_next_open", &EventInputs::hours_until_next_open)
        .def_readwrite("event_severity_score",  &EventInputs::event_severity_score);

    py::class_<ScenarioSummary>(m, "ScenarioSummary")
        .def(py::init<>())
        .def_readwrite("expected_equity_impact_pct",    &ScenarioSummary::expected_equity_impact_pct)
        .def_readwrite("expected_yield_10y_bps",        &ScenarioSummary::expected_yield_10y_bps)
        .def_readwrite("expected_vix_change",           &ScenarioSummary::expected_vix_change)
        .def_readwrite("tail_loss_5pct",                &ScenarioSummary::tail_loss_5pct)
        .def_readwrite("tail_loss_1pct",                &ScenarioSummary::tail_loss_1pct)
        .def_readwrite("expected_liquidity_impairment", &ScenarioSummary::expected_liquidity_impairment)
        .def_readwrite("tail_scenario_probability",     &ScenarioSummary::tail_scenario_probability)
        .def_readwrite("trading_halt_probability",      &ScenarioSummary::trading_halt_probability)
        .def_readwrite("monday_gap_estimate_pct",       &ScenarioSummary::monday_gap_estimate_pct);

    // ---------------------------------------------------------------------------
    // Output Structs
    // ---------------------------------------------------------------------------

    py::class_<SubScore>(m, "SubScore")
        .def_readonly("score",                &SubScore::score)
        .def_readonly("weighted_contribution",&SubScore::weighted_contribution)
        .def_readonly("weight",               &SubScore::weight);

    py::class_<CompositeScoreResult>(m, "CompositeScoreResult")
        .def_readonly("composite_score",      &CompositeScoreResult::composite_score)
        .def_readonly("severity",             &CompositeScoreResult::severity)
        .def_readonly("regime",               &CompositeScoreResult::regime)
        .def_readonly("regime_multiplier",    &CompositeScoreResult::regime_multiplier)
        .def_readonly("gap_risk_multiplier",  &CompositeScoreResult::gap_risk_multiplier)
        .def_readonly("error_code",           &CompositeScoreResult::error_code)
        .def("get_sub_score", [](const CompositeScoreResult& r, int idx) {
            if (idx < 0 || idx >= N_SUB_SCORES)
                throw py::index_error("Sub-score index out of range [0, 8]");
            return r.sub_scores[idx];
        })
        .def("__repr__", [](const CompositeScoreResult& r) {
            return "<CompositeScoreResult score=" + std::to_string(r.composite_score)
                 + " err=" + std::to_string(r.error_code) + ">";
        });

    // ---------------------------------------------------------------------------
    // FastRiskScorer
    // ---------------------------------------------------------------------------

    py::class_<FastRiskScorer>(m, "FastRiskScorer")
        .def(py::init<>())
        .def("score", &FastRiskScorer::score,
             py::arg("market"), py::arg("surprise"),
             py::arg("event"), py::arg("scenario"),
             "Compute full composite risk score with all sub-scores.")
        .def("score_fast", &FastRiskScorer::score_fast,
             py::arg("market"), py::arg("surprise"),
             py::arg("event"), py::arg("scenario"),
             "Compute composite score only (faster path, no sub-score decomposition).")
        .def_static("classify_regime", &FastRiskScorer::classify_regime,
             py::arg("market"),
             "Classify market regime from inputs.")
        .def_static("score_to_severity", &FastRiskScorer::score_to_severity,
             py::arg("score"),
             "Convert composite score to Severity enum.");

    // ---------------------------------------------------------------------------
    // Sub-score index constants
    // ---------------------------------------------------------------------------
    m.attr("LIQUIDITY")     = SubScoreIndex::LIQUIDITY;
    m.attr("VOLATILITY")    = SubScoreIndex::VOLATILITY;
    m.attr("RATE_SHOCK")    = SubScoreIndex::RATE_SHOCK;
    m.attr("EQUITY_DOWN")   = SubScoreIndex::EQUITY_DOWN;
    m.attr("CREDIT_SPREAD") = SubScoreIndex::CREDIT_SPREAD;
    m.attr("FX_RISK")       = SubScoreIndex::FX_RISK;
    m.attr("COMMODITY")     = SubScoreIndex::COMMODITY;
    m.attr("WEEKEND_GAP")   = SubScoreIndex::WEEKEND_GAP;
    m.attr("POLICY_AMBIG")  = SubScoreIndex::POLICY_AMBIG;
    m.attr("N_SUB_SCORES")  = N_SUB_SCORES;

    m.attr("__version__") = "1.0.0";
}
