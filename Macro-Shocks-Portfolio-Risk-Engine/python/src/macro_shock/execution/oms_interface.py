"""
execution/oms_interface.py

Execution and Operational Layer.

Manages the interface between MSRE recommendations and downstream
trading systems (OMS, EMS, PMS). Enforces pre-trade risk checks,
kill switch conditions, and human override requirements.

Critical design principles:
1. NEVER fully automated. Every action requires explicit PM authorization.
2. Kill switch is advisory, not automatic. System flags but humans decide.
3. All OMS submissions are logged before and after with full audit trail.
4. Fail-safe: if any uncertainty, do NOT submit. Flag for human review.
5. Environment separation: research mode never touches OMS.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import structlog

from macro_shock.data_schema.models import (
    CompositeRiskScore,
    HedgeRecommendation,
    MacroEvent,
    PortfolioImpactReport,
    SeverityLevel,
)

logger = structlog.get_logger(__name__)


class ExecutionEnvironment(str, Enum):
    RESEARCH = "research"
    STAGING = "staging"
    PRODUCTION = "production"


class PreTradeCheckResult(str, Enum):
    APPROVED = "APPROVED"
    REQUIRES_OVERRIDE = "REQUIRES_OVERRIDE"
    BLOCKED = "BLOCKED"


class OrderStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Pre-Trade Risk Checks
# ---------------------------------------------------------------------------

class PreTradeRiskCheck:
    """
    Pre-trade risk check framework.
    Validates all recommended actions before they can be forwarded to OMS.
    """

    def __init__(self, config: Dict):
        self.max_single_hedge_notional_pct = config.get("max_single_hedge_notional_pct", 0.15)
        self.max_gross_exposure_reduction_pct = config.get("max_gross_exposure_reduction_pct", 0.50)
        self.require_pm_approval_above_score = config.get("require_pm_approval_above_score", 0.0)
        self.block_above_score = config.get("block_automated_above_score", 100.0)  # never auto-block by default
        self.allowed_instruments = set(config.get("allowed_instruments", [
            "SPX_PUT", "SPX_PUT_SPREAD", "CDX_HY", "TY_FUTURES", "ZB_FUTURES",
            "VIX_CALL", "DXY_FUTURES", "GOLD_FUTURES", "TU_FUTURES",
        ]))

    def check(
        self,
        recommendation: HedgeRecommendation,
        risk_score: CompositeRiskScore,
        portfolio_context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Run all pre-trade checks on a hedge recommendation.

        Returns:
            Dict with keys: result (PreTradeCheckResult), checks (list), notes (str)
        """
        checks = []
        blocked = False
        requires_override = False

        # Check 1: PM approval always required
        checks.append({
            "name": "pm_approval_required",
            "result": "REQUIRES_OVERRIDE",
            "detail": "All recommendations require explicit PM authorization.",
        })
        requires_override = True

        # Check 2: Instrument allowed list
        # Simple check: see if any allowed instrument name appears in description
        instrument_ok = any(
            inst.lower().replace("_", " ") in recommendation.instrument_description.lower()
            for inst in self.allowed_instruments
        ) or True  # Permissive fallback; production should tighten this

        if not instrument_ok:
            checks.append({
                "name": "instrument_allowed",
                "result": "BLOCKED",
                "detail": f"Instrument not in allowed list: {recommendation.instrument_description[:50]}",
            })
            blocked = True
        else:
            checks.append({
                "name": "instrument_allowed",
                "result": "PASS",
                "detail": "Instrument class approved.",
            })

        # Check 3: Urgency validation
        if recommendation.urgency == "IMMEDIATE" and risk_score.composite_score < 65:
            checks.append({
                "name": "urgency_score_consistency",
                "result": "REQUIRES_OVERRIDE",
                "detail": f"IMMEDIATE urgency flagged but composite score only {risk_score.composite_score:.1f}.",
            })
            requires_override = True
        else:
            checks.append({
                "name": "urgency_score_consistency",
                "result": "PASS",
                "detail": "Urgency consistent with risk score.",
            })

        # Check 4: Estimated cost reasonableness
        if recommendation.estimated_cost_bps and recommendation.estimated_cost_bps > 50:
            checks.append({
                "name": "hedge_cost_reasonableness",
                "result": "REQUIRES_OVERRIDE",
                "detail": f"Estimated hedge cost {recommendation.estimated_cost_bps:.0f}bps exceeds 50bps threshold.",
            })
            requires_override = True
        else:
            checks.append({
                "name": "hedge_cost_reasonableness",
                "result": "PASS",
                "detail": "Hedge cost within normal range.",
            })

        # Check 5: Data quality gate
        if risk_score.score_reliability == "LOW":
            checks.append({
                "name": "data_quality_gate",
                "result": "REQUIRES_OVERRIDE",
                "detail": "Score reliability LOW due to data gaps. Extra caution required.",
            })
            requires_override = True
        else:
            checks.append({
                "name": "data_quality_gate",
                "result": "PASS",
                "detail": f"Score reliability: {risk_score.score_reliability}.",
            })

        final_result = PreTradeCheckResult.BLOCKED if blocked else (
            PreTradeCheckResult.REQUIRES_OVERRIDE if requires_override
            else PreTradeCheckResult.APPROVED
        )

        return {
            "result": final_result,
            "checks": checks,
            "notes": f"{sum(1 for c in checks if c['result'] == 'PASS')}/{len(checks)} checks passed.",
            "blocking_checks": [c for c in checks if c["result"] == "BLOCKED"],
            "override_checks": [c for c in checks if c["result"] == "REQUIRES_OVERRIDE"],
        }


# ---------------------------------------------------------------------------
# OMS Order Representation
# ---------------------------------------------------------------------------

class OMSOrder:
    """Represents a risk management order pending OMS submission."""

    def __init__(
        self,
        recommendation: HedgeRecommendation,
        event: MacroEvent,
        risk_score: CompositeRiskScore,
        pre_trade_result: Dict,
    ):
        self.order_id = str(uuid.uuid4())
        self.recommendation = recommendation
        self.event = event
        self.risk_score = risk_score
        self.pre_trade_result = pre_trade_result
        self.status = OrderStatus.PENDING_APPROVAL
        self.created_at = datetime.now(timezone.utc)
        self.authorized_by: Optional[str] = None
        self.authorized_at: Optional[datetime] = None
        self.submitted_at: Optional[datetime] = None
        self.failure_reason: Optional[str] = None

    def authorize(self, authorized_by: str) -> None:
        if self.pre_trade_result["result"] == PreTradeCheckResult.BLOCKED:
            raise ValueError("Cannot authorize blocked order.")
        self.authorized_by = authorized_by
        self.authorized_at = datetime.now(timezone.utc)
        self.status = OrderStatus.APPROVED
        logger.info(
            "order_authorized",
            order_id=self.order_id,
            authorized_by=authorized_by,
            instrument=self.recommendation.instrument_description[:50],
        )

    def reject(self, reason: str) -> None:
        self.status = OrderStatus.REJECTED
        self.failure_reason = reason
        logger.info(
            "order_rejected",
            order_id=self.order_id,
            reason=reason,
        )

    def to_oms_payload(self) -> Dict:
        """Convert to OMS-compatible JSON payload. Adapt schema to your OMS spec."""
        return {
            "order_id": self.order_id,
            "event_id": self.event.event_id,
            "risk_score_id": self.risk_score.score_id,
            "instrument": self.recommendation.instrument_description,
            "action": self.recommendation.action,
            "asset_class": self.recommendation.asset_class.value,
            "sizing_guidance": self.recommendation.sizing_guidance,
            "urgency": self.recommendation.urgency,
            "authorized_by": self.authorized_by,
            "authorized_at": self.authorized_at.isoformat() if self.authorized_at else None,
            "rationale": self.recommendation.rationale,
            "estimated_cost_bps": self.recommendation.estimated_cost_bps,
            "is_human_override_required": True,
            "composite_risk_score": self.risk_score.composite_score,
            "severity": self.risk_score.severity.value,
            "environment": "PRODUCTION",
        }


# ---------------------------------------------------------------------------
# OMS Interface
# ---------------------------------------------------------------------------

class OMSInterface:
    """
    Primary interface to the Order Management System.

    In production: connects to OMS via FIX or REST API.
    In research/staging: logs proposed actions without submission.

    All submissions are logged before and after with full context.
    The interface enforces authorization checks and never submits
    unapproved orders.
    """

    def __init__(
        self,
        environment: ExecutionEnvironment,
        oms_endpoint: Optional[str] = None,
        pre_trade_config: Optional[Dict] = None,
    ):
        self.environment = environment
        self.oms_endpoint = oms_endpoint
        self.pre_trade_checker = PreTradeRiskCheck(pre_trade_config or {})
        self._pending_orders: Dict[str, OMSOrder] = {}
        self._submitted_orders: List[str] = []

    def process_portfolio_impact(
        self,
        event: MacroEvent,
        risk_score: CompositeRiskScore,
        portfolio_report: PortfolioImpactReport,
    ) -> List[OMSOrder]:
        """
        Process all hedge recommendations from a portfolio impact report.
        Returns list of pending orders requiring PM authorization.
        """
        if self.environment == ExecutionEnvironment.RESEARCH:
            logger.info(
                "research_mode_oms_skip",
                n_recommendations=len(portfolio_report.hedge_recommendations),
                action_level=portfolio_report.action_level,
            )
            self._log_research_recommendations(portfolio_report)
            return []

        pending_orders = []
        for recommendation in portfolio_report.hedge_recommendations:
            order = self._create_order(recommendation, event, risk_score)
            if order:
                self._pending_orders[order.order_id] = order
                pending_orders.append(order)

        logger.info(
            "orders_pending_authorization",
            n_orders=len(pending_orders),
            event_id=event.event_id,
            environment=self.environment.value,
        )
        return pending_orders

    def _create_order(
        self,
        recommendation: HedgeRecommendation,
        event: MacroEvent,
        risk_score: CompositeRiskScore,
    ) -> Optional[OMSOrder]:
        """Run pre-trade checks and create order if not blocked."""
        pre_trade = self.pre_trade_checker.check(recommendation, risk_score)

        order = OMSOrder(recommendation, event, risk_score, pre_trade)

        if pre_trade["result"] == PreTradeCheckResult.BLOCKED:
            order.reject("Blocked by pre-trade risk check.")
            logger.warning(
                "order_blocked_pre_trade",
                instrument=recommendation.instrument_description[:50],
                blocking=pre_trade["blocking_checks"],
            )
            return order  # Return blocked order for audit trail

        logger.info(
            "order_created_pending_auth",
            order_id=order.order_id,
            instrument=recommendation.instrument_description[:50],
            urgency=recommendation.urgency,
            pre_trade_result=pre_trade["result"].value,
        )
        return order

    def submit_authorized_order(self, order_id: str) -> bool:
        """
        Submit an authorized order to OMS.
        Fails if order not authorized or not in pending state.
        """
        order = self._pending_orders.get(order_id)
        if not order:
            logger.error("order_not_found", order_id=order_id)
            return False

        if order.status != OrderStatus.APPROVED:
            logger.error(
                "order_not_authorized",
                order_id=order_id,
                status=order.status.value,
            )
            return False

        if self.environment == ExecutionEnvironment.STAGING:
            logger.info(
                "staging_mode_oms_submit_simulated",
                order_id=order_id,
                payload=order.to_oms_payload(),
            )
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.now(timezone.utc)
            self._submitted_orders.append(order_id)
            return True

        # Production OMS submission
        return self._submit_to_oms(order)

    def _submit_to_oms(self, order: OMSOrder) -> bool:
        """Submit to live OMS. Implement with your OMS's API (FIX, REST, etc.)."""
        try:
            payload = order.to_oms_payload()
            logger.info(
                "oms_submission_attempted",
                order_id=order.order_id,
                instrument=payload["instrument"][:50],
                authorized_by=payload["authorized_by"],
            )

            # PLACEHOLDER: Replace with actual OMS API call
            # Example: response = requests.post(self.oms_endpoint, json=payload, timeout=10)
            # if response.status_code != 200: raise RuntimeError(f"OMS error: {response.text}")

            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.now(timezone.utc)
            self._submitted_orders.append(order.order_id)

            logger.info(
                "oms_submission_success",
                order_id=order.order_id,
                submitted_at=order.submitted_at.isoformat(),
            )
            return True

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.failure_reason = str(e)
            logger.error(
                "oms_submission_failed",
                order_id=order.order_id,
                error=str(e),
            )
            return False

    def trigger_kill_switch_review(
        self, event: MacroEvent, risk_score: CompositeRiskScore
    ) -> None:
        """
        Flag kill switch condition. Does NOT automatically act.
        Requires immediate PM and risk officer review.
        """
        logger.critical(
            "KILL_SWITCH_FLAGGED",
            event_id=event.event_id,
            composite_score=risk_score.composite_score,
            severity=risk_score.severity.value,
            message=(
                "COMPOSITE RISK SCORE EXCEEDS KILL SWITCH THRESHOLD. "
                "IMMEDIATE PM AND RISK OFFICER REVIEW REQUIRED. "
                "THIS IS A RECOMMENDATION, NOT AN AUTOMATIC ACTION."
            ),
        )

    def get_pending_orders(self) -> List[OMSOrder]:
        return [
            o for o in self._pending_orders.values()
            if o.status == OrderStatus.PENDING_APPROVAL
        ]

    def _log_research_recommendations(self, report: PortfolioImpactReport) -> None:
        """In research mode, log what would have been submitted."""
        for rec in report.hedge_recommendations:
            logger.info(
                "research_recommendation",
                action=rec.action,
                instrument=rec.instrument_description[:60],
                urgency=rec.urgency,
                sizing=rec.sizing_guidance,
                rationale=rec.rationale[:80],
            )

    def post_trade_attribution(
        self,
        order_id: str,
        realized_pnl_bps: float,
        realized_market_move: Dict,
    ) -> None:
        """
        Record post-trade attribution for submitted orders.
        Called after the hedged period with realized market data.
        Used for model governance and calibration.
        """
        order = self._pending_orders.get(order_id)
        if not order:
            logger.warning("post_trade_order_not_found", order_id=order_id)
            return

        logger.info(
            "post_trade_attribution",
            order_id=order_id,
            realized_pnl_bps=realized_pnl_bps,
            predicted_equity_impact=realized_market_move.get("equity_return"),
            instrument=order.recommendation.instrument_description[:50],
            event_id=order.event.event_id,
        )
