"""
macro_shock/__main__.py

CLI entry point for the Macro Shock Risk Engine.
Enables: python -m macro_shock [command] [options]

Commands:
  monitor     Continuous real-time event monitoring (production mode)
  analyze     Analyze a single event from JSON or CLI flags
  backtest    Run historical event study backtest
  serve       Start the REST API server
  health      Run system health check
  demo        Run a canned scenario demonstration

Examples:
  python -m macro_shock monitor --config configs/production.yaml
  python -m macro_shock analyze --event-file event.json
  python -m macro_shock backtest --start 2020-01-01 --end 2024-01-01
  python -m macro_shock serve --port 8000
  python -m macro_shock health --env production
  python -m macro_shock demo --scenario weekend_crisis
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import structlog

# Ensure src is importable when run as python -m macro_shock
_src = Path(__file__).parent.parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


def _configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    import logging
    processors = [
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.stdlib.add_log_level,
    ]
    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(processors=processors)
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))


def _load_config(config_path: str | None, env: str) -> dict:
    import yaml
    if config_path:
        p = Path(config_path)
    else:
        p = Path(__file__).parent.parent.parent / "configs" / f"{env}.yaml"

    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f) or {}
    return {}


# ──────────────────────────────────────────────────────────────
# Command: monitor
# ──────────────────────────────────────────────────────────────

def cmd_monitor(args: argparse.Namespace) -> None:
    """Continuous real-time event monitoring loop."""
    import time
    from macro_shock.orchestration.pipeline import MacroShockPipeline
    from macro_shock.monitoring.alert_manager import HeartbeatMonitor

    cfg = _load_config(args.config, args.env)
    pipeline = MacroShockPipeline(config=cfg, environment=args.env)
    heartbeat = HeartbeatMonitor(interval_seconds=300)

    logger = structlog.get_logger("monitor")
    logger.info("monitor_started", env=args.env, poll_interval=args.interval)

    print(f"\n[MSRE] Monitor active | env={args.env} | poll={args.interval}s")
    print("[MSRE] Press Ctrl+C to stop.\n")

    try:
        while True:
            heartbeat.heartbeat()
            heartbeat.check()
            # In production: poll event feed here and call pipeline.process_raw_event(...)
            # Placeholder: log alive signal every interval
            logger.debug("monitor_alive")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("monitor_stopped")
        print("\n[MSRE] Monitor stopped.")


# ──────────────────────────────────────────────────────────────
# Command: analyze
# ──────────────────────────────────────────────────────────────

def cmd_analyze(args: argparse.Namespace) -> None:
    """Analyze a single event and print the full risk report."""
    from macro_shock.orchestration.pipeline import MacroShockPipeline
    from macro_shock.data.ingestion import MarketStateBuilder

    cfg = _load_config(args.config, args.env)
    pipeline = MacroShockPipeline(config=cfg, environment=args.env)

    if args.event_file:
        with open(args.event_file) as f:
            raw_event = json.load(f)
    else:
        # Build minimal event from CLI flags
        if not args.title or not args.institution or not args.event_time:
            print("ERROR: --title, --institution, and --event-time are required without --event-file")
            sys.exit(1)
        raw_event = {
            "title": args.title,
            "institution": args.institution,
            "event_time": args.event_time,
            "speaker": args.speaker or "",
            "speaker_role": args.speaker_role or "",
            "prepared_remarks": args.text or "",
        }

    from datetime import datetime, timezone
    try:
        event_time = datetime.fromisoformat(raw_event["event_time"]).astimezone(timezone.utc)
    except Exception:
        event_time = datetime.now(timezone.utc)

    market_state = MarketStateBuilder.build_synthetic(
        as_of=event_time,
        calendar=pipeline.calendar,
        stress_level=args.stress,
        seed=42,
    )

    ctx = pipeline.process_raw_event(raw_event, market_state=market_state)

    # Print structured output
    _print_risk_report(ctx)

    if args.output:
        result = {}
        if ctx.risk_score:
            result["composite_score"] = ctx.risk_score.composite_score
            result["severity"] = ctx.risk_score.severity.value
            result["action_level"] = ctx.risk_score.recommended_action_level
            result["summary"] = ctx.risk_score.summary
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nOutput written to: {args.output}")


def _print_risk_report(ctx) -> None:
    """Print a concise risk report to stdout."""
    sep = "─" * 65
    print(f"\n{sep}")
    print("  MACRO SHOCK RISK ENGINE — ANALYSIS REPORT")
    print(sep)

    if ctx.event:
        e = ctx.event
        print(f"  Event:    {e.title}")
        print(f"  Type:     {e.event_type.value}  |  Severity: {e.severity.value} ({e.severity_score:.1f})")
        print(f"  Weekend:  {e.is_weekend}  |  Gap Corridor: {e.full_weekend_gap}")
        if e.hours_until_next_open:
            print(f"  Hours to open: {e.hours_until_next_open:.1f}h")

    if ctx.policy_surprise:
        ps = ctx.policy_surprise
        hd = ps.hawkish_dovish
        stance = hd.stance.value if hd else "N/A"
        print(f"\n  Policy:   {stance}  |  Surprise: {ps.composite_surprise_magnitude:.2f}  |  Direction: {ps.net_direction:+.2f}")
        if hd and hd.crisis_language_detected:
            print("  ⚠  Crisis language detected")

    if ctx.risk_score:
        rs = ctx.risk_score
        print(f"\n  ┌─ COMPOSITE RISK SCORE: {rs.composite_score:.1f}/100  [{rs.severity.value}]")
        print(f"  │  Regime: {rs.regime.value}  ×{rs.regime_multiplier:.2f}  |  Gap: ×{rs.gap_risk_multiplier:.2f}")
        print(f"  │  Action: {rs.recommended_action_level}")
        print(f"  └─ Reliability: {rs.score_reliability}")

    if ctx.scenario_tree:
        tree = ctx.scenario_tree
        print(f"\n  Scenarios: E[equity]={tree.expected_equity_impact_pct:+.1f}%  "
              f"| 5th Pct={tree.tail_loss_5pct:.1f}%  "
              f"| E[ΔVix]={tree.expected_vix_change:+.1f}pts")
        if tree.monday_gap_estimate_pct is not None:
            print(f"             Monday gap est: {tree.monday_gap_estimate_pct:+.1f}%")

    if ctx.portfolio_impact:
        pi = ctx.portfolio_impact
        print(f"\n  Portfolio: {pi.action_level}")
        for h in pi.hedge_recommendations[:3]:
            print(f"    [{h.urgency}] {h.action} {h.asset_class.value.upper()} — {h.instrument_description[:55]}")

    if ctx.alerts:
        print(f"\n  Alerts: {len(ctx.alerts)}")
        for a in ctx.alerts[:3]:
            print(f"    [{a.level.value}] {a.title}")

    print(sep + "\n")


# ──────────────────────────────────────────────────────────────
# Command: backtest
# ──────────────────────────────────────────────────────────────

def cmd_backtest(args: argparse.Namespace) -> None:
    """Run historical event study backtest."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "examples"))

    from macro_shock.orchestration.pipeline import MacroShockPipeline
    from macro_shock.backtesting.event_study import BacktestEngine, TimestampGuard, TransactionCostModel
    from macro_shock.data_schema.models import BacktestEvent, EventType

    cfg = _load_config(args.config, args.env)
    pipeline = MacroShockPipeline(config=cfg, environment=args.env)

    print(f"[Backtest] Loading synthetic events...")
    from synthetic_data_generator import generate_market_data_df, generate_synthetic_events
    df = generate_market_data_df(n_days=1500, stress_profile="normal")
    guard = TimestampGuard(df, timestamp_col="timestamp")
    engine = BacktestEngine(pipeline=pipeline, market_data_guard=guard,
                            cost_model=TransactionCostModel())

    raw_events = generate_synthetic_events()
    events = []
    for e in raw_events:
        try:
            events.append(BacktestEvent(
                event_id=e["event_id"], event_date=e["event_date"],
                event_type=EventType(e["event_type"]), is_weekend=e["is_weekend"],
                institution=e["institution"], speaker=e.get("speaker"),
                description=e["description"],
                realized_spx_next_session_return=e.get("realized_spx_next_session_return"),
                realized_10y_yield_change_bps=e.get("realized_10y_yield_change_bps"),
                realized_vix_change=e.get("realized_vix_change"),
                trading_halt_occurred=e.get("trading_halt_occurred", False),
                data_validated=True,
            ))
        except Exception as ex:
            print(f"  Skipping {e['event_id']}: {ex}")

    result = engine.run(events)
    print(f"\n{'─'*50}")
    print(f"  BACKTEST RESULTS  ({result.n_events} events)")
    print(f"{'─'*50}")
    print(f"  Score accuracy:      {result.score_accuracy:.3f}")
    print(f"  Precision@CRITICAL:  {result.precision_at_critical:.3f}")
    print(f"  Recall@CRITICAL:     {result.recall_at_critical:.3f}")
    print(f"  Max Drawdown:        {result.max_drawdown:.3f}")
    print(f"  ES (5%):             {result.expected_shortfall_5pct:.3f}")
    print(f"  Gap Estimate Error:  {result.avg_weekend_gap_estimate_error:.2f}%")
    print(f"  {result.notes}")
    print()


# ──────────────────────────────────────────────────────────────
# Command: serve
# ──────────────────────────────────────────────────────────────

def cmd_serve(args: argparse.Namespace) -> None:
    """Start the REST API server."""
    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn not installed. Run: pip install uvicorn[standard]")
        sys.exit(1)

    os.environ.setdefault("MSRE_ENVIRONMENT", args.env)
    os.environ.setdefault("MSRE_CONFIG", args.config or f"python/configs/{args.env}.yaml")

    print(f"[MSRE] Starting API server | host={args.host}:{args.port} | env={args.env}")
    uvicorn.run(
        "macro_shock.orchestration.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info" if args.env != "production" else "warning",
        workers=1 if args.reload else args.workers,
    )


# ──────────────────────────────────────────────────────────────
# Command: health
# ──────────────────────────────────────────────────────────────

def cmd_health(args: argparse.Namespace) -> None:
    """Run system health check."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/health_check.py", "--env", args.env] +
        (["--verbose"] if args.verbose else []),
        cwd=Path(__file__).parent.parent.parent.parent,
    )
    sys.exit(result.returncode)


# ──────────────────────────────────────────────────────────────
# Command: demo
# ──────────────────────────────────────────────────────────────

def cmd_demo(args: argparse.Namespace) -> None:
    """Run a canned scenario demonstration."""
    import subprocess
    cmd = [
        sys.executable, "examples/run_end_to_end.py",
        "--env", args.env,
        "--event-scenario", args.scenario,
        "--stress-level", str(args.stress),
    ]
    if args.all:
        cmd = [sys.executable, "examples/run_end_to_end.py", "--env", args.env, "--run-all-scenarios"]

    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent.parent.parent)
    sys.exit(result.returncode)


# ──────────────────────────────────────────────────────────────
# Argument parser
# ──────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m macro_shock",
        description="Macro Shock Risk Engine — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env", default=os.getenv("MSRE_ENVIRONMENT", "research"),
                        choices=["research", "staging", "production"])
    parser.add_argument("--config", default=None, help="Path to YAML config file")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-format", default="console", choices=["console", "json"])

    sub = parser.add_subparsers(dest="command", required=True)

    # monitor
    p_mon = sub.add_parser("monitor", help="Continuous real-time event monitoring")
    p_mon.add_argument("--interval", type=int, default=30, help="Poll interval seconds")
    p_mon.set_defaults(func=cmd_monitor)

    # analyze
    p_ana = sub.add_parser("analyze", help="Analyze a single event")
    p_ana.add_argument("--event-file", help="Path to event JSON file")
    p_ana.add_argument("--title", help="Event title (if not using --event-file)")
    p_ana.add_argument("--institution", help="Institution name")
    p_ana.add_argument("--event-time", help="Event timestamp ISO 8601")
    p_ana.add_argument("--speaker", default="")
    p_ana.add_argument("--speaker-role", default="")
    p_ana.add_argument("--text", default="", help="Prepared remarks / raw text")
    p_ana.add_argument("--stress", type=float, default=0.35, help="Market stress level 0-1")
    p_ana.add_argument("--output", default=None, help="Write JSON output to file")
    p_ana.set_defaults(func=cmd_analyze)

    # backtest
    p_bt = sub.add_parser("backtest", help="Run historical event study backtest")
    p_bt.add_argument("--start", default=None)
    p_bt.add_argument("--end", default=None)
    p_bt.set_defaults(func=cmd_backtest)

    # serve
    p_srv = sub.add_parser("serve", help="Start the REST API server")
    p_srv.add_argument("--host", default="0.0.0.0")
    p_srv.add_argument("--port", type=int, default=8000)
    p_srv.add_argument("--workers", type=int, default=2)
    p_srv.add_argument("--reload", action="store_true", help="Hot-reload (development only)")
    p_srv.set_defaults(func=cmd_serve)

    # health
    p_hc = sub.add_parser("health", help="System health check")
    p_hc.add_argument("--verbose", "-v", action="store_true")
    p_hc.set_defaults(func=cmd_health)

    # demo
    p_demo = sub.add_parser("demo", help="Run a canned scenario demonstration")
    p_demo.add_argument("--scenario", default="weekend_crisis",
                        choices=["weekend_crisis", "hawkish_surprise", "dovish_pivot", "friday_close_ambiguous"])
    p_demo.add_argument("--stress", type=float, default=0.4)
    p_demo.add_argument("--all", action="store_true", help="Run all scenarios")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _configure_logging(args.log_level, args.log_format)
    args.func(args)


if __name__ == "__main__":
    main()
