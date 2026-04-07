"""
portfolio_impact/impact_translator.py

Portfolio Impact Engine.

Translates the risk score, scenario tree, and market context into
explicit, asset-class-specific portfolio recommendations. Outputs are
structured to interface with OMS/EMS/PMS systems.

Design philosophy:
- Never fully automated. All outputs require PM authorization.
- Explicit, not vague. "Reduce equity beta by 15-25%" not "reduce risk."
- Regime-conditioned. Different advice for different market states.
- Tiered by urgency. Immediate vs. pre-open vs. intraday actions.
- Hedge sizing is illustrative, not exact; requires PM calibration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog

from macro_shock.data_schema.models import (
    AlertLevel,
    AssetClass,
    CompositeRiskScore,
    EventType,
    HedgeRecommendation,
    MacroEvent,
    MarketStateSnapshot,
    PortfolioImpactReport,
    RegimeType,
    ScenarioTree,
    SeverityLevel,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Action Thresholds
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "kill_switch": 90.0,          # Auto-trigger kill switch consideration
    "emergency_derisking": 80.0,  # Emergency exposure reduction
    "hedge": 65.0,                # Active hedging recommended
    "reduce": 45.0,               # Exposure reduction
    "monitor": 25.0,              # Watch closely, no action
    "no_action": 0.0,
}

# Recommended gross exposure reduction by action level
GROSS_EXPOSURE_CHANGES = {
    "EMERGENCY_DERISKING": (-0.35, -0.50),   # Reduce 35-50%
    "HEDGE": (-0.15, -0.25),                  # Reduce 15-25%
    "REDUCE": (-0.08, -0.15),                 # Reduce 8-15%
    "MONITOR": (0.0, 0.0),
    "NO_ACTION": (0.0, 0.0),
}

# Recommended leverage changes
LEVERAGE_CHANGES = {
    "EMERGENCY_DERISKING": (-0.40, -0.60),
    "HEDGE": (-0.20, -0.35),
    "REDUCE": (-0.10, -0.20),
    "MONITOR": (0.0, 0.0),
    "NO_ACTION": (0.0, 0.0),
}


class PortfolioImpactTranslator:
    """
    Translates risk scores and scenarios into portfolio recommendations.

    Portfolio-type aware: provides specialized guidance for:
    - Equity long/short
    - Fixed income / rates
    - Macro / global macro
    - Credit
    - Volatility strategies

    NOTE: Hedge sizing guidance is illustrative. Actual sizing must be
    calibrated to specific portfolio Greeks, factor exposures, and
    available hedging instruments. This engine outputs qualitative-to-
    semi-quantitative guidance, not final OMS orders.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

    def generate(
        self,
        event: MacroEvent,
        risk_score: CompositeRiskScore,
        scenario_tree: ScenarioTree,
        market_state: MarketStateSnapshot,
    ) -> PortfolioImpactReport:
        """
        Generate the full portfolio impact report.
        """
        action_level = risk_score.recommended_action_level
        severity = risk_score.severity
        regime = risk_score.regime
        composite = risk_score.composite_score

        gross_range = GROSS_EXPOSURE_CHANGES.get(action_level, (0.0, 0.0))
        lev_range = LEVERAGE_CHANGES.get(action_level, (0.0, 0.0))

        # Midpoint of recommended range
        gross_change = (gross_range[0] + gross_range[1]) / 2 if gross_range[0] != 0 else None
        net_change = gross_change * 0.6 if gross_change else None  # Net changes less than gross
        lev_change = (lev_range[0] + lev_range[1]) / 2 if lev_range[0] != 0 else None

        # Generate asset-class guidance
        eq_guidance = self._equity_guidance(risk_score, scenario_tree, regime)
        fi_guidance = self._fixed_income_guidance(risk_score, scenario_tree, regime)
        rates_guidance = self._rates_guidance(risk_score, scenario_tree, regime)
        fx_guidance = self._fx_guidance(risk_score, scenario_tree, regime)
        comm_guidance = self._commodity_guidance(risk_score, scenario_tree)
        credit_guidance = self._credit_guidance(risk_score, scenario_tree, regime)
        vol_guidance = self._volatility_guidance(risk_score, scenario_tree, market_state)

        # Generate specific hedge recommendations
        hedges = self._generate_hedges(
            event, risk_score, scenario_tree, market_state, action_level
        )

        alert_level = self._score_to_alert(composite)
        trigger_kill = composite >= THRESHOLDS["kill_switch"]
        requires_review = composite >= THRESHOLDS["reduce"]

        # Estimated portfolio impact
        var_change = self._estimate_var_change(risk_score, scenario_tree)
        drawdown_risk = abs(scenario_tree.tail_loss_5pct)

        notes = self._build_notes(event, risk_score, scenario_tree)

        report = PortfolioImpactReport(
            event_id=event.event_id,
            score_id=risk_score.score_id,
            action_level=action_level,
            recommended_gross_exposure_change=gross_change,
            recommended_net_exposure_change=net_change,
            recommended_leverage_change=lev_change,
            equity_guidance=eq_guidance,
            fixed_income_guidance=fi_guidance,
            rates_guidance=rates_guidance,
            fx_guidance=fx_guidance,
            commodity_guidance=comm_guidance,
            credit_guidance=credit_guidance,
            vol_guidance=vol_guidance,
            hedge_recommendations=hedges,
            estimated_portfolio_var_change=var_change,
            estimated_drawdown_risk=drawdown_risk,
            trigger_kill_switch=trigger_kill,
            alert_level=alert_level,
            requires_immediate_review=requires_review,
            human_override_required=True,  # Always true
            notes=notes,
        )

        logger.info(
            "portfolio_impact_generated",
            event_id=event.event_id,
            action_level=action_level,
            alert_level=alert_level.value,
            n_hedges=len(hedges),
            kill_switch=trigger_kill,
            gross_change=f"{gross_change:.0%}" if gross_change else "N/A",
        )

        return report

    # ------------------------------------------------------------------
    # Asset-Class Guidance
    # ------------------------------------------------------------------

    def _equity_guidance(
        self, score: CompositeRiskScore, tree: ScenarioTree, regime: RegimeType
    ) -> str:
        level = score.recommended_action_level
        eq_score = score.equity_downside_risk.score
        tail = tree.tail_loss_5pct

        if level == "EMERGENCY_DERISKING":
            return (
                f"EMERGENCY: Reduce gross equity exposure 35-50%. "
                f"Close or hedge high-beta longs immediately. "
                f"Add tail protection via near-term SPX put spreads (1-2% OTM, 2-4 week expiry). "
                f"5th percentile scenario: {tail:.1f}% equity drawdown. "
                f"Bias: reduce longs before adding shorts to preserve optionality."
            )
        elif level == "HEDGE":
            return (
                f"HEDGE: Reduce equity gross 15-25%. "
                f"Purchase 1-month SPX puts or collars on concentrated equity positions. "
                f"Reduce high-beta / high-multiple names first. "
                f"Consider variance swaps on SPX if vol is cheap pre-event. "
                f"Expected scenario equity move: {tree.expected_equity_impact_pct:.1f}%."
            )
        elif level == "REDUCE":
            return (
                f"REDUCE: Trim equity exposure 8-15%, focusing on high-beta / high-valuation names. "
                f"Shift toward defensive factors (low-vol, quality, dividend yield). "
                f"Reduce single-name concentration. "
                f"Consider minimal put protection on core positions."
            )
        elif level == "MONITOR":
            return (
                f"MONITOR: Maintain current equity positions. "
                f"Watch for follow-through selling / vol expansion. "
                f"Be prepared to reduce quickly if risk-off dynamics materialize. "
                f"Equity sub-score: {eq_score:.0f}/100."
            )
        return "NO ACTION: Equity positioning unchanged."

    def _fixed_income_guidance(
        self, score: CompositeRiskScore, tree: ScenarioTree, regime: RegimeType
    ) -> str:
        rate_score = score.rate_shock_risk.score
        expected_yield = tree.expected_yield_change_bps

        if score.recommended_action_level in ("EMERGENCY_DERISKING", "HEDGE"):
            direction = "Shorten" if expected_yield > 0 else "Extend"
            action = "reduce duration 20-40%" if expected_yield > 0 else "add duration as safe-haven"
            return (
                f"FIXED INCOME: {direction} duration exposure. "
                f"Recommended: {action}. "
                f"Expected 10Y yield change: {expected_yield:+.0f}bps. "
                f"Consider receiving fixed in 2Y or 5Y swaps if hawkish shock expected. "
                f"Flight-to-quality positioning in TLT/TLH if crisis scenario elevated."
            )
        elif score.recommended_action_level == "REDUCE":
            return (
                f"FIXED INCOME: Reduce duration in {'+' if expected_yield > 0 else '-'} "
                f"direction. Expected 10Y move: {expected_yield:+.0f}bps. "
                f"Rate shock sub-score: {rate_score:.0f}/100."
            )
        return f"FIXED INCOME: Monitor duration. Rate shock score: {rate_score:.0f}/100."

    def _rates_guidance(
        self, score: CompositeRiskScore, tree: ScenarioTree, regime: RegimeType
    ) -> str:
        surprise_dir = "hawkish" if score.rate_shock_risk.score > 50 else "dovish"
        exp_2y = tree.expected_yield_change_bps * 1.3   # 2Y typically moves more on policy
        exp_10y = tree.expected_yield_change_bps

        if score.recommended_action_level in ("EMERGENCY_DERISKING", "HEDGE"):
            return (
                f"RATES: {surprise_dir.upper()} shock expected. "
                f"2Y estimate: {exp_2y:+.0f}bps; 10Y estimate: {exp_10y:+.0f}bps. "
                f"Consider steepener/flattener trades based on surprise direction. "
                f"If hawkish: 2s10s flattener. If dovish: 2s10s steepener. "
                f"Monitor SOFR futures strip repricing for first-mover signal. "
                f"Add convexity via options on rates where available."
            )
        return (
            f"RATES: Monitor curve dynamics. "
            f"Expected 2Y: {exp_2y:+.0f}bps; 10Y: {exp_10y:+.0f}bps. "
            f"Rate shock sub-score: {score.rate_shock_risk.score:.0f}/100."
        )

    def _fx_guidance(
        self, score: CompositeRiskScore, tree: ScenarioTree, regime: RegimeType
    ) -> str:
        fx_score = score.fx_risk.score
        expected_dxy = sum(s.probability * s.dxy_change_pct for s in tree.scenarios)

        if fx_score >= 55:
            dxy_dir = "stronger DXY" if expected_dxy > 0 else "weaker DXY"
            return (
                f"FX: Significant FX dislocation expected. Expected DXY move: {expected_dxy:+.2f}%. "
                f"{'USD strength' if expected_dxy > 0 else 'USD weakness'} scenario. "
                f"Reduce EM FX exposure — EM FX historically hardest hit in USD strength / risk-off regimes. "
                f"Consider JPY long as safe-haven vs. high-beta EM (BRL, ZAR, TRY). "
                f"FX carry positions at elevated unwind risk."
            )
        elif fx_score >= 35:
            return (
                f"FX: Moderate FX risk. Expected DXY: {expected_dxy:+.2f}%. "
                f"Reduce EM FX carry if composite risk score elevated."
            )
        return f"FX: FX risk sub-score {fx_score:.0f}/100 — within normal range."

    def _commodity_guidance(
        self, score: CompositeRiskScore, tree: ScenarioTree
    ) -> str:
        comm_score = score.commodity_shock_risk.score
        expected_gold = sum(s.probability * s.gold_change_pct for s in tree.scenarios)
        expected_oil = sum(s.probability * s.oil_change_pct for s in tree.scenarios)

        if comm_score >= 55:
            return (
                f"COMMODITIES: Elevated commodity dislocation expected. "
                f"Gold: {expected_gold:+.1f}% ({"flight-to-safety bid" if expected_gold > 0 else "risk-on selloff"}). "
                f"Oil: {expected_oil:+.1f}% (growth demand signal). "
                f"Consider gold long as portfolio hedge in tail scenarios. "
                f"Reduce cyclical commodity exposure (industrial metals, energy) if risk-off regime."
            )
        return f"COMMODITIES: Sub-score {comm_score:.0f}/100. "

    def _credit_guidance(
        self, score: CompositeRiskScore, tree: ScenarioTree, regime: RegimeType
    ) -> str:
        credit_score = score.credit_spread_risk.score
        expected_hy = sum(s.probability * s.credit_hy_change_bps for s in tree.scenarios)

        if credit_score >= 60:
            return (
                f"CREDIT: High spread widening risk. Expected HY move: {expected_hy:+.0f}bps. "
                f"Reduce HY and sub-IG credit exposure. Rotate to higher-quality IG or Treasuries. "
                f"CDX HY protection recommended as portfolio hedge. "
                f"Watch for liquidity premium emergence in lower-rated names. "
                f"EM credit particularly vulnerable."
            )
        elif credit_score >= 40:
            return (
                f"CREDIT: Moderate widening risk ({expected_hy:+.0f}bps expected HY). "
                f"Reduce lower-rated HY exposure. Maintain IG positions."
            )
        return f"CREDIT: Sub-score {credit_score:.0f}/100. Spreads within acceptable range."

    def _volatility_guidance(
        self, score: CompositeRiskScore, tree: ScenarioTree, state: MarketStateSnapshot
    ) -> str:
        vol_score = score.volatility_risk.score
        expected_vix = tree.expected_vix_change
        current_vix = None
        if state.volatility and state.volatility.vix_spot:
            current_vix = state.volatility.vix_spot

        if vol_score >= 60:
            vix_desc = f" (current VIX: {current_vix:.1f})" if current_vix else ""
            return (
                f"VOLATILITY{vix_desc}: Significant vol expansion expected (+{expected_vix:.1f} pts). "
                f"Long vol positions benefit — consider VIX calls, UVXY, or long variance. "
                f"Short vol strategies (covered calls, short straddles) at high risk — "
                f"reduce or close short vega positions. "
                f"Put-spread overlays on equity portfolio recommended."
            )
        elif vol_score >= 40:
            return (
                f"VOLATILITY: Moderate vol expansion expected (+{expected_vix:.1f} pts). "
                f"Reduce net short vega in portfolio. Consider low-cost tail hedges."
            )
        return f"VOLATILITY: Sub-score {vol_score:.0f}/100. Vol surface within normal range."

    # ------------------------------------------------------------------
    # Hedge Generation
    # ------------------------------------------------------------------

    def _generate_hedges(
        self,
        event: MacroEvent,
        score: CompositeRiskScore,
        tree: ScenarioTree,
        state: MarketStateSnapshot,
        action_level: str,
    ) -> List[HedgeRecommendation]:
        hedges = []

        if action_level == "NO_ACTION":
            return hedges

        # Determine urgency based on market timing
        if event.full_weekend_gap:
            urgency = "PRE-OPEN"
        elif event.is_after_hours:
            urgency = "PRE-OPEN"
        else:
            urgency = "INTRADAY"

        # Equity Tail Protection
        if score.equity_downside_risk.score >= 40 and action_level in ("HEDGE", "EMERGENCY_DERISKING", "REDUCE"):
            tail_prob = sum(s.probability for s in tree.scenarios if s.is_tail_scenario)
            tail_loss = tree.tail_loss_5pct
            hedges.append(HedgeRecommendation(
                asset_class=AssetClass.EQUITY,
                instrument_description=(
                    f"SPX put spread: buy {abs(tail_loss/2):.0f}% OTM puts, "
                    f"sell {abs(tail_loss):.0f}% OTM puts; 2-4 week expiry"
                ),
                action="BUY",
                urgency=urgency,
                sizing_guidance="5-10% of equity book DV01 / notional equivalent",
                rationale=(
                    f"Tail scenario probability {tail_prob:.0%}; 5th pct loss estimate {tail_loss:.1f}%. "
                    f"Put spread limits cost while providing downside protection."
                ),
                estimated_cost_bps=15.0,
                estimated_protection_value=f"~{abs(tail_loss):.1f}% downside protection",
                requires_pm_approval=True,
            ))

        # Duration / Rates Hedge
        if score.rate_shock_risk.score >= 45:
            is_hawkish = score.rate_shock_risk.primary_driver and "hawkish" in score.rate_shock_risk.primary_driver.lower()
            hedges.append(HedgeRecommendation(
                asset_class=AssetClass.RATES,
                instrument_description=(
                    "Treasury futures: sell TY (10Y) or TU (2Y) futures; "
                    "or receive fixed on 2Y or 5Y OIS swap"
                ) if is_hawkish else (
                    "Treasury futures: buy TY (10Y) or ZB (30Y) futures as safe-haven duration"
                ),
                action="SELL" if is_hawkish else "BUY",
                urgency=urgency,
                sizing_guidance="10-20% of portfolio DV01 offset",
                rationale=(
                    f"Rate shock risk score {score.rate_shock_risk.score:.0f}/100. "
                    f"Expected 10Y move {tree.expected_yield_change_bps:+.0f}bps."
                ),
                estimated_cost_bps=2.0,
                requires_pm_approval=True,
            ))

        # Credit Hedge
        if score.credit_spread_risk.score >= 50:
            expected_hy = sum(s.probability * s.credit_hy_change_bps for s in tree.scenarios)
            hedges.append(HedgeRecommendation(
                asset_class=AssetClass.CREDIT,
                instrument_description="Buy CDX HY protection (short risk); 5Y on-the-run series",
                action="BUY",
                urgency=urgency,
                sizing_guidance="3-8% of credit book notional equivalent",
                rationale=(
                    f"Credit spread risk {score.credit_spread_risk.score:.0f}/100. "
                    f"Expected HY widening {expected_hy:+.0f}bps. CDX HY is most liquid hedge instrument."
                ),
                estimated_cost_bps=8.0,
                estimated_protection_value=f"+{expected_hy:.0f}bps HY move protection",
                requires_pm_approval=True,
            ))

        # FX Hedge
        if score.fx_risk.score >= 50:
            expected_dxy = sum(s.probability * s.dxy_change_pct for s in tree.scenarios)
            hedges.append(HedgeRecommendation(
                asset_class=AssetClass.FX,
                instrument_description=(
                    "Buy USD/sell EM FX basket (BRL, ZAR, MXN) if expecting USD strength; "
                    "or buy JPY as safe-haven vs. risk-correlated FX"
                ),
                action="BUY" if expected_dxy > 0 else "SELL",
                urgency=urgency,
                sizing_guidance="Cover 50-75% of EM FX exposure",
                rationale=(
                    f"FX risk score {score.fx_risk.score:.0f}/100. "
                    f"Expected DXY {expected_dxy:+.2f}%."
                ),
                requires_pm_approval=True,
            ))

        # Vol hedge for short-vol books
        if score.volatility_risk.score >= 55:
            hedges.append(HedgeRecommendation(
                asset_class=AssetClass.VOLATILITY,
                instrument_description=(
                    "VIX call spreads (e.g., +20/-30 calls); or buy VIXM futures; "
                    "or add long gamma via 1-month ATM straddles on SPX"
                ),
                action="BUY",
                urgency="IMMEDIATE" if score.volatility_risk.score >= 70 else urgency,
                sizing_guidance="Size to neutralize net short vega in portfolio",
                rationale=(
                    f"Vol risk score {score.volatility_risk.score:.0f}/100. "
                    f"Expected VIX change +{tree.expected_vix_change:.1f}pts. "
                    f"Short vol strategies at risk of acceleration."
                ),
                estimated_cost_bps=20.0,
                requires_pm_approval=True,
            ))

        return hedges

    def _estimate_var_change(
        self, score: CompositeRiskScore, tree: ScenarioTree
    ) -> Optional[float]:
        """
        Rough estimate of portfolio VaR change as fraction of current VaR.
        Higher composite score → higher VaR increase.
        This is illustrative; real VaR computation requires portfolio Greeks.
        """
        if score.composite_score < 20:
            return None
        # Rule of thumb: 1pt of composite score ≈ 0.5% increase in portfolio VaR
        return score.composite_score * 0.005

    def _score_to_alert(self, score: float) -> AlertLevel:
        if score >= 75:
            return AlertLevel.CRITICAL
        elif score >= 55:
            return AlertLevel.HIGH
        elif score >= 35:
            return AlertLevel.MEDIUM
        return AlertLevel.LOW

    def _build_notes(
        self,
        event: MacroEvent,
        score: CompositeRiskScore,
        tree: ScenarioTree,
    ) -> str:
        notes = []

        if event.full_weekend_gap and tree.monday_gap_estimate_pct:
            notes.append(
                f"Monday gap estimate: {tree.monday_gap_estimate_pct:.1f}% "
                f"(confidence: {tree.monday_gap_confidence:.0%}). "
                f"Execute defensive positioning before Monday 9:30 AM ET open."
            )

        if score.composite_score >= 65:
            trading_halt_prob = max(
                s.trading_halt_probability for s in tree.scenarios if s.is_tail_scenario
            ) if tree.scenarios else 0
            if trading_halt_prob > 0.05:
                notes.append(
                    f"Trading halt probability in tail scenario: {trading_halt_prob:.0%}. "
                    f"Ensure liquidity in non-equity instruments (futures, ETFs, FX) for Monday hedging."
                )

        if score.score_reliability != "HIGH":
            notes.append(
                f"Score reliability: {score.score_reliability}. "
                f"Data completeness: {score.overall_data_quality:.0%}. "
                f"Use wider error bars on all impact estimates."
            )

        notes.append(
            "All recommendations require PM/risk officer authorization. "
            "This output is advisory, not an execution order."
        )

        return " | ".join(notes)
