"""
tests/unit/test_monitoring.py

Unit tests for the Monitoring and Alerting system.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from macro_shock.data_schema.models import (
    AlertLevel, CompositeRiskScore, EventType, HawkishDovishScore,
    MacroEvent, MarketSessionState, PolicyStance, PolicySurpriseVector,
    RegimeType, ScenarioOutcome, ScenarioTree, SeverityLevel, SubRiskScore,
)
from macro_shock.monitoring.alert_manager import AlertManager, AuditTrail, HeartbeatMonitor


# ─── Helpers ─────────────────────────────────────────────────

def make_sub_score(name: str, score: float, weight: float = 0.11) -> SubRiskScore:
    return SubRiskScore(name=name, score=score, weight=weight, primary_driver=f"{name} driver")


def make_composite(score: float, severity: SeverityLevel, action: str) -> CompositeRiskScore:
    w = 1.0 / 9
    return CompositeRiskScore(
        event_id="evt-test",
        composite_score=score,
        severity=severity,
        liquidity_risk=make_sub_score("Liquidity Risk", score * 0.9, w),
        volatility_risk=make_sub_score("Volatility Risk", score * 0.85, w),
        rate_shock_risk=make_sub_score("Rate Shock Risk", score * 0.95, w),
        equity_downside_risk=make_sub_score("Equity Downside Risk", score, w),
        credit_spread_risk=make_sub_score("Credit Spread Risk", score * 0.8, w),
        fx_risk=make_sub_score("FX Risk", score * 0.6, w),
        commodity_shock_risk=make_sub_score("Commodity Shock Risk", score * 0.5, w),
        weekend_gap_risk=make_sub_score("Weekend Gap Risk", score * 1.1 if score > 50 else 10, w),
        policy_ambiguity_risk=make_sub_score("Policy Ambiguity Risk", score * 0.4, w),
        regime=RegimeType.FRAGILE_RISK_ON,
        recommended_action_level=action,
        summary=f"Test score {score}",
    )


def make_scenario_tree(event_id: str, include_tail: bool = False) -> ScenarioTree:
    scenarios = [
        ScenarioOutcome(
            name="Benign", description="In line", probability=0.60,
            equity_impact_pct=-0.5, yield_10y_change_bps=3.0, vix_change=0.5,
            yield_2y_change_bps=4.0, credit_hy_change_bps=5.0,
            is_tail_scenario=False, liquidity_impairment=0.0,
            trading_halt_probability=0.0, forced_deleveraging_risk=0.0,
        ),
    ]
    if include_tail:
        scenarios.append(ScenarioOutcome(
            name="Disorderly Risk-Off", description="Tail", probability=0.40,
            equity_impact_pct=-8.0, yield_10y_change_bps=15.0, vix_change=18.0,
            yield_2y_change_bps=25.0, credit_hy_change_bps=200.0,
            is_tail_scenario=True, liquidity_impairment=0.7,
            trading_halt_probability=0.12, forced_deleveraging_risk=0.6,
        ))
    return ScenarioTree(
        event_id=event_id,
        regime=RegimeType.FRAGILE_RISK_ON,
        scenarios=scenarios,
        expected_equity_impact_pct=-1.0,
        expected_yield_change_bps=3.0,
        expected_vix_change=2.0,
        tail_loss_5pct=-3.0,
        tail_loss_1pct=-6.0,
        monday_gap_estimate_pct=-1.2 if not include_tail else -6.0,
        monday_gap_confidence=0.8,
    )


def make_event(event_id: str, is_weekend: bool = False) -> MacroEvent:
    return MacroEvent(
        event_id=event_id,
        detected_at=datetime.now(timezone.utc),
        event_timestamp=datetime.now(timezone.utc),
        event_type=EventType.WEEKEND_POLICY_ACTION if is_weekend else EventType.PRESS_CONFERENCE,
        severity=SeverityLevel.HIGH,
        severity_score=70.0,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        speaker_role="Chair",
        title="Test Event",
        is_weekend=is_weekend,
        full_weekend_gap=is_weekend,
        hours_until_next_open=52.0 if is_weekend else None,
        market_session_at_event=MarketSessionState.CLOSED_WEEKEND if is_weekend else MarketSessionState.OPEN,
    )


def make_portfolio_impact(action: str, kill_switch: bool = False):
    from macro_shock.data_schema.models import PortfolioImpactReport, HedgeRecommendation, AssetClass
    return PortfolioImpactReport(
        event_id="evt-test",
        score_id="score-test",
        action_level=action,
        alert_level=AlertLevel.HIGH if not kill_switch else AlertLevel.CRITICAL,
        trigger_kill_switch=kill_switch,
        human_override_required=True,
        equity_guidance="Reduce equity exposure.",
        rates_guidance="Hedge duration.",
        credit_guidance="Buy CDX protection.",
        hedge_recommendations=[
            HedgeRecommendation(
                asset_class=AssetClass.EQUITY,
                instrument_description="SPX put spread",
                action="BUY", urgency="PRE-OPEN",
                sizing_guidance="5% of equity notional",
                rationale="Tail protection",
                requires_pm_approval=True,
            )
        ] if action not in ("NO_ACTION", "MONITOR") else [],
    )


# ─── AlertManager ────────────────────────────────────────────

class TestAlertManager:

    @pytest.fixture
    def manager(self):
        return AlertManager(environment="research")

    def test_critical_score_generates_alert(self, manager):
        score = make_composite(80.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_scenario_tree("evt-test")
        event = make_event("evt-test")
        portfolio = make_portfolio_impact("EMERGENCY_DERISKING")

        alerts = manager.evaluate_and_alert(event, score, tree, portfolio)
        assert len(alerts) > 0
        levels = [a.level for a in alerts]
        assert AlertLevel.CRITICAL in levels

    def test_low_score_generates_low_or_no_alert(self, manager):
        score = make_composite(12.0, SeverityLevel.INFORMATIONAL, "NO_ACTION")
        tree = make_scenario_tree("evt-test2")
        event = make_event("evt-test2")
        portfolio = make_portfolio_impact("NO_ACTION")

        alerts = manager.evaluate_and_alert(event, score, tree, portfolio)
        for a in alerts:
            assert a.level in (AlertLevel.LOW, AlertLevel.MEDIUM)

    def test_kill_switch_generates_critical_alert(self, manager):
        score = make_composite(92.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_scenario_tree("evt-ks")
        event = make_event("evt-ks")
        portfolio = make_portfolio_impact("EMERGENCY_DERISKING", kill_switch=True)

        alerts = manager.evaluate_and_alert(event, score, tree, portfolio)
        titles = [a.title for a in alerts]
        assert any("KILL SWITCH" in t for t in titles)

    def test_weekend_gap_alert_for_negative_monday_gap(self, manager):
        score = make_composite(65.0, SeverityLevel.HIGH, "HEDGE")
        # Create tree with big negative Monday gap
        tree = make_scenario_tree("evt-gap")
        tree.monday_gap_estimate_pct = -4.5  # Beyond CRITICAL threshold -4.0
        event = make_event("evt-gap", is_weekend=True)
        portfolio = make_portfolio_impact("HEDGE")

        alerts = manager.evaluate_and_alert(event, score, tree, portfolio)
        gap_alerts = [a for a in alerts if "gap" in a.title.lower() or "Monday" in a.title]
        assert len(gap_alerts) > 0

    def test_trading_halt_alert_generated(self, manager):
        score = make_composite(78.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_scenario_tree("evt-halt", include_tail=True)  # 12% halt prob
        event = make_event("evt-halt", is_weekend=True)
        portfolio = make_portfolio_impact("EMERGENCY_DERISKING")

        alerts = manager.evaluate_and_alert(event, score, tree, portfolio)
        halt_alerts = [a for a in alerts if "halt" in a.title.lower()]
        assert len(halt_alerts) > 0

    def test_alert_history_accumulates(self, manager):
        for i in range(3):
            score = make_composite(80.0, SeverityLevel.CRITICAL, "HEDGE")
            tree = make_scenario_tree(f"evt-hist-{i}")
            event = make_event(f"evt-hist-{i}")
            portfolio = make_portfolio_impact("HEDGE")
            manager.evaluate_and_alert(event, score, tree, portfolio)

        history = manager.get_alert_history()
        assert len(history) >= 3

    def test_get_unacknowledged_critical_returns_correct_subset(self, manager):
        score = make_composite(85.0, SeverityLevel.CRITICAL, "EMERGENCY_DERISKING")
        tree = make_scenario_tree("evt-unack")
        event = make_event("evt-unack")
        portfolio = make_portfolio_impact("EMERGENCY_DERISKING", kill_switch=True)

        manager.evaluate_and_alert(event, score, tree, portfolio)
        unacked = manager.get_unacknowledged_critical_alerts()
        assert all(a.level == AlertLevel.CRITICAL for a in unacked)
        assert all(not a.acknowledged for a in unacked)

    def test_alert_has_composite_score(self, manager):
        score = make_composite(77.0, SeverityLevel.CRITICAL, "HEDGE")
        tree = make_scenario_tree("evt-score")
        event = make_event("evt-score")
        portfolio = make_portfolio_impact("HEDGE")

        alerts = manager.evaluate_and_alert(event, score, tree, portfolio)
        scored = [a for a in alerts if a.composite_score is not None]
        assert len(scored) > 0
        assert all(abs(a.composite_score - 77.0) < 1.0 for a in scored)


# ─── HeartbeatMonitor ────────────────────────────────────────

class TestHeartbeatMonitor:

    def test_fresh_heartbeat_passes(self):
        monitor = HeartbeatMonitor(interval_seconds=60)
        monitor.heartbeat()
        assert monitor.check() is True

    def test_stale_heartbeat_fails(self):
        import time
        monitor = HeartbeatMonitor(interval_seconds=1)
        monitor.heartbeat()
        time.sleep(1.1)
        assert monitor.check() is False

    def test_alert_callback_called_on_failure(self):
        import time
        called = []
        monitor = HeartbeatMonitor(interval_seconds=1, alert_fn=lambda msg: called.append(msg))
        monitor.heartbeat()
        time.sleep(1.1)
        monitor.check()
        assert len(called) == 1

    def test_heartbeat_resets_timer(self):
        import time
        monitor = HeartbeatMonitor(interval_seconds=1)
        monitor.heartbeat()
        time.sleep(0.8)
        monitor.heartbeat()   # Reset
        time.sleep(0.8)
        # Should still pass because we reset 0.8s ago
        assert monitor.check() is True


# ─── AuditTrail ──────────────────────────────────────────────

class TestAuditTrail:

    def test_record_event_does_not_raise(self):
        trail = AuditTrail()
        event = make_event("evt-audit")
        trail.record_event(event)  # Should not raise

    def test_record_risk_score_does_not_raise(self):
        trail = AuditTrail()
        score = make_composite(60.0, SeverityLevel.HIGH, "HEDGE")
        trail.record_risk_score(score)  # Should not raise

    def test_audit_log_written_to_file(self, tmp_path):
        trail = AuditTrail(log_dir=str(tmp_path))
        event = make_event("evt-file")
        trail.record_event(event)

        log_files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(log_files) == 1
        content = log_files[0].read_text()
        assert "evt-file" in content
        assert "event_detected" in content

    def test_audit_log_is_valid_jsonl(self, tmp_path):
        import json
        trail = AuditTrail(log_dir=str(tmp_path))
        for i in range(3):
            trail.record_event(make_event(f"evt-{i}"))

        log_file = list(tmp_path.glob("audit_*.jsonl"))[0]
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            parsed = json.loads(line)
            assert "audit_type" in parsed
            assert "timestamp" in parsed
