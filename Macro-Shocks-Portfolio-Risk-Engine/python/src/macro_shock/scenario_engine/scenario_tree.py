"""
scenario_engine/scenario_tree.py

Shock Propagation and Scenario Tree Engine.

Builds a probability-weighted scenario tree for a macro event, conditioned on:
1. The policy surprise vector (magnitude and direction)
2. Pre-event market vulnerability (regime, vol level, liquidity)
3. Event type and timing (weekend gap, emergency, etc.)

Scenarios are calibrated to historical event distributions.
Each scenario carries explicit impact estimates, a probability, and
liquidity/trading-halt assumptions.

Uncertainty: scenario probabilities are point estimates, not exact.
In production, confidence intervals should be communicated alongside
any single probability estimate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import structlog

from macro_shock.data_schema.models import (
    EventType,
    MacroEvent,
    MarketStateSnapshot,
    PolicySurpriseVector,
    RegimeType,
    ScenarioOutcome,
    ScenarioTree,
    SeverityLevel,
)
from macro_shock.market_context.vulnerability_scorer import VulnerabilityComponents

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Scenario Definitions
# ---------------------------------------------------------------------------
# Base scenarios. Probabilities are set to 1.0 (placeholder) and are
# conditioned/re-weighted by the scenario engine based on the context.

SCENARIO_TEMPLATES = [
    {
        "name": "Benign / In-Line",
        "description": "Policy communication is broadly in line with expectations. Markets absorb with minimal dislocation.",
        "base_prob": 0.30,
        "equity_impact_pct": -0.5,    # ~ flat
        "yield_10y_change_bps": 3.0,
        "yield_2y_change_bps": 4.0,
        "credit_hy_change_bps": 5.0,
        "vix_change": 0.0,
        "dxy_change_pct": 0.1,
        "gold_change_pct": -0.2,
        "oil_change_pct": 0.0,
        "liquidity_impairment": 0.0,
        "correlation_spike": False,
        "trading_halt_prob": 0.00,
        "forced_deleveraging": 0.0,
        "is_tail": False,
    },
    {
        "name": "Mild Hawkish Surprise",
        "description": "Policy is marginally more hawkish than expected. Modest rate re-pricing, equity softness.",
        "base_prob": 0.25,
        "equity_impact_pct": -1.8,
        "yield_10y_change_bps": 12.0,
        "yield_2y_change_bps": 18.0,
        "credit_hy_change_bps": 20.0,
        "vix_change": 2.5,
        "dxy_change_pct": 0.4,
        "gold_change_pct": -0.6,
        "oil_change_pct": -0.3,
        "liquidity_impairment": 0.10,
        "correlation_spike": False,
        "trading_halt_prob": 0.00,
        "forced_deleveraging": 0.05,
        "is_tail": False,
    },
    {
        "name": "Mild Dovish Surprise",
        "description": "Policy is marginally more dovish/accommodative than expected. Modest equity rally, rates lower.",
        "base_prob": 0.20,
        "equity_impact_pct": 1.5,
        "yield_10y_change_bps": -10.0,
        "yield_2y_change_bps": -15.0,
        "credit_hy_change_bps": -15.0,
        "vix_change": -2.0,
        "dxy_change_pct": -0.5,
        "gold_change_pct": 0.8,
        "oil_change_pct": 0.5,
        "liquidity_impairment": 0.05,
        "correlation_spike": False,
        "trading_halt_prob": 0.00,
        "forced_deleveraging": 0.0,
        "is_tail": False,
    },
    {
        "name": "Significant Hawkish Shock",
        "description": "Unexpectedly aggressive tightening signal. Material equity selloff, yield spike, spread widening.",
        "base_prob": 0.10,
        "equity_impact_pct": -4.5,
        "yield_10y_change_bps": 28.0,
        "yield_2y_change_bps": 40.0,
        "credit_hy_change_bps": 65.0,
        "vix_change": 8.0,
        "dxy_change_pct": 1.2,
        "gold_change_pct": -1.5,
        "oil_change_pct": -1.5,
        "liquidity_impairment": 0.30,
        "correlation_spike": True,
        "trading_halt_prob": 0.02,
        "forced_deleveraging": 0.20,
        "is_tail": False,
    },
    {
        "name": "Disorderly Risk-Off",
        "description": "Policy shock triggers broad deleveraging. Correlated selloff across risk assets. VIX spike.",
        "base_prob": 0.07,
        "equity_impact_pct": -7.5,
        "yield_10y_change_bps": 15.0,
        "yield_2y_change_bps": 25.0,
        "credit_hy_change_bps": 150.0,
        "vix_change": 18.0,
        "dxy_change_pct": 2.0,
        "gold_change_pct": -2.0,
        "oil_change_pct": -4.0,
        "liquidity_impairment": 0.60,
        "correlation_spike": True,
        "trading_halt_prob": 0.07,
        "forced_deleveraging": 0.55,
        "is_tail": True,
    },
    {
        "name": "Emergency Crisis Easing",
        "description": "Emergency dovish action signals severe financial stress. Initial equity crash, then reversal.",
        "base_prob": 0.03,
        "equity_impact_pct": -8.0,      # Initial shock before reversal
        "yield_10y_change_bps": -40.0,  # Flight to safety
        "yield_2y_change_bps": -50.0,
        "credit_hy_change_bps": 250.0,  # Credit blowout despite QE
        "vix_change": 25.0,
        "dxy_change_pct": -1.5,
        "gold_change_pct": 4.0,
        "oil_change_pct": -5.0,
        "liquidity_impairment": 0.85,
        "correlation_spike": True,
        "trading_halt_prob": 0.15,
        "forced_deleveraging": 0.80,
        "is_tail": True,
    },
    {
        "name": "Extraordinary Market Intervention",
        "description": "Fed or government announces emergency market-structure intervention (circuit breakers activated, exchange closure).",
        "base_prob": 0.01,
        "equity_impact_pct": -12.0,
        "yield_10y_change_bps": -60.0,
        "yield_2y_change_bps": -70.0,
        "credit_hy_change_bps": 500.0,
        "vix_change": 40.0,
        "dxy_change_pct": 3.0,
        "gold_change_pct": 6.0,
        "oil_change_pct": -10.0,
        "liquidity_impairment": 1.0,
        "correlation_spike": True,
        "trading_halt_prob": 0.90,
        "forced_deleveraging": 1.0,
        "is_tail": True,
    },
    {
        "name": "Significant Dovish Accommodation",
        "description": "Much more accommodative than expected. Equity rally, curve steepener, credit tightening.",
        "base_prob": 0.04,
        "equity_impact_pct": 3.5,
        "yield_10y_change_bps": -20.0,
        "yield_2y_change_bps": -30.0,
        "credit_hy_change_bps": -40.0,
        "vix_change": -5.0,
        "dxy_change_pct": -1.5,
        "gold_change_pct": 2.0,
        "oil_change_pct": 1.5,
        "liquidity_impairment": 0.05,
        "correlation_spike": False,
        "trading_halt_prob": 0.00,
        "forced_deleveraging": 0.0,
        "is_tail": False,
    },
]


class ScenarioTreeBuilder:
    """
    Builds a calibrated probability-weighted scenario tree.

    Algorithm:
    1. Start with base scenario probabilities (empirical priors)
    2. Condition probabilities on the policy surprise magnitude and direction
    3. Apply regime adjustments (crisis regime increases tail scenario weights)
    4. Apply weekend/gap corridor adjustments (amplify magnitude estimates)
    5. Normalize probabilities to sum to 1.0
    6. Compute probability-weighted expected values and tail statistics

    Key tradeoff: We use a small, named scenario set (7 scenarios) rather than
    a full simulation. This sacrifices tail precision for interpretability and
    speed. For precise tail estimation, plug in a Monte Carlo layer downstream.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.random_state = np.random.RandomState(42)  # Reproducible for testing

    def build(
        self,
        event: MacroEvent,
        surprise_vector: PolicySurpriseVector,
        vulnerability: VulnerabilityComponents,
        market_state: Optional[MarketStateSnapshot] = None,
    ) -> ScenarioTree:
        """
        Build the full scenario tree.
        """
        scenarios = self._build_base_scenarios()
        scenarios = self._condition_on_surprise(scenarios, surprise_vector)
        scenarios = self._condition_on_regime(scenarios, vulnerability.regime)
        scenarios = self._apply_vulnerability_amplification(scenarios, vulnerability)
        scenarios = self._apply_gap_corridor_amplification(scenarios, event)
        scenarios = self._normalize_probabilities(scenarios)

        # Convert to model objects
        outcome_objects = [
            ScenarioOutcome(
                name=s["name"],
                description=s["description"],
                probability=s["prob"],
                equity_impact_z=s["equity_impact_pct"] / 3.0,  # Rough z-score
                equity_impact_pct=s["equity_impact_pct"],
                yield_10y_change_bps=s["yield_10y_change_bps"],
                yield_2y_change_bps=s["yield_2y_change_bps"],
                credit_hy_change_bps=s["credit_hy_change_bps"],
                vix_change=s["vix_change"],
                dxy_change_pct=s["dxy_change_pct"],
                gold_change_pct=s["gold_change_pct"],
                oil_change_pct=s["oil_change_pct"],
                is_tail_scenario=s["is_tail"],
                liquidity_impairment=s["liquidity_impairment"],
                correlation_spike_expected=s["correlation_spike"],
                trading_halt_probability=s["trading_halt_prob"],
                forced_deleveraging_risk=s["forced_deleveraging"],
                first_price_discovery=(
                    "futures_immediate"
                    if not event.full_weekend_gap
                    else "monday_cash_open"
                ),
            )
            for s in scenarios
        ]

        # Compute aggregate statistics
        probabilities = np.array([s.probability for s in outcome_objects])
        equity_returns = np.array([s.equity_impact_pct for s in outcome_objects])
        yield_changes = np.array([s.yield_10y_change_bps for s in outcome_objects])
        vix_changes = np.array([s.vix_change for s in outcome_objects])

        expected_equity = float(np.dot(probabilities, equity_returns))
        expected_yield = float(np.dot(probabilities, yield_changes))
        expected_vix = float(np.dot(probabilities, vix_changes))

        # Tail loss (5th and 1st percentile equity outcomes)
        # Sort scenarios by equity impact
        sorted_returns = np.sort(equity_returns)
        sorted_probs = probabilities[np.argsort(equity_returns)]
        cumulative_probs = np.cumsum(sorted_probs)

        tail_5pct = float(sorted_returns[np.searchsorted(cumulative_probs, 0.05)])
        tail_1pct = float(sorted_returns[np.searchsorted(cumulative_probs, 0.01)])

        # Monday gap estimate (for weekend events)
        monday_gap = None
        monday_gap_conf = None
        if event.full_weekend_gap:
            # Gap estimate is the probability-weighted equity impact
            # adjusted for futures pre-absorption
            monday_gap = expected_equity * 0.85  # Futures absorb ~15% before open
            monday_gap_conf = float(1.0 - vulnerability.data_quality * 0.2)  # Lower confidence with missing data

        tree = ScenarioTree(
            event_id=event.event_id,
            regime=vulnerability.regime,
            scenarios=outcome_objects,
            expected_equity_impact_pct=expected_equity,
            expected_yield_change_bps=expected_yield,
            expected_vix_change=expected_vix,
            tail_loss_5pct=tail_5pct,
            tail_loss_1pct=tail_1pct,
            monday_gap_estimate_pct=monday_gap,
            monday_gap_confidence=monday_gap_conf,
        )

        logger.info(
            "scenario_tree_built",
            event_id=event.event_id,
            n_scenarios=len(outcome_objects),
            expected_equity=f"{expected_equity:.2f}%",
            tail_5pct=f"{tail_5pct:.2f}%",
            regime=vulnerability.regime.value,
            monday_gap=f"{monday_gap:.2f}%" if monday_gap else "N/A",
        )

        return tree

    def _build_base_scenarios(self) -> List[Dict]:
        """Return a fresh copy of scenario templates with 'prob' field."""
        scenarios = []
        for t in SCENARIO_TEMPLATES:
            s = dict(t)
            s["prob"] = s.pop("base_prob")
            scenarios.append(s)
        return scenarios

    def _condition_on_surprise(
        self, scenarios: List[Dict], surprise: PolicySurpriseVector
    ) -> List[Dict]:
        """
        Shift scenario weights based on the direction and magnitude of the surprise.

        High positive (hawkish) surprise → upweight hawkish scenarios.
        High negative (dovish) surprise → upweight dovish scenarios.
        High urgency → upweight tail scenarios.
        """
        direction = surprise.net_direction
        magnitude = surprise.composite_surprise_magnitude
        urgency = surprise.urgency_surprise
        crisis = surprise.hawkish_dovish.crisis_language_detected if surprise.hawkish_dovish else False

        for s in scenarios:
            name = s["name"]
            boost = 1.0

            # Direction-based conditioning
            if direction > 0.3 and "Hawkish" in name:
                boost *= (1.0 + magnitude * 1.5)
            elif direction > 0.3 and ("Dovish" in name or "Crisis" in name):
                boost *= max(1.0 - magnitude * 0.8, 0.05)

            if direction < -0.3 and ("Dovish" in name or "Crisis" in name or "Emergency" in name):
                boost *= (1.0 + magnitude * 1.5)
            elif direction < -0.3 and "Hawkish" in name:
                boost *= max(1.0 - magnitude * 0.8, 0.05)

            # In-line scenario discounted when surprise is large
            if name == "Benign / In-Line":
                boost *= max(1.0 - magnitude * 2.0, 0.05)

            # Urgency boosts tail scenarios
            if s["is_tail"] and urgency > 0.5:
                boost *= (1.0 + urgency * 1.0)

            # Crisis language boosts emergency scenarios
            if crisis and "Crisis" in name:
                boost *= 3.0
            if crisis and "Extraordinary" in name:
                boost *= 5.0

            s["prob"] = s["prob"] * boost

        return scenarios

    def _condition_on_regime(
        self, scenarios: List[Dict], regime: RegimeType
    ) -> List[Dict]:
        """
        Adjust probabilities based on the current market regime.
        In crisis regime, tail scenarios get much higher weights.
        """
        regime_tail_multipliers = {
            RegimeType.RISK_ON_EXPANSION: 0.5,    # Tails unlikely in calm markets
            RegimeType.FRAGILE_RISK_ON: 1.0,       # Neutral
            RegimeType.RISK_OFF_CORRECTION: 1.8,   # Tails more likely
            RegimeType.CRISIS: 4.0,                # Tails highly likely
            RegimeType.RECOVERY: 0.7,
            RegimeType.UNKNOWN: 1.0,
        }
        tail_mult = regime_tail_multipliers.get(regime, 1.0)

        for s in scenarios:
            if s["is_tail"]:
                s["prob"] *= tail_mult
            elif regime == RegimeType.RISK_ON_EXPANSION:
                if "Benign" in s["name"] or "Mild" in s["name"]:
                    s["prob"] *= 1.3

        return scenarios

    def _apply_vulnerability_amplification(
        self, scenarios: List[Dict], vuln: VulnerabilityComponents
    ) -> List[Dict]:
        """
        Scale impact magnitudes (not probabilities) by market vulnerability.
        High vulnerability = existing stress amplifies the shock.
        """
        amp = vuln.amplification_factor  # [1.0, 2.0]
        for s in scenarios:
            # Amplify negative outcomes more than positive
            if s["equity_impact_pct"] < 0:
                s["equity_impact_pct"] *= amp
            else:
                s["equity_impact_pct"] *= (1.0 + (amp - 1.0) * 0.5)

            s["vix_change"] *= amp
            s["credit_hy_change_bps"] *= amp
            s["liquidity_impairment"] = min(s["liquidity_impairment"] * amp, 1.0)

        return scenarios

    def _apply_gap_corridor_amplification(
        self, scenarios: List[Dict], event: MacroEvent
    ) -> List[Dict]:
        """
        Weekend gap corridor amplification.
        When markets are closed, information cannot be absorbed gradually.
        The first tradable session may gap violently.

        Amplification logic:
        - Increase magnitude of adverse scenarios
        - Increase trading halt probability
        - Increase forced deleveraging risk
        """
        if not event.full_weekend_gap:
            return scenarios

        gap_amp = 1.25  # Base gap amplification
        if event.hours_until_next_open and event.hours_until_next_open > 48:
            gap_amp = 1.40  # Full Saturday event = maximum gap time

        for s in scenarios:
            if s["is_tail"] or s["equity_impact_pct"] < -2.0:
                s["equity_impact_pct"] *= gap_amp
                s["trading_halt_prob"] = min(s["trading_halt_prob"] * 2.0, 0.95)
                s["forced_deleveraging"] = min(s["forced_deleveraging"] * 1.5, 1.0)
            elif "Benign" in s["name"]:
                # Even benign scenarios are slightly amplified due to uncertainty
                s["equity_impact_pct"] *= 1.1

        return scenarios

    def _normalize_probabilities(self, scenarios: List[Dict]) -> List[Dict]:
        """Ensure probabilities sum to 1.0."""
        total = sum(s["prob"] for s in scenarios)
        if total < 1e-6:
            # Fallback: equal weights
            for s in scenarios:
                s["prob"] = 1.0 / len(scenarios)
        else:
            for s in scenarios:
                s["prob"] = s["prob"] / total
        return scenarios
