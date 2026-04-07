"""
risk_scoring/composite_scorer.py

Composite Macro Shock Risk Scoring Engine.

Produces the primary output of the MSRE: a Composite Risk Score [0-100]
decomposed into nine sub-scores with full explainability.

Score Architecture:
  R_composite = Σ(w_i × S_i) × RegimeMultiplier × GapRiskMultiplier

Sub-scores:
  1. Liquidity Risk
  2. Volatility Risk
  3. Rate Shock Risk
  4. Equity Downside Risk
  5. Credit Spread Risk
  6. FX Risk
  7. Commodity Shock Risk
  8. Weekend Gap Risk
  9. Policy Ambiguity Risk

Each sub-score is [0, 100]. Weights are regime-conditioned.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import structlog

from macro_shock.data_schema.models import (
    AlertLevel,
    CompositeRiskScore,
    MacroEvent,
    MarketStateSnapshot,
    PolicySurpriseVector,
    RegimeType,
    ScenarioTree,
    SeverityLevel,
    SubRiskScore,
)
from macro_shock.market_context.vulnerability_scorer import VulnerabilityComponents

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Regime-Conditioned Sub-Score Weights
# ---------------------------------------------------------------------------
# Weights are tuned to reflect what drives market moves in each regime.
# Sum of weights should equal 1.0 for each regime.

REGIME_WEIGHTS: Dict[RegimeType, Dict[str, float]] = {
    RegimeType.RISK_ON_EXPANSION: {
        "liquidity": 0.10,
        "volatility": 0.10,
        "rate_shock": 0.22,
        "equity_downside": 0.22,
        "credit_spread": 0.12,
        "fx": 0.08,
        "commodity": 0.05,
        "weekend_gap": 0.06,
        "policy_ambiguity": 0.05,
    },
    RegimeType.FRAGILE_RISK_ON: {
        "liquidity": 0.15,
        "volatility": 0.15,
        "rate_shock": 0.20,
        "equity_downside": 0.18,
        "credit_spread": 0.12,
        "fx": 0.07,
        "commodity": 0.05,
        "weekend_gap": 0.05,
        "policy_ambiguity": 0.03,
    },
    RegimeType.RISK_OFF_CORRECTION: {
        "liquidity": 0.20,
        "volatility": 0.18,
        "rate_shock": 0.18,
        "equity_downside": 0.16,
        "credit_spread": 0.12,
        "fx": 0.07,
        "commodity": 0.04,
        "weekend_gap": 0.03,
        "policy_ambiguity": 0.02,
    },
    RegimeType.CRISIS: {
        "liquidity": 0.28,
        "volatility": 0.18,
        "rate_shock": 0.15,
        "equity_downside": 0.12,
        "credit_spread": 0.12,
        "fx": 0.07,
        "commodity": 0.03,
        "weekend_gap": 0.03,
        "policy_ambiguity": 0.02,
    },
    RegimeType.RECOVERY: {
        "liquidity": 0.12,
        "volatility": 0.12,
        "rate_shock": 0.22,
        "equity_downside": 0.22,
        "credit_spread": 0.12,
        "fx": 0.08,
        "commodity": 0.05,
        "weekend_gap": 0.04,
        "policy_ambiguity": 0.03,
    },
    RegimeType.UNKNOWN: {
        "liquidity": 0.15,
        "volatility": 0.15,
        "rate_shock": 0.20,
        "equity_downside": 0.18,
        "credit_spread": 0.12,
        "fx": 0.08,
        "commodity": 0.05,
        "weekend_gap": 0.04,
        "policy_ambiguity": 0.03,
    },
}

# ---------------------------------------------------------------------------
# Regime and Gap Multipliers
# ---------------------------------------------------------------------------

REGIME_MULTIPLIERS: Dict[RegimeType, float] = {
    RegimeType.RISK_ON_EXPANSION: 1.00,
    RegimeType.FRAGILE_RISK_ON: 1.15,
    RegimeType.RISK_OFF_CORRECTION: 1.35,
    RegimeType.CRISIS: 2.00,
    RegimeType.RECOVERY: 1.05,
    RegimeType.UNKNOWN: 1.10,
}


class CompositeRiskScorer:
    """
    Primary risk scoring engine.

    Computes the Composite Macro Shock Risk Score and all sub-scores
    from the policy surprise vector, market state, scenario tree,
    and vulnerability components.

    All scores are deterministic given the same inputs (no stochastic elements).
    This is by design: risk scoring must be reproducible and auditable.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.min_data_quality_for_high_confidence = self.config.get(
            "min_data_quality_high_confidence", 0.75
        )

    def score(
        self,
        event: MacroEvent,
        surprise_vector: PolicySurpriseVector,
        market_state: MarketStateSnapshot,
        vulnerability: VulnerabilityComponents,
        scenario_tree: ScenarioTree,
    ) -> CompositeRiskScore:
        """
        Compute the full composite risk score.

        Args:
            event: Classified macro event.
            surprise_vector: NLP-derived policy surprise vector.
            market_state: Pre-event market state snapshot.
            vulnerability: Market vulnerability assessment.
            scenario_tree: Probability-weighted scenario tree.

        Returns:
            CompositeRiskScore with full decomposition and explainability.
        """
        regime = vulnerability.regime
        weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS[RegimeType.UNKNOWN])
        regime_mult = REGIME_MULTIPLIERS.get(regime, 1.10)
        gap_mult = self._compute_gap_multiplier(event)

        # Compute each sub-score
        liquidity_ss = self._score_liquidity(
            surprise_vector, market_state, vulnerability, scenario_tree, weights
        )
        volatility_ss = self._score_volatility(
            surprise_vector, market_state, vulnerability, scenario_tree, weights
        )
        rate_shock_ss = self._score_rate_shock(
            surprise_vector, market_state, vulnerability, scenario_tree, weights
        )
        equity_ss = self._score_equity_downside(
            surprise_vector, market_state, vulnerability, scenario_tree, weights
        )
        credit_ss = self._score_credit_spread(
            surprise_vector, market_state, vulnerability, scenario_tree, weights
        )
        fx_ss = self._score_fx(
            surprise_vector, market_state, vulnerability, scenario_tree, weights
        )
        commodity_ss = self._score_commodity(
            surprise_vector, market_state, vulnerability, scenario_tree, weights
        )
        gap_ss = self._score_weekend_gap(event, surprise_vector, vulnerability, weights)
        ambiguity_ss = self._score_policy_ambiguity(surprise_vector, event, weights)

        # Compute composite before multipliers
        sub_scores = [
            liquidity_ss, volatility_ss, rate_shock_ss, equity_ss,
            credit_ss, fx_ss, commodity_ss, gap_ss, ambiguity_ss,
        ]
        raw_composite = sum(ss.weighted_contribution for ss in sub_scores)

        # Apply multipliers, cap at 100
        final_composite = min(raw_composite * regime_mult * gap_mult, 100.0)
        final_composite = max(final_composite, 0.0)

        severity = self._score_to_severity(final_composite)
        action_level = self._score_to_action(final_composite, event)

        primary_drivers = self._identify_primary_drivers(sub_scores)
        summary = self._build_summary(
            final_composite, severity, regime, event, surprise_vector, primary_drivers
        )

        data_quality = min(
            market_state.data_completeness,
            vulnerability.data_quality,
            surprise_vector.confidence,
        )
        reliability = self._assess_reliability(data_quality, event)

        score = CompositeRiskScore(
            event_id=event.event_id,
            composite_score=float(final_composite),
            severity=severity,
            liquidity_risk=liquidity_ss,
            volatility_risk=volatility_ss,
            rate_shock_risk=rate_shock_ss,
            equity_downside_risk=equity_ss,
            credit_spread_risk=credit_ss,
            fx_risk=fx_ss,
            commodity_shock_risk=commodity_ss,
            weekend_gap_risk=gap_ss,
            policy_ambiguity_risk=ambiguity_ss,
            regime_multiplier=float(regime_mult),
            gap_risk_multiplier=float(gap_mult),
            regime=regime,
            summary=summary,
            primary_risk_drivers=primary_drivers,
            recommended_action_level=action_level,
            overall_data_quality=float(data_quality),
            score_reliability=reliability,
        )

        logger.info(
            "risk_score_computed",
            event_id=event.event_id,
            composite=f"{final_composite:.1f}",
            severity=severity.value,
            regime=regime.value,
            regime_mult=f"{regime_mult:.2f}",
            gap_mult=f"{gap_mult:.2f}",
            drivers=primary_drivers[:3],
        )

        return score

    # ------------------------------------------------------------------
    # Sub-Score Computation Methods
    # ------------------------------------------------------------------

    def _score_liquidity(
        self,
        surprise: PolicySurpriseVector,
        state: MarketStateSnapshot,
        vuln: VulnerabilityComponents,
        tree: ScenarioTree,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["liquidity"]
        components = []
        factors = []

        # Component 1: Pre-event liquidity vulnerability (0-50 contribution)
        liq_vuln = vuln.liquidity_vulnerability * 50.0
        components.append(liq_vuln)
        if liq_vuln > 25:
            factors.append(f"Elevated pre-event liquidity stress ({liq_vuln:.0f}/50)")

        # Component 2: Expected liquidity impairment from scenario tree (0-30)
        expected_impairment = sum(
            s.probability * s.liquidity_impairment for s in tree.scenarios
        )
        impairment_score = expected_impairment * 30.0
        components.append(impairment_score)
        if impairment_score > 15:
            factors.append(f"High expected liquidity impairment ({expected_impairment:.1%})")

        # Component 3: Urgency boost (0-20)
        urgency_score = surprise.urgency_surprise * 20.0
        components.append(urgency_score)
        if urgency_score > 10:
            factors.append("Elevated urgency language in policy communication")

        raw = min(sum(components), 100.0)
        primary = factors[0] if factors else "No significant liquidity stress signals"

        return SubRiskScore(
            name="Liquidity Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
            data_quality=float(vuln.data_quality),
        )

    def _score_volatility(
        self,
        surprise: PolicySurpriseVector,
        state: MarketStateSnapshot,
        vuln: VulnerabilityComponents,
        tree: ScenarioTree,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["volatility"]
        components = []
        factors = []

        # Component 1: Pre-event VIX level (0-35)
        if state.volatility and state.volatility.vix_spot:
            vix = state.volatility.vix_spot
            vix_score = min((vix - 12.0) / (40.0 - 12.0) * 35.0, 35.0)
            components.append(vix_score)
            if vix > 25:
                factors.append(f"Elevated VIX at {vix:.1f}")
        else:
            components.append(20.0)  # Conservative default

        # Component 2: Expected VIX change from scenarios (0-35)
        expected_vix_change = sum(
            s.probability * max(s.vix_change, 0) for s in tree.scenarios
        )
        vix_change_score = min(expected_vix_change / 20.0 * 35.0, 35.0)
        components.append(vix_change_score)
        if expected_vix_change > 5:
            factors.append(f"Expected VIX increase +{expected_vix_change:.1f} pts")

        # Component 3: Surprise magnitude (0-30)
        surprise_score = surprise.composite_surprise_magnitude * 30.0
        components.append(surprise_score)
        if surprise.composite_surprise_magnitude > 0.5:
            factors.append("Large policy surprise magnitude signals vol expansion")

        raw = min(sum(components), 100.0)
        primary = factors[0] if factors else "Volatility risk within normal range"

        return SubRiskScore(
            name="Volatility Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
            data_quality=1.0 if (state.volatility and state.volatility.vix_spot) else 0.6,
        )

    def _score_rate_shock(
        self,
        surprise: PolicySurpriseVector,
        state: MarketStateSnapshot,
        vuln: VulnerabilityComponents,
        tree: ScenarioTree,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["rate_shock"]
        components = []
        factors = []

        # Component 1: Rate path surprise (most direct driver) (0-40)
        rate_surprise_score = abs(surprise.rate_path_surprise) * 40.0
        components.append(rate_surprise_score)
        direction = "hawkish" if surprise.rate_path_surprise > 0 else "dovish"
        if abs(surprise.rate_path_surprise) > 0.3:
            factors.append(
                f"Significant {direction} rate path surprise "
                f"({surprise.rate_path_surprise:+.2f})"
            )

        # Component 2: Expected 10y yield change from scenarios (0-35)
        expected_10y_change = abs(sum(
            s.probability * s.yield_10y_change_bps for s in tree.scenarios
        ))
        yield_score = min(expected_10y_change / 30.0 * 35.0, 35.0)
        components.append(yield_score)
        if expected_10y_change > 10:
            factors.append(f"Expected 10Y yield move ±{expected_10y_change:.0f}bps")

        # Component 3: Yield curve context (0-25)
        if state.yields and state.yields.slope_2_10 is not None:
            slope = state.yields.slope_2_10
            if slope < 0:
                # Inversion amplifies rate shock transmission to growth
                curve_score = min(abs(slope) / 100.0 * 25.0, 25.0)
                factors.append(f"Inverted yield curve ({slope:.0f}bps) amplifies shock")
            else:
                curve_score = 5.0
            components.append(curve_score)

        raw = min(sum(components), 100.0)
        primary = factors[0] if factors else "Rate shock risk within normal range"

        return SubRiskScore(
            name="Rate Shock Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
        )

    def _score_equity_downside(
        self,
        surprise: PolicySurpriseVector,
        state: MarketStateSnapshot,
        vuln: VulnerabilityComponents,
        tree: ScenarioTree,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["equity_downside"]
        components = []
        factors = []

        # Component 1: Expected equity downside from scenario tree (0-40)
        expected_negative = sum(
            s.probability * abs(min(s.equity_impact_pct, 0))
            for s in tree.scenarios
        )
        equity_score = min(expected_negative / 5.0 * 40.0, 40.0)
        components.append(equity_score)
        if expected_negative > 1.5:
            factors.append(f"Expected equity downside -{expected_negative:.1f}%")

        # Component 2: Tail loss (5th percentile) (0-35)
        tail_severity = abs(min(tree.tail_loss_5pct, 0))
        tail_score = min(tail_severity / 10.0 * 35.0, 35.0)
        components.append(tail_score)
        if tail_severity > 3:
            factors.append(f"Tail loss (5%) estimate: {tree.tail_loss_5pct:.1f}%")

        # Component 3: Equity vulnerability (pre-event drawdown) (0-25)
        if state.equity and state.equity.spx_from_52w_high is not None:
            drawdown = abs(min(state.equity.spx_from_52w_high, 0))
            drawdown_score = min(drawdown / 20.0 * 25.0, 25.0)
            components.append(drawdown_score)
            if drawdown > 5:
                factors.append(
                    f"SPX already -{drawdown:.1f}% from 52-week high"
                )
        else:
            components.append(10.0)

        raw = min(sum(components), 100.0)
        primary = factors[0] if factors else "Equity downside risk within normal range"

        return SubRiskScore(
            name="Equity Downside Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
        )

    def _score_credit_spread(
        self,
        surprise: PolicySurpriseVector,
        state: MarketStateSnapshot,
        vuln: VulnerabilityComponents,
        tree: ScenarioTree,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["credit_spread"]
        components = []
        factors = []

        # Component 1: Pre-event credit vulnerability (0-40)
        credit_vuln_score = vuln.credit_vulnerability * 40.0
        components.append(credit_vuln_score)
        if state.credit and state.credit.hy_spread_bps and state.credit.hy_spread_bps > 450:
            factors.append(f"HY spreads already elevated at {state.credit.hy_spread_bps:.0f}bps")

        # Component 2: Expected HY spread widening from scenarios (0-35)
        expected_hy_widen = sum(
            s.probability * max(s.credit_hy_change_bps, 0)
            for s in tree.scenarios
        )
        hy_score = min(expected_hy_widen / 100.0 * 35.0, 35.0)
        components.append(hy_score)
        if expected_hy_widen > 25:
            factors.append(f"Expected HY spread widening +{expected_hy_widen:.0f}bps")

        # Component 3: Correlation spike risk (0-25)
        tail_scenarios = [s for s in tree.scenarios if s.correlation_spike_expected]
        corr_spike_prob = sum(s.probability for s in tail_scenarios)
        corr_score = corr_spike_prob * 25.0
        components.append(corr_score)
        if corr_spike_prob > 0.10:
            factors.append(f"Correlation spike probability: {corr_spike_prob:.0%}")

        raw = min(sum(components), 100.0)
        primary = factors[0] if factors else "Credit spread risk within normal range"

        return SubRiskScore(
            name="Credit Spread Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
        )

    def _score_fx(
        self,
        surprise: PolicySurpriseVector,
        state: MarketStateSnapshot,
        vuln: VulnerabilityComponents,
        tree: ScenarioTree,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["fx"]
        components = []
        factors = []

        # Component 1: Rate surprise drives DXY (0-50)
        rate_dir = surprise.rate_path_surprise
        expected_dxy_change = sum(
            s.probability * abs(s.dxy_change_pct) for s in tree.scenarios
        )
        fx_score = min(expected_dxy_change / 2.0 * 50.0, 50.0)
        components.append(fx_score)
        if expected_dxy_change > 0.5:
            factors.append(f"Expected DXY move ±{expected_dxy_change:.2f}%")

        # Component 2: EM FX vulnerability (0-30)
        if vuln.composite > 0.6:
            em_score = min((vuln.composite - 0.6) / 0.4 * 30.0, 30.0)
            components.append(em_score)
            factors.append("Risk-off environment stresses EM FX")
        else:
            components.append(5.0)

        # Component 3: Financial stability concern → carry unwind (0-20)
        fin_stability_surprise = abs(surprise.financial_stability_surprise)
        if fin_stability_surprise > 0.3:
            carry_score = fin_stability_surprise * 20.0
            components.append(carry_score)
            factors.append("Financial stability signals trigger FX carry unwind")
        else:
            components.append(3.0)

        raw = min(sum(components), 100.0)
        primary = factors[0] if factors else "FX risk within normal range"

        return SubRiskScore(
            name="FX Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
        )

    def _score_commodity(
        self,
        surprise: PolicySurpriseVector,
        state: MarketStateSnapshot,
        vuln: VulnerabilityComponents,
        tree: ScenarioTree,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["commodity"]
        components = []
        factors = []

        # Gold as flight-to-safety proxy
        expected_gold = sum(
            s.probability * s.gold_change_pct for s in tree.scenarios
        )
        # Large positive gold move = risk-off (high vulnerability)
        gold_score = min(max(expected_gold, 0) / 3.0 * 50.0, 50.0)
        components.append(gold_score)
        if expected_gold > 1.0:
            factors.append(f"Expected gold +{expected_gold:.1f}% (flight-to-safety)")

        # Oil as growth proxy
        expected_oil_change = sum(
            s.probability * abs(s.oil_change_pct) for s in tree.scenarios
        )
        oil_score = min(expected_oil_change / 5.0 * 50.0, 50.0)
        components.append(oil_score)
        if abs(sum(s.probability * s.oil_change_pct for s in tree.scenarios)) > 1.5:
            factors.append(f"Significant oil price dislocation expected")

        raw = min(sum(components), 100.0)
        primary = factors[0] if factors else "Commodity shock risk within normal range"

        return SubRiskScore(
            name="Commodity Shock Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
        )

    def _score_weekend_gap(
        self,
        event: MacroEvent,
        surprise: PolicySurpriseVector,
        vuln: VulnerabilityComponents,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["weekend_gap"]
        factors = []

        if not event.is_after_hours and not event.is_weekend:
            return SubRiskScore(
                name="Weekend Gap Risk",
                score=0.0,
                weight=w,
                primary_driver="Event occurred during market hours; no gap risk",
                confidence=1.0,
            )

        components = []

        # Component 1: Gap duration (0-40)
        if event.hours_until_next_open:
            # Maximum gap = ~60 hours (Friday 4pm to Monday 9:30am)
            hours = event.hours_until_next_open
            duration_score = min(hours / 60.0 * 40.0, 40.0)
            components.append(duration_score)
            factors.append(f"{hours:.1f}h until next market open")
        else:
            components.append(20.0)

        # Component 2: Surprise magnitude amplified by gap (0-30)
        gap_surprise_score = surprise.composite_surprise_magnitude * 30.0
        if event.full_weekend_gap:
            gap_surprise_score *= 1.3
        components.append(min(gap_surprise_score, 30.0))
        if surprise.composite_surprise_magnitude > 0.4:
            factors.append("Large surprise during closed market = gap risk")

        # Component 3: Vulnerability during gap (0-30)
        gap_vuln_score = vuln.composite * 30.0
        components.append(gap_vuln_score)
        if vuln.composite > 0.5:
            factors.append("Fragile market conditions amplify Monday opening risk")

        raw = min(sum(components), 100.0)
        primary = (
            factors[0]
            if factors
            else "Weekend/after-hours event detected"
        )

        return SubRiskScore(
            name="Weekend Gap Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
        )

    def _score_policy_ambiguity(
        self,
        surprise: PolicySurpriseVector,
        event: MacroEvent,
        weights: Dict,
    ) -> SubRiskScore:
        w = weights["policy_ambiguity"]
        components = []
        factors = []

        hd = surprise.hawkish_dovish

        # Low confidence = high ambiguity
        ambiguity_from_confidence = (1.0 - surprise.confidence) * 40.0
        components.append(ambiguity_from_confidence)
        if surprise.confidence < 0.5:
            factors.append(f"Low NLP confidence ({surprise.confidence:.0%}) signals ambiguous language")

        # Forward guidance change = uncertainty about future path
        if hd and hd.forward_guidance_change:
            components.append(30.0)
            factors.append("Forward guidance changed or removed — path uncertainty elevated")
        else:
            components.append(5.0)

        # Policy reversal language
        if hd and hd.policy_reversal_language:
            components.append(30.0)
            factors.append("Policy reversal language detected — prior guidance invalidated")
        else:
            components.append(5.0)

        raw = min(sum(components), 100.0)
        primary = factors[0] if factors else "Policy communication is clear and in-line"

        return SubRiskScore(
            name="Policy Ambiguity Risk",
            score=float(raw),
            weight=w,
            primary_driver=primary,
            contributing_factors=factors,
            confidence=float(surprise.confidence),
        )

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------

    def _compute_gap_multiplier(self, event: MacroEvent) -> float:
        """
        Gap risk multiplier based on market closure duration.
        1.0 = event during market hours
        1.5 = full weekend gap
        """
        if not event.is_after_hours and not event.is_weekend:
            return 1.0
        if event.full_weekend_gap:
            hours = event.hours_until_next_open or 60.0
            # Scale: 1.2 for overnight, 1.5 for full weekend
            return min(1.2 + (hours / 60.0) * 0.3, 1.5)
        return 1.2  # Regular after-hours event

    def _score_to_severity(self, score: float) -> SeverityLevel:
        if score >= 75:
            return SeverityLevel.CRITICAL
        elif score >= 55:
            return SeverityLevel.HIGH
        elif score >= 35:
            return SeverityLevel.MEDIUM
        elif score >= 15:
            return SeverityLevel.LOW
        return SeverityLevel.INFORMATIONAL

    def _score_to_action(self, score: float, event: MacroEvent) -> str:
        if score >= 80:
            return "EMERGENCY_DERISKING"
        elif score >= 65:
            return "HEDGE"
        elif score >= 45:
            return "REDUCE"
        elif score >= 25:
            return "MONITOR"
        return "NO_ACTION"

    def _identify_primary_drivers(self, sub_scores: List[SubRiskScore]) -> List[str]:
        """Return the top 3 risk drivers by weighted contribution."""
        sorted_scores = sorted(
            sub_scores, key=lambda s: s.weighted_contribution, reverse=True
        )
        return [
            f"{s.name}: {s.score:.0f}/100 ({s.primary_driver})"
            for s in sorted_scores[:3]
            if s.weighted_contribution > 2.0
        ]

    def _build_summary(
        self,
        score: float,
        severity: SeverityLevel,
        regime: RegimeType,
        event: MacroEvent,
        surprise: PolicySurpriseVector,
        drivers: List[str],
    ) -> str:
        stance_desc = ""
        if surprise.hawkish_dovish:
            stance_desc = f"Policy assessed as {surprise.hawkish_dovish.stance.value}. "

        gap_desc = ""
        if event.full_weekend_gap:
            gap_desc = (
                f"Event occurred during weekend gap corridor "
                f"({event.hours_until_next_open:.1f}h until next market open). "
            )

        crisis_desc = ""
        if surprise.hawkish_dovish and surprise.hawkish_dovish.crisis_language_detected:
            crisis_desc = "Crisis language detected. "

        return (
            f"{severity.value} macro shock risk: composite score {score:.1f}/100. "
            f"Regime: {regime.value}. {stance_desc}{gap_desc}{crisis_desc}"
            f"Primary drivers: {'; '.join(drivers[:2]) if drivers else 'see sub-scores'}."
        )

    def _assess_reliability(self, data_quality: float, event: MacroEvent) -> str:
        if data_quality >= self.min_data_quality_for_high_confidence:
            return "HIGH"
        elif data_quality >= 0.5:
            return "MEDIUM"
        return "LOW"
