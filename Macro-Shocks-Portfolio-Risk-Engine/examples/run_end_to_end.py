"""
examples/run_end_to_end.py

Minimal end-to-end example demonstrating the full MSRE pipeline.

Usage:
    python examples/run_end_to_end.py --env research --use-synthetic-data
    python examples/run_end_to_end.py --event-scenario weekend_crisis
    python examples/run_end_to_end.py --run-backtest
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure src is on path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "src"))

import structlog
import yaml

from macro_shock.data.ingestion import MarketStateBuilder
from macro_shock.event_detection.calendar import MarketCalendar
from macro_shock.orchestration.pipeline import MacroShockPipeline

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Canned Event Scenarios for Demonstration
# ---------------------------------------------------------------------------

SCENARIOS = {
    "weekend_crisis": {
        "title": "Emergency Federal Reserve Statement — Weekend",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": "2024-03-09T19:00:00-05:00",  # Saturday 7pm ET
        "description": "Emergency Federal Reserve statement regarding financial stability concerns.",
        "headline_summary": "Fed announces emergency backstop facilities citing systemic risk concerns.",
        "prepared_remarks": (
            "The Federal Reserve Board has voted unanimously to establish emergency lending facilities "
            "to address financial stability concerns in the banking system. We are taking extraordinary "
            "measures to ensure liquidity and prevent contagion. The situation is severe and systemic risk "
            "is a real concern. We will do whatever it takes to stabilize financial conditions. "
            "Emergency rate action may be considered at the next intermeeting call."
        ),
        "qa_section": (
            "Q: Are you considering emergency rate cuts? "
            "A: We are not ruling anything out. The financial stability concerns outweigh inflation "
            "considerations at this moment. We are acting urgently and decisively. "
            "Q: Is there a risk of bank runs? "
            "A: We are monitoring systemic risk very carefully and have activated crisis measures."
        ),
    },
    "hawkish_surprise": {
        "title": "FOMC Press Conference — Hawkish Surprise",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": "2024-01-31T18:30:00-05:00",  # Wednesday afternoon
        "description": "FOMC press conference following rate decision. Unexpectedly hawkish tone.",
        "headline_summary": "Fed signals higher for longer; rate cuts premature; inflation not yet under control.",
        "prepared_remarks": (
            "Inflation remains too high and above our 2% target. We are committed to returning inflation "
            "to target and will not hesitate to raise rates further if necessary. It would be premature "
            "to declare victory on inflation. The labor market remains tight. "
            "We will keep policy sufficiently restrictive for as long as it takes. "
            "Rate cuts are not on the table in the near term. We have more work to do."
        ),
        "qa_section": (
            "Q: When will you cut rates? "
            "A: That question is premature. We need to see more data showing sustained inflation decline. "
            "Sufficiently restrictive policy must be maintained. "
            "Q: Are additional hikes possible? "
            "A: Yes, additional increases remain on the table if the data warrant."
        ),
    },
    "dovish_pivot": {
        "title": "Jackson Hole Speech — Dovish Pivot Signal",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": "2024-08-23T14:00:00-06:00",  # Friday afternoon Mountain Time
        "description": "Powell Jackson Hole speech signals easing cycle beginning.",
        "headline_summary": "Powell: 'It is time' to cut rates. Inflation substantially improved.",
        "prepared_remarks": (
            "Inflation has declined substantially toward our 2% goal. The labor market has cooled "
            "meaningfully from its overheated state. The upside risks to inflation have diminished. "
            "The time has come for policy to adjust. The direction of travel is clear. "
            "We will do everything we can to support a strong labor market as we make progress "
            "toward price stability. We are confident that inflation is on a sustainable path lower."
        ),
        "qa_section": (
            "Q: How big will the first cut be? "
            "A: We will be guided by the totality of data. We have ample room to respond. "
            "Q: Is this a pivot? "
            "A: The data has evolved in a way that supports beginning to dial back policy restriction."
        ),
    },
    "friday_close_ambiguous": {
        "title": "Fed Chair Remarks — Friday After Close",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": "2024-11-01T20:00:00-04:00",  # Friday 8pm ET
        "description": "Powell remarks at Friday evening economic conference after market close.",
        "headline_summary": "Powell says Fed remains data dependent; path uncertain.",
        "prepared_remarks": (
            "The path forward for monetary policy is highly uncertain. We remain data dependent "
            "and will act as appropriate given the incoming information. We are committed to our dual "
            "mandate but face a challenging environment with significant uncertainty on both sides. "
            "We are not on a preset course. The full effects of our tightening have yet to be felt."
        ),
        "qa_section": (
            "Q: What is the next move? "
            "A: We are watching the data carefully. It could be higher, it could be lower, depending on data. "
            "The wide range of outcomes reflects genuine uncertainty in the economic environment."
        ),
    },
}


def run_scenario(scenario_name: str, config: dict, stress_level: float = 0.35) -> None:
    """Run a single named scenario through the full pipeline."""
    if scenario_name not in SCENARIOS:
        print(f"Unknown scenario: {scenario_name}. Available: {list(SCENARIOS.keys())}")
        return

    scenario = SCENARIOS[scenario_name]
    logger.info("running_scenario", scenario=scenario_name)

    pipeline = MacroShockPipeline(config=config, environment="research")

    # Build synthetic market state calibrated to the event time
    event_time = datetime.fromisoformat(scenario["event_time"]).astimezone(timezone.utc)
    market_state = MarketStateBuilder.build_synthetic(
        as_of=event_time,
        calendar=pipeline.calendar,
        stress_level=stress_level,
        seed=42,
    )

    context = pipeline.process_raw_event(raw_event=scenario, market_state=market_state)

    # Print results
    print("\n" + "=" * 70)
    print(f"  MACRO SHOCK RISK ENGINE — {scenario_name.upper()}")
    print("=" * 70)

    if context.event:
        print(f"\n  EVENT: {context.event.title}")
        print(f"  Type:  {context.event.event_type.value}")
        print(f"  Severity: {context.event.severity.value} ({context.event.severity_score:.1f}/100)")
        print(f"  Weekend Gap: {context.event.full_weekend_gap}")
        if context.event.hours_until_next_open:
            print(f"  Hours to Open: {context.event.hours_until_next_open:.1f}h")

    if context.policy_surprise:
        ps = context.policy_surprise
        hd = ps.hawkish_dovish
        print(f"\n  LANGUAGE INTELLIGENCE:")
        if hd:
            print(f"  Stance:       {hd.stance.value}")
            print(f"  HD Score:     {hd.overall_score:+.3f} (−1=dovish, +1=hawkish)")
            print(f"  Confidence:   {hd.confidence:.0%}")
            print(f"  Crisis Lang:  {hd.crisis_language_detected}")
            print(f"  Policy Rev:   {hd.policy_reversal_language}")
        print(f"  Surprise Mag: {ps.composite_surprise_magnitude:.3f}")
        print(f"  Net Direction:{ps.net_direction:+.3f}")

    if context.risk_score:
        rs = context.risk_score
        print(f"\n  COMPOSITE RISK SCORE: {rs.composite_score:.1f}/100 [{rs.severity.value}]")
        print(f"  Regime: {rs.regime.value}")
        print(f"  Regime Multiplier: {rs.regime_multiplier:.2f}x")
        print(f"  Gap Multiplier:    {rs.gap_risk_multiplier:.2f}x")
        print(f"  Action Level: {rs.recommended_action_level}")
        print(f"\n  SUB-SCORES:")
        sub_scores = [
            rs.liquidity_risk, rs.volatility_risk, rs.rate_shock_risk,
            rs.equity_downside_risk, rs.credit_spread_risk, rs.fx_risk,
            rs.commodity_shock_risk, rs.weekend_gap_risk, rs.policy_ambiguity_risk,
        ]
        for ss in sorted(sub_scores, key=lambda s: s.score, reverse=True):
            bar = "█" * int(ss.score / 10) + "░" * (10 - int(ss.score / 10))
            print(f"  [{bar}] {ss.score:5.1f}  {ss.name}")

    if context.scenario_tree:
        tree = context.scenario_tree
        print(f"\n  SCENARIO TREE ({len(tree.scenarios)} scenarios):")
        print(f"  Expected Equity:  {tree.expected_equity_impact_pct:+.2f}%")
        print(f"  Expected 10Y Yld: {tree.expected_yield_change_bps:+.0f}bps")
        print(f"  Expected VIX Δ:   {tree.expected_vix_change:+.1f}pts")
        print(f"  Tail Loss (5%):   {tree.tail_loss_5pct:.1f}%")
        print(f"  Tail Loss (1%):   {tree.tail_loss_1pct:.1f}%")
        if tree.monday_gap_estimate_pct:
            print(f"  Monday Gap Est:   {tree.monday_gap_estimate_pct:.1f}%")
        print(f"\n  {'Scenario':<35} {'Prob':>6}  {'Equity':>8}  {'10Y':>8}  {'VIX':>6}")
        print(f"  {'-'*65}")
        for s in sorted(tree.scenarios, key=lambda x: x.probability, reverse=True):
            tail_mark = " *" if s.is_tail_scenario else ""
            print(
                f"  {s.name:<35} {s.probability:>5.1%}  "
                f"{s.equity_impact_pct:>+7.1f}%  {s.yield_10y_change_bps:>+7.0f}bps  "
                f"{s.vix_change:>+5.1f}{tail_mark}"
            )

    if context.portfolio_impact:
        pi = context.portfolio_impact
        print(f"\n  PORTFOLIO IMPACT: [{pi.action_level}]")
        if pi.recommended_gross_exposure_change:
            print(f"  Gross Exposure Change: {pi.recommended_gross_exposure_change:.0%}")
        if pi.recommended_leverage_change:
            print(f"  Leverage Change:       {pi.recommended_leverage_change:.0%}")
        if pi.hedge_recommendations:
            print(f"\n  HEDGE RECOMMENDATIONS ({len(pi.hedge_recommendations)}):")
            for h in pi.hedge_recommendations:
                print(f"  [{h.urgency}] {h.action} {h.asset_class.value.upper()}: {h.instrument_description[:60]}")
                print(f"            Sizing: {h.sizing_guidance}")

    if context.alerts:
        print(f"\n  ALERTS ({len(context.alerts)}):")
        for a in context.alerts:
            print(f"  [{a.level.value}] {a.title}")

    if context.failed_stages:
        print(f"\n  FAILED STAGES: {context.failed_stages}")
        for err in context.errors:
            print(f"  ERROR: {err}")

    print("\n" + "=" * 70 + "\n")


def run_backtest(config: dict) -> None:
    """Run a minimal backtest over synthetic events."""
    from examples.synthetic_data_generator import generate_market_data_df, generate_synthetic_events
    from macro_shock.backtesting.event_study import BacktestEngine, TimestampGuard, TransactionCostModel
    from macro_shock.data_schema.models import BacktestEvent, EventType

    print("\nRunning backtest over synthetic events...")

    df = generate_market_data_df(n_days=1000, stress_profile="normal")
    guard = TimestampGuard(df, timestamp_col="timestamp")

    pipeline = MacroShockPipeline(config=config, environment="research")
    engine = BacktestEngine(
        pipeline=pipeline,
        market_data_guard=guard,
        cost_model=TransactionCostModel(),
        config={"pre_event_lookback_days": 30},
    )

    raw_events = generate_synthetic_events()
    backtest_events = []
    for e in raw_events:
        try:
            be = BacktestEvent(
                event_id=e["event_id"],
                event_date=e["event_date"],
                event_type=EventType(e["event_type"]),
                is_weekend=e["is_weekend"],
                institution=e["institution"],
                speaker=e.get("speaker"),
                description=e["description"],
                realized_spx_next_session_return=e.get("realized_spx_next_session_return"),
                realized_10y_yield_change_bps=e.get("realized_10y_yield_change_bps"),
                realized_vix_change=e.get("realized_vix_change"),
                realized_hy_spread_change_bps=e.get("realized_hy_spread_change_bps"),
                trading_halt_occurred=e.get("trading_halt_occurred", False),
                emergency_action_followed=e.get("emergency_action_followed", False),
                data_validated=True,
            )
            backtest_events.append(be)
        except Exception as ex:
            print(f"  Skipping event {e['event_id']}: {ex}")

    result = engine.run(backtest_events)

    print("\n  BACKTEST RESULTS")
    print("  " + "-" * 40)
    print(f"  Events processed:      {result.n_events}")
    print(f"  Weekend events:        {result.n_weekend_events}")
    print(f"  Score accuracy (corr): {result.score_accuracy:.3f}")
    print(f"  Precision@CRITICAL:    {result.precision_at_critical:.3f}")
    print(f"  Recall@CRITICAL:       {result.recall_at_critical:.3f}")
    print(f"  Expected Shortfall 5%: {result.expected_shortfall_5pct:.3f}")
    print(f"  Max Drawdown:          {result.max_drawdown:.3f}")
    print(f"  Gap Estimate Error:    {result.avg_weekend_gap_estimate_error:.2f}%")
    print(f"  Notes: {result.notes}")


def main():
    parser = argparse.ArgumentParser(description="Macro Shock Risk Engine — End-to-End Demo")
    parser.add_argument("--env", default="research", choices=["research", "staging", "production"])
    parser.add_argument("--event-scenario", default="weekend_crisis", choices=list(SCENARIOS.keys()))
    parser.add_argument("--stress-level", type=float, default=0.35, help="Market stress level 0-1")
    parser.add_argument("--run-all-scenarios", action="store_true")
    parser.add_argument("--run-backtest", action="store_true")
    parser.add_argument("--config", default=None, help="Path to config YAML file")
    args = parser.parse_args()

    # Load config
    if args.config and Path(args.config).exists():
        with open(args.config) as f:
            config = yaml.safe_load(f)
    else:
        config = {
            "use_transformer": False,
            "audit_log_dir": "/tmp/msre_audit",
            "fail_fast": False,
            "alert_thresholds": None,
        }

    if args.run_backtest:
        run_backtest(config)
    elif args.run_all_scenarios:
        for name in SCENARIOS:
            run_scenario(name, config, stress_level=args.stress_level)
    else:
        run_scenario(args.event_scenario, config, stress_level=args.stress_level)


if __name__ == "__main__":
    main()
