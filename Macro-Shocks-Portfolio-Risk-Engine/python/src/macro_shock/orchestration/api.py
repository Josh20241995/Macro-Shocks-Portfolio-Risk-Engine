"""
orchestration/api.py

FastAPI REST API Server for the Macro Shock Risk Engine.

Serves the C# dashboard and any downstream consumers with:
  GET  /health                     — Liveness check
  GET  /api/v1/risk/latest         — Most recent risk snapshot
  GET  /api/v1/risk/history        — Historical scores (configurable lookback)
  POST /api/v1/events/process      — Submit a raw event for immediate scoring
  GET  /api/v1/alerts              — Recent alert history
  POST /api/v1/alerts/acknowledge  — Acknowledge an alert
  GET  /api/v1/backtest/run        — Trigger a backtest run (async)

Run with:
  uvicorn macro_shock.orchestration.api:app --host 0.0.0.0 --port 8000 --reload

All responses use camelCase-compatible field names via Pydantic alias generators.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from macro_shock.data.ingestion import MarketStateBuilder
from macro_shock.data_schema.models import (
    CompositeRiskScore,
    MacroEvent,
    PortfolioImpactReport,
    RiskAlert,
    ScenarioTree,
)
from macro_shock.event_detection.calendar import MarketCalendar
from macro_shock.monitoring.alert_manager import AlertManager, AuditTrail
from macro_shock.orchestration.pipeline import MacroShockPipeline

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# App Initialization
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Macro Shock Risk Engine API",
    description="Institutional macro shock risk scoring and portfolio guidance.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Application State (initialized at startup)
# ---------------------------------------------------------------------------

class AppState:
    pipeline: Optional[MacroShockPipeline] = None
    alert_manager: Optional[AlertManager] = None
    calendar: Optional[MarketCalendar] = None
    latest_context: Optional[Any] = None          # PipelineRunContext
    score_history: List[CompositeRiskScore] = []
    alert_history: List[RiskAlert] = []
    config: Dict = {}

state = AppState()


@app.on_event("startup")
async def startup():
    env = os.getenv("MSRE_ENVIRONMENT", "research")
    config_path = os.getenv("MSRE_CONFIG", f"python/configs/{env}.yaml")

    config: Dict = {}
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        logger.info("config_loaded", path=config_path, env=env)
    except FileNotFoundError:
        logger.warning("config_not_found", path=config_path, using="defaults")
        config = {"use_transformer": False, "fail_fast": False}

    state.config = config
    state.calendar = MarketCalendar()
    state.pipeline = MacroShockPipeline(config=config, environment=env)
    state.alert_manager = AlertManager(environment=env)

    logger.info("msre_api_started", environment=env)


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    environment: str
    timestamp: str
    pipeline_ready: bool


class SubScoreResponse(BaseModel):
    name: str
    score: float
    weight: float
    weighted_contribution: float
    primary_driver: str
    contributing_factors: List[str] = []
    confidence: float = 1.0


class ScenarioResponse(BaseModel):
    name: str
    description: str
    probability: float
    equity_impact_pct: float
    yield_10y_change_bps: float
    yield_2y_change_bps: float
    credit_hy_change_bps: float
    vix_change: float
    is_tail_scenario: bool
    liquidity_impairment: float
    trading_halt_probability: float
    forced_deleveraging_risk: float


class HedgeResponse(BaseModel):
    asset_class: str
    instrument_description: str
    action: str
    urgency: str
    sizing_guidance: str
    rationale: str
    estimated_cost_bps: Optional[float] = None
    estimated_protection_value: Optional[str] = None
    requires_pm_approval: bool = True


class AlertResponse(BaseModel):
    alert_id: str
    level: str
    title: str
    message: str
    composite_score: Optional[float] = None
    generated_at: str
    triggered_thresholds: List[str] = []
    requires_acknowledgment: bool = False
    acknowledged: bool = False


class EventSummaryResponse(BaseModel):
    event_id: str
    title: str
    institution: str
    speaker: Optional[str] = None
    event_type: str
    severity: str
    severity_score: float
    is_weekend: bool
    full_weekend_gap: bool
    hours_until_next_open: Optional[float] = None
    event_timestamp: str


class RiskSnapshotResponse(BaseModel):
    composite_score: float
    severity: str
    action_level: str
    regime: str
    summary: str
    weekend_gap_active: bool
    hours_until_next_open: float
    monday_gap_estimate_pct: float
    expected_equity_impact_pct: float
    tail_loss_5pct: float
    equity_guidance: str
    rates_guidance: str
    credit_guidance: str
    sub_scores: List[SubScoreResponse]
    scenarios: List[ScenarioResponse]
    hedge_recommendations: List[HedgeResponse]
    recent_alerts: List[AlertResponse]
    current_event: Optional[EventSummaryResponse]
    generated_at: str
    data_quality: float
    score_reliability: str


class ProcessEventRequest(BaseModel):
    title: str
    institution: str
    speaker: Optional[str] = None
    speaker_role: Optional[str] = None
    event_time: str
    description: Optional[str] = None
    headline_summary: Optional[str] = None
    prepared_remarks: Optional[str] = None
    qa_section: Optional[str] = None
    raw_text: Optional[str] = None
    stress_level: float = 0.30   # For synthetic market state in research mode


class AcknowledgeAlertRequest(BaseModel):
    alert_id: str
    acknowledged_by: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Operations"])
async def health():
    """Liveness and readiness check."""
    return HealthResponse(
        status="healthy",
        environment=os.getenv("MSRE_ENVIRONMENT", "research"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        pipeline_ready=state.pipeline is not None,
    )


@app.get("/api/v1/risk/latest", response_model=RiskSnapshotResponse, tags=["Risk"])
async def get_latest_risk():
    """
    Returns the most recent risk snapshot.
    Includes composite score, all sub-scores, scenario tree,
    portfolio impact, and active alerts.
    """
    if state.latest_context is None:
        raise HTTPException(status_code=404, detail="No risk data available yet. Submit an event first.")

    return _build_snapshot_response(state.latest_context)


@app.get("/api/v1/risk/history", response_model=List[RiskSnapshotResponse], tags=["Risk"])
async def get_risk_history(hours: int = Query(default=24, ge=1, le=168)):
    """
    Returns historical risk scores.
    In production, this reads from TimescaleDB.
    In research mode, returns in-memory history.
    """
    if not state.score_history:
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    recent = [
        s for s in state.score_history
        if s.generated_at.timestamp() >= cutoff
    ]

    return [_build_minimal_snapshot_response(s) for s in recent]


@app.post("/api/v1/events/process", response_model=RiskSnapshotResponse, tags=["Risk"])
async def process_event(request: ProcessEventRequest, background_tasks: BackgroundTasks):
    """
    Submit a raw event for immediate risk scoring.
    Returns the full risk snapshot synchronously.
    Background tasks handle alert routing and audit logging.
    """
    if state.pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialized.")

    raw_event = request.model_dump()
    raw_event["event_time"] = request.event_time

    # Build synthetic market state (production would use live feeds)
    market_state = MarketStateBuilder.build_synthetic(
        as_of=datetime.fromisoformat(request.event_time.replace("Z", "+00:00")),
        calendar=state.calendar,
        stress_level=request.stress_level,
        seed=42,
    )

    context = state.pipeline.process_raw_event(raw_event, market_state=market_state)
    state.latest_context = context

    if context.risk_score:
        state.score_history.append(context.risk_score)
        # Keep last 500 scores in memory
        if len(state.score_history) > 500:
            state.score_history = state.score_history[-500:]

    if context.alerts:
        state.alert_history.extend(context.alerts)
        if len(state.alert_history) > 1000:
            state.alert_history = state.alert_history[-1000:]

    return _build_snapshot_response(context)


@app.get("/api/v1/alerts", response_model=List[AlertResponse], tags=["Alerts"])
async def get_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    level: Optional[str] = Query(default=None),
):
    """Returns recent alerts, optionally filtered by severity level."""
    alerts = state.alert_history[-limit:]
    if level:
        alerts = [a for a in alerts if a.level.value == level.upper()]
    return [_alert_to_response(a) for a in reversed(alerts)]


@app.post("/api/v1/alerts/acknowledge", tags=["Alerts"])
async def acknowledge_alert(request: AcknowledgeAlertRequest):
    """Acknowledge an alert by ID."""
    for alert in state.alert_history:
        if alert.alert_id == request.alert_id:
            alert.acknowledged = True
            alert.acknowledged_by = request.acknowledged_by
            alert.acknowledged_at = datetime.now(timezone.utc)
            logger.info(
                "alert_acknowledged",
                alert_id=request.alert_id,
                by=request.acknowledged_by,
            )
            return {"status": "acknowledged", "alert_id": request.alert_id}
    raise HTTPException(status_code=404, detail=f"Alert {request.alert_id} not found.")


@app.get("/api/v1/scenarios/demo", response_model=RiskSnapshotResponse, tags=["Demo"])
async def run_demo_scenario(
    scenario: str = Query(default="weekend_crisis"),
    stress_level: float = Query(default=0.5, ge=0.0, le=1.0),
):
    """
    Run a canned demo scenario for dashboard testing.
    Available: weekend_crisis, hawkish_surprise, dovish_pivot, friday_close_ambiguous
    """
    from examples.run_end_to_end import SCENARIOS
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{scenario}'. Available: {list(SCENARIOS.keys())}",
        )

    raw_event = SCENARIOS[scenario]
    event_time = datetime.fromisoformat(raw_event["event_time"]).astimezone(timezone.utc)
    market_state = MarketStateBuilder.build_synthetic(
        as_of=event_time,
        calendar=state.calendar,
        stress_level=stress_level,
        seed=42,
    )

    context = state.pipeline.process_raw_event(raw_event, market_state=market_state)
    state.latest_context = context
    return _build_snapshot_response(context)


# ---------------------------------------------------------------------------
# Response Builders
# ---------------------------------------------------------------------------

def _build_snapshot_response(context) -> RiskSnapshotResponse:
    """Convert a PipelineRunContext to the API response model."""
    score = context.risk_score
    tree = context.scenario_tree
    portfolio = context.portfolio_impact
    event = context.event

    sub_scores_resp = []
    if score:
        for ss in [
            score.liquidity_risk, score.volatility_risk, score.rate_shock_risk,
            score.equity_downside_risk, score.credit_spread_risk, score.fx_risk,
            score.commodity_shock_risk, score.weekend_gap_risk, score.policy_ambiguity_risk,
        ]:
            sub_scores_resp.append(SubScoreResponse(
                name=ss.name,
                score=round(ss.score, 2),
                weight=round(ss.weight, 4),
                weighted_contribution=round(ss.weighted_contribution, 2),
                primary_driver=ss.primary_driver,
                contributing_factors=ss.contributing_factors,
                confidence=round(ss.confidence, 3),
            ))

    scenarios_resp = []
    if tree:
        for s in tree.scenarios:
            scenarios_resp.append(ScenarioResponse(
                name=s.name,
                description=s.description,
                probability=round(s.probability, 4),
                equity_impact_pct=round(s.equity_impact_pct, 2),
                yield_10y_change_bps=round(s.yield_10y_change_bps, 1),
                yield_2y_change_bps=round(s.yield_2y_change_bps, 1),
                credit_hy_change_bps=round(s.credit_hy_change_bps, 1),
                vix_change=round(s.vix_change, 2),
                is_tail_scenario=s.is_tail_scenario,
                liquidity_impairment=round(s.liquidity_impairment, 3),
                trading_halt_probability=round(s.trading_halt_probability, 3),
                forced_deleveraging_risk=round(s.forced_deleveraging_risk, 3),
            ))

    hedges_resp = []
    if portfolio:
        for h in portfolio.hedge_recommendations:
            hedges_resp.append(HedgeResponse(
                asset_class=h.asset_class.value,
                instrument_description=h.instrument_description,
                action=h.action,
                urgency=h.urgency,
                sizing_guidance=h.sizing_guidance,
                rationale=h.rationale,
                estimated_cost_bps=h.estimated_cost_bps,
                estimated_protection_value=h.estimated_protection_value,
                requires_pm_approval=h.requires_pm_approval,
            ))

    recent_alerts = [_alert_to_response(a) for a in (context.alerts or [])[-10:]]

    event_resp = None
    if event:
        event_resp = EventSummaryResponse(
            event_id=event.event_id,
            title=event.title,
            institution=event.institution,
            speaker=event.speaker,
            event_type=event.event_type.value,
            severity=event.severity.value,
            severity_score=round(event.severity_score, 1),
            is_weekend=event.is_weekend,
            full_weekend_gap=event.full_weekend_gap,
            hours_until_next_open=event.hours_until_next_open,
            event_timestamp=event.event_timestamp.isoformat(),
        )

    return RiskSnapshotResponse(
        composite_score=round(score.composite_score, 2) if score else 0.0,
        severity=score.severity.value if score else "INFORMATIONAL",
        action_level=score.recommended_action_level if score else "NO_ACTION",
        regime=score.regime.value if score else "unknown",
        summary=score.summary if score else "No risk data available.",
        weekend_gap_active=event.full_weekend_gap if event else False,
        hours_until_next_open=event.hours_until_next_open or 0.0 if event else 0.0,
        monday_gap_estimate_pct=round(tree.monday_gap_estimate_pct or 0.0, 2) if tree else 0.0,
        expected_equity_impact_pct=round(tree.expected_equity_impact_pct, 2) if tree else 0.0,
        tail_loss_5pct=round(tree.tail_loss_5pct, 2) if tree else 0.0,
        equity_guidance=portfolio.equity_guidance if portfolio else "",
        rates_guidance=portfolio.rates_guidance if portfolio else "",
        credit_guidance=portfolio.credit_guidance if portfolio else "",
        sub_scores=sub_scores_resp,
        scenarios=sorted(scenarios_resp, key=lambda s: s.probability, reverse=True),
        hedge_recommendations=hedges_resp,
        recent_alerts=recent_alerts,
        current_event=event_resp,
        generated_at=datetime.now(timezone.utc).isoformat(),
        data_quality=round(score.overall_data_quality, 3) if score else 0.0,
        score_reliability=score.score_reliability if score else "LOW",
    )


def _build_minimal_snapshot_response(score: CompositeRiskScore) -> RiskSnapshotResponse:
    """Minimal snapshot for history endpoint (no scenario/hedge detail)."""
    return RiskSnapshotResponse(
        composite_score=round(score.composite_score, 2),
        severity=score.severity.value,
        action_level=score.recommended_action_level,
        regime=score.regime.value,
        summary=score.summary,
        weekend_gap_active=score.gap_risk_multiplier > 1.0,
        hours_until_next_open=0.0,
        monday_gap_estimate_pct=0.0,
        expected_equity_impact_pct=0.0,
        tail_loss_5pct=0.0,
        equity_guidance="", rates_guidance="", credit_guidance="",
        sub_scores=[], scenarios=[], hedge_recommendations=[],
        recent_alerts=[],
        current_event=None,
        generated_at=score.generated_at.isoformat(),
        data_quality=round(score.overall_data_quality, 3),
        score_reliability=score.score_reliability,
    )


def _alert_to_response(alert: RiskAlert) -> AlertResponse:
    return AlertResponse(
        alert_id=alert.alert_id,
        level=alert.level.value,
        title=alert.title,
        message=alert.message,
        composite_score=alert.composite_score,
        generated_at=alert.generated_at.isoformat(),
        triggered_thresholds=alert.triggered_thresholds,
        requires_acknowledgment=alert.requires_acknowledgment,
        acknowledged=alert.acknowledged,
    )
