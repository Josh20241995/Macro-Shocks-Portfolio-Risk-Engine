"""
monitoring/alert_manager.py

Monitoring, Alerting, and Audit Trail System.

Provides:
- Config-driven threshold alerting (CRITICAL / HIGH / MEDIUM / LOW)
- Structured JSON logging with correlation IDs
- Alert routing to downstream systems (Slack, PagerDuty, OMS)
- Dead-man switch / heartbeat monitoring
- Full audit trail for all risk outputs
- Exception handling and graceful degradation

Design:
- All alerts are append-only (never mutated after emission)
- Alert acknowledgment is tracked separately
- Every risk score, scenario, and portfolio recommendation is logged
  with its full context for post-event audit
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from macro_shock.data_schema.models import (
    AlertLevel,
    CompositeRiskScore,
    MacroEvent,
    PortfolioImpactReport,
    RiskAlert,
    ScenarioTree,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Alert Threshold Configuration
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS = {
    "composite_score": {
        AlertLevel.CRITICAL: 75.0,
        AlertLevel.HIGH: 55.0,
        AlertLevel.MEDIUM: 35.0,
        AlertLevel.LOW: 15.0,
    },
    "weekend_gap_risk_score": {
        AlertLevel.CRITICAL: 70.0,
        AlertLevel.HIGH: 50.0,
        AlertLevel.MEDIUM: 30.0,
    },
    "liquidity_risk_score": {
        AlertLevel.CRITICAL: 75.0,
        AlertLevel.HIGH: 55.0,
    },
    "volatility_risk_score": {
        AlertLevel.CRITICAL: 70.0,
        AlertLevel.HIGH: 50.0,
    },
    "monday_gap_estimate_pct": {
        AlertLevel.CRITICAL: -4.0,    # >4% negative gap
        AlertLevel.HIGH: -2.5,
        AlertLevel.MEDIUM: -1.5,
    },
    "trading_halt_probability": {
        AlertLevel.CRITICAL: 0.10,   # >10% tail halt probability
        AlertLevel.HIGH: 0.05,
    },
}


# ---------------------------------------------------------------------------
# Routing Configuration
# ---------------------------------------------------------------------------

class AlertRouter:
    """
    Routes alerts to configured downstream channels.
    All routing is best-effort — failures are logged but do not block
    the primary monitoring pipeline.
    """

    def __init__(self, config: Dict):
        self._slack_webhook = config.get("slack_webhook_url")
        self._pagerduty_key = config.get("pagerduty_integration_key")
        self._oms_endpoint = config.get("oms_alert_endpoint")
        self._email_recipients = config.get("email_recipients", [])

    def route(self, alert: RiskAlert) -> None:
        targets = alert.routing_targets or []

        for target in targets:
            try:
                if target == "slack" and self._slack_webhook:
                    self._send_slack(alert)
                elif target == "pagerduty" and self._pagerduty_key:
                    self._send_pagerduty(alert)
                elif target == "oms" and self._oms_endpoint:
                    self._send_oms(alert)
                elif target == "log":
                    self._log_alert(alert)
            except Exception as e:
                logger.error(
                    "alert_routing_failed",
                    target=target,
                    alert_id=alert.alert_id,
                    error=str(e),
                )

    def _send_slack(self, alert: RiskAlert) -> None:
        """Send alert to Slack webhook. Requires 'requests' library."""
        try:
            import requests
            color = {
                AlertLevel.CRITICAL: "danger",
                AlertLevel.HIGH: "warning",
                AlertLevel.MEDIUM: "good",
                AlertLevel.LOW: "#36a64f",
            }.get(alert.level, "#cccccc")

            payload = {
                "attachments": [{
                    "color": color,
                    "title": f"[MSRE] {alert.level.value}: {alert.title}",
                    "text": alert.message,
                    "fields": [
                        {"title": "Score", "value": f"{alert.composite_score:.1f}/100" if alert.composite_score else "N/A", "short": True},
                        {"title": "Alert ID", "value": alert.alert_id[:8], "short": True},
                        {"title": "Time", "value": alert.generated_at.isoformat(), "short": True},
                    ],
                    "footer": "Macro Shock Risk Engine",
                }]
            }
            resp = requests.post(self._slack_webhook, json=payload, timeout=5)
            resp.raise_for_status()
            logger.debug("slack_alert_sent", alert_id=alert.alert_id)
        except ImportError:
            logger.warning("requests_not_available_for_slack")

    def _send_pagerduty(self, alert: RiskAlert) -> None:
        """Send high/critical alerts to PagerDuty."""
        if alert.level not in (AlertLevel.CRITICAL, AlertLevel.HIGH):
            return
        try:
            import requests
            payload = {
                "routing_key": self._pagerduty_key,
                "event_action": "trigger",
                "payload": {
                    "summary": f"[MSRE] {alert.level.value}: {alert.title}",
                    "severity": "critical" if alert.level == AlertLevel.CRITICAL else "warning",
                    "source": "macro-shock-risk-engine",
                    "custom_details": {
                        "composite_score": alert.composite_score,
                        "message": alert.message,
                        "alert_id": alert.alert_id,
                    },
                },
            }
            resp = requests.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
                timeout=5,
            )
            resp.raise_for_status()
            logger.info("pagerduty_alert_sent", alert_id=alert.alert_id)
        except ImportError:
            logger.warning("requests_not_available_for_pagerduty")

    def _send_oms(self, alert: RiskAlert) -> None:
        """Stub: send alert event to OMS for downstream processing."""
        logger.info(
            "oms_alert_dispatched",
            alert_id=alert.alert_id,
            level=alert.level.value,
            endpoint=self._oms_endpoint,
        )

    def _log_alert(self, alert: RiskAlert) -> None:
        logger.warning(
            "risk_alert",
            level=alert.level.value,
            title=alert.title,
            message=alert.message,
            score=alert.composite_score,
            alert_id=alert.alert_id,
        )


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------

class AuditTrail:
    """
    Append-only audit log for all risk engine outputs.
    Written to both structured log and an optional file-based JSON log.
    Used for regulatory compliance, post-event analysis, and model governance.
    """

    def __init__(self, log_dir: Optional[str] = None):
        self._log_dir = Path(log_dir) if log_dir else None
        if self._log_dir:
            self._log_dir.mkdir(parents=True, exist_ok=True)

    def record_event(self, event: MacroEvent) -> None:
        entry = {
            "audit_type": "event_detected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "severity": event.severity.value,
            "severity_score": event.severity_score,
            "institution": event.institution,
            "speaker": event.speaker,
            "is_weekend": event.is_weekend,
            "full_weekend_gap": event.full_weekend_gap,
            "hours_until_next_open": event.hours_until_next_open,
        }
        self._write(entry)

    def record_risk_score(self, score: CompositeRiskScore) -> None:
        entry = {
            "audit_type": "risk_score_generated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score_id": score.score_id,
            "event_id": score.event_id,
            "composite_score": score.composite_score,
            "severity": score.severity.value,
            "regime": score.regime.value,
            "regime_multiplier": score.regime_multiplier,
            "gap_risk_multiplier": score.gap_risk_multiplier,
            "action_level": score.recommended_action_level,
            "data_quality": score.overall_data_quality,
            "reliability": score.score_reliability,
            "sub_scores": {
                "liquidity": score.liquidity_risk.score,
                "volatility": score.volatility_risk.score,
                "rate_shock": score.rate_shock_risk.score,
                "equity_downside": score.equity_downside_risk.score,
                "credit_spread": score.credit_spread_risk.score,
                "fx": score.fx_risk.score,
                "commodity": score.commodity_shock_risk.score,
                "weekend_gap": score.weekend_gap_risk.score,
                "policy_ambiguity": score.policy_ambiguity_risk.score,
            },
        }
        self._write(entry)

    def record_scenario_tree(self, tree: ScenarioTree) -> None:
        entry = {
            "audit_type": "scenario_tree_generated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tree_id": tree.tree_id,
            "event_id": tree.event_id,
            "regime": tree.regime.value,
            "n_scenarios": len(tree.scenarios),
            "expected_equity_impact_pct": tree.expected_equity_impact_pct,
            "expected_yield_change_bps": tree.expected_yield_change_bps,
            "tail_loss_5pct": tree.tail_loss_5pct,
            "tail_loss_1pct": tree.tail_loss_1pct,
            "monday_gap_estimate_pct": tree.monday_gap_estimate_pct,
            "scenarios": [
                {
                    "name": s.name,
                    "probability": round(s.probability, 4),
                    "equity_impact_pct": s.equity_impact_pct,
                    "is_tail": s.is_tail_scenario,
                    "trading_halt_prob": s.trading_halt_probability,
                }
                for s in tree.scenarios
            ],
        }
        self._write(entry)

    def record_portfolio_impact(self, report: PortfolioImpactReport) -> None:
        entry = {
            "audit_type": "portfolio_impact_generated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "report_id": report.report_id,
            "event_id": report.event_id,
            "score_id": report.score_id,
            "action_level": report.action_level,
            "alert_level": report.alert_level.value,
            "gross_exposure_change": report.recommended_gross_exposure_change,
            "leverage_change": report.recommended_leverage_change,
            "trigger_kill_switch": report.trigger_kill_switch,
            "n_hedge_recommendations": len(report.hedge_recommendations),
            "requires_immediate_review": report.requires_immediate_review,
        }
        self._write(entry)

    def record_alert(self, alert: RiskAlert) -> None:
        entry = {
            "audit_type": "alert_emitted",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert_id": alert.alert_id,
            "level": alert.level.value,
            "title": alert.title,
            "composite_score": alert.composite_score,
            "triggered_thresholds": alert.triggered_thresholds,
            "routing_targets": alert.routing_targets,
        }
        self._write(entry)

    def _write(self, entry: Dict) -> None:
        logger.info("audit_record", **{k: v for k, v in entry.items() if k != "scenarios"})
        if self._log_dir:
            log_file = self._log_dir / f"audit_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Alert Manager (Main Interface)
# ---------------------------------------------------------------------------

class AlertManager:
    """
    Primary monitoring and alerting interface.

    Evaluates thresholds, emits structured alerts, routes to downstream
    channels, and writes to the audit trail.
    """

    def __init__(
        self,
        router: Optional[AlertRouter] = None,
        audit_trail: Optional[AuditTrail] = None,
        thresholds: Optional[Dict] = None,
        default_routing: Optional[List[str]] = None,
        environment: str = "research",
    ):
        self.router = router
        self.audit = audit_trail or AuditTrail()
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        self.default_routing = default_routing or ["log"]
        self.environment = environment
        self._alert_history: List[RiskAlert] = []

    def evaluate_and_alert(
        self,
        event: MacroEvent,
        risk_score: CompositeRiskScore,
        scenario_tree: ScenarioTree,
        portfolio_report: PortfolioImpactReport,
    ) -> List[RiskAlert]:
        """
        Evaluate all threshold conditions and emit appropriate alerts.
        Returns list of emitted alerts.
        """
        alerts: List[RiskAlert] = []

        # 1. Composite score alert
        score_alert = self._check_composite_score(risk_score, event)
        if score_alert:
            alerts.append(score_alert)

        # 2. Sub-score specific alerts
        subscore_alerts = self._check_sub_scores(risk_score, event)
        alerts.extend(subscore_alerts)

        # 3. Scenario tree alerts
        scenario_alerts = self._check_scenario_tree(scenario_tree, event, risk_score)
        alerts.extend(scenario_alerts)

        # 4. Portfolio action alert
        action_alert = self._check_portfolio_action(portfolio_report, event, risk_score)
        if action_alert:
            alerts.append(action_alert)

        # 5. Kill switch alert
        if portfolio_report.trigger_kill_switch:
            ks_alert = self._build_kill_switch_alert(event, risk_score)
            alerts.append(ks_alert)

        # Emit and route all alerts
        for alert in alerts:
            self._emit(alert)

        return alerts

    def _check_composite_score(
        self, score: CompositeRiskScore, event: MacroEvent
    ) -> Optional[RiskAlert]:
        thresholds = self.thresholds.get("composite_score", {})
        composite = score.composite_score

        triggered_level = None
        for level in [AlertLevel.CRITICAL, AlertLevel.HIGH, AlertLevel.MEDIUM, AlertLevel.LOW]:
            if level in thresholds and composite >= thresholds[level]:
                triggered_level = level
                break

        if triggered_level is None:
            return None

        routing = self._determine_routing(triggered_level)

        return RiskAlert(
            event_id=event.event_id,
            score_id=score.score_id,
            level=triggered_level,
            title=f"Macro Shock Risk Score: {composite:.1f}/100",
            message=(
                f"Event: {event.title} ({event.institution}). "
                f"Composite Risk Score: {composite:.1f}/100 [{score.severity.value}]. "
                f"Regime: {score.regime.value}. "
                f"Recommended action: {score.recommended_action_level}. "
                f"{score.summary}"
            ),
            composite_score=composite,
            triggered_thresholds=[f"composite_score >= {thresholds[triggered_level]:.0f}"],
            routing_targets=routing,
        )

    def _check_sub_scores(
        self, score: CompositeRiskScore, event: MacroEvent
    ) -> List[RiskAlert]:
        alerts = []
        checks = [
            ("weekend_gap_risk_score", score.weekend_gap_risk.score, "Weekend Gap Risk"),
            ("liquidity_risk_score", score.liquidity_risk.score, "Liquidity Risk"),
            ("volatility_risk_score", score.volatility_risk.score, "Volatility Risk"),
        ]

        for key, value, name in checks:
            thresholds = self.thresholds.get(key, {})
            for level in [AlertLevel.CRITICAL, AlertLevel.HIGH, AlertLevel.MEDIUM]:
                if level in thresholds and value >= thresholds[level]:
                    if not self._already_alerted_at_level(event.event_id, level, key):
                        alerts.append(RiskAlert(
                            event_id=event.event_id,
                            score_id=score.score_id,
                            level=level,
                            title=f"{name} Alert: {value:.1f}/100",
                            message=(
                                f"{name} sub-score reached {value:.1f}/100. "
                                f"Primary driver: {self._get_sub_score_driver(score, key)}."
                            ),
                            composite_score=score.composite_score,
                            triggered_thresholds=[f"{key} >= {thresholds[level]:.0f}"],
                            routing_targets=self._determine_routing(level),
                        ))
                    break

        return alerts

    def _check_scenario_tree(
        self,
        tree: ScenarioTree,
        event: MacroEvent,
        score: CompositeRiskScore,
    ) -> List[RiskAlert]:
        alerts = []
        thresholds = self.thresholds.get("monday_gap_estimate_pct", {})

        if tree.monday_gap_estimate_pct is not None:
            gap = tree.monday_gap_estimate_pct
            for level in [AlertLevel.CRITICAL, AlertLevel.HIGH, AlertLevel.MEDIUM]:
                if level in thresholds and gap <= thresholds[level]:
                    alerts.append(RiskAlert(
                        event_id=event.event_id,
                        score_id=score.score_id,
                        level=level,
                        title=f"Monday Gap Risk: {gap:.1f}% estimated",
                        message=(
                            f"Weekend gap corridor active. "
                            f"Estimated Monday gap: {gap:.1f}% "
                            f"(confidence: {tree.monday_gap_confidence:.0%}). "
                            f"Next market open: {event.hours_until_next_open:.1f}h. "
                            f"Pre-position risk management recommended before Monday open."
                        ),
                        composite_score=score.composite_score,
                        triggered_thresholds=[f"monday_gap <= {thresholds[level]:.1f}%"],
                        routing_targets=self._determine_routing(level),
                    ))
                    break

        # Trading halt probability alert
        halt_thresholds = self.thresholds.get("trading_halt_probability", {})
        max_halt_prob = max(
            (s.trading_halt_probability for s in tree.scenarios if s.is_tail_scenario),
            default=0.0,
        )
        for level in [AlertLevel.CRITICAL, AlertLevel.HIGH]:
            if level in halt_thresholds and max_halt_prob >= halt_thresholds[level]:
                alerts.append(RiskAlert(
                    event_id=event.event_id,
                    score_id=score.score_id,
                    level=level,
                    title=f"Trading Halt Risk: {max_halt_prob:.0%} probability in tail scenario",
                    message=(
                        f"Tail scenarios include {max_halt_prob:.0%} probability of trading halt. "
                        f"Ensure liquidity in non-equity instruments for Monday hedging. "
                        f"Pre-position in futures and FX which remain tradeable during equity halts."
                    ),
                    composite_score=score.composite_score,
                    triggered_thresholds=[f"trading_halt_prob >= {halt_thresholds[level]:.0%}"],
                    routing_targets=self._determine_routing(level),
                    requires_acknowledgment=True,
                ))
                break

        return alerts

    def _check_portfolio_action(
        self,
        report: PortfolioImpactReport,
        event: MacroEvent,
        score: CompositeRiskScore,
    ) -> Optional[RiskAlert]:
        if report.action_level in ("NO_ACTION", "MONITOR"):
            return None

        level_map = {
            "EMERGENCY_DERISKING": AlertLevel.CRITICAL,
            "HEDGE": AlertLevel.HIGH,
            "REDUCE": AlertLevel.MEDIUM,
        }
        level = level_map.get(report.action_level, AlertLevel.LOW)

        return RiskAlert(
            event_id=event.event_id,
            score_id=score.score_id,
            level=level,
            title=f"Portfolio Action Required: {report.action_level}",
            message=(
                f"Risk engine recommends: {report.action_level}. "
                f"Gross exposure change: {report.recommended_gross_exposure_change:.0%}" if report.recommended_gross_exposure_change else ""
                f"{report.notes}. "
                f"REQUIRES PM/RISK OFFICER AUTHORIZATION."
            ),
            composite_score=score.composite_score,
            triggered_thresholds=[f"action_level={report.action_level}"],
            routing_targets=self._determine_routing(level),
            requires_acknowledgment=True,
        )

    def _build_kill_switch_alert(
        self, event: MacroEvent, score: CompositeRiskScore
    ) -> RiskAlert:
        return RiskAlert(
            event_id=event.event_id,
            score_id=score.score_id,
            level=AlertLevel.CRITICAL,
            title="KILL SWITCH CONSIDERATION TRIGGERED",
            message=(
                f"Composite risk score {score.composite_score:.1f}/100 exceeds kill switch threshold. "
                f"Risk engine recommends emergency de-risking review. "
                f"IMMEDIATE PM AND RISK OFFICER REVIEW REQUIRED. "
                f"All actions require explicit human authorization."
            ),
            composite_score=score.composite_score,
            triggered_thresholds=["kill_switch_threshold"],
            routing_targets=["slack", "pagerduty", "oms", "log"],
            requires_acknowledgment=True,
        )

    def _emit(self, alert: RiskAlert) -> None:
        self._alert_history.append(alert)
        self.audit.record_alert(alert)
        if self.router:
            self.router.route(alert)
        else:
            logger.warning(
                "risk_alert_emitted",
                level=alert.level.value,
                title=alert.title,
                score=alert.composite_score,
                alert_id=alert.alert_id,
            )

    def _determine_routing(self, level: AlertLevel) -> List[str]:
        if self.environment == "production":
            if level == AlertLevel.CRITICAL:
                return ["slack", "pagerduty", "oms", "log"]
            elif level == AlertLevel.HIGH:
                return ["slack", "oms", "log"]
            return ["log"]
        return ["log"]  # Non-production: log only

    def _already_alerted_at_level(
        self, event_id: str, level: AlertLevel, threshold_key: str
    ) -> bool:
        return any(
            a.event_id == event_id
            and a.level == level
            and threshold_key in " ".join(a.triggered_thresholds)
            for a in self._alert_history
        )

    def _get_sub_score_driver(self, score: CompositeRiskScore, key: str) -> str:
        mapping = {
            "weekend_gap_risk_score": score.weekend_gap_risk.primary_driver,
            "liquidity_risk_score": score.liquidity_risk.primary_driver,
            "volatility_risk_score": score.volatility_risk.primary_driver,
        }
        return mapping.get(key, "See sub-score detail")

    def get_alert_history(self) -> List[RiskAlert]:
        return list(self._alert_history)

    def get_unacknowledged_critical_alerts(self) -> List[RiskAlert]:
        return [
            a for a in self._alert_history
            if a.level == AlertLevel.CRITICAL
            and a.requires_acknowledgment
            and not a.acknowledged
        ]


# ---------------------------------------------------------------------------
# Heartbeat Monitor
# ---------------------------------------------------------------------------

class HeartbeatMonitor:
    """
    Dead-man switch: alerts if the pipeline fails to emit a heartbeat
    within the configured interval. Used to detect silent pipeline failures.
    """

    def __init__(self, interval_seconds: int = 300, alert_fn: Optional[Callable] = None):
        self.interval = interval_seconds
        self.alert_fn = alert_fn
        self._last_heartbeat: float = time.monotonic()

    def heartbeat(self) -> None:
        self._last_heartbeat = time.monotonic()

    def check(self) -> bool:
        elapsed = time.monotonic() - self._last_heartbeat
        if elapsed > self.interval:
            msg = f"Pipeline heartbeat missed: {elapsed:.0f}s since last beat (threshold: {self.interval}s)"
            logger.error("heartbeat_missed", elapsed_seconds=elapsed)
            if self.alert_fn:
                self.alert_fn(msg)
            return False
        return True
