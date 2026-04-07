"""
data_schema/models.py

Canonical Pydantic data models for the Macro Shock Risk Engine.
All inter-module data exchange uses these types.
Never use raw dicts across module boundaries.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    SCHEDULED_POST_CLOSE = "scheduled_post_close"
    UNSCHEDULED_EMERGENCY = "unscheduled_emergency"
    WEEKEND_POLICY_ACTION = "weekend_policy_action"
    GEOPOLITICAL_SURPRISE = "geopolitical_surprise"
    INTERMEETING_RATE_ACTION = "intermeeting_rate_action"
    FINANCIAL_STABILITY_STATEMENT = "financial_stability_statement"
    CONGRESSIONAL_TESTIMONY = "congressional_testimony"
    PRESS_CONFERENCE = "press_conference"
    UNKNOWN = "unknown"


class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class MarketSessionState(str, Enum):
    OPEN = "open"
    CLOSED_INTRADAY = "closed_intraday"   # normal close, same day
    CLOSED_OVERNIGHT = "closed_overnight"  # overnight gap
    CLOSED_WEEKEND = "closed_weekend"      # Friday close -> Monday open
    CLOSED_HOLIDAY = "closed_holiday"
    PRE_MARKET = "pre_market"
    AFTER_HOURS = "after_hours"


class RegimeType(str, Enum):
    RISK_ON_EXPANSION = "risk_on_expansion"
    FRAGILE_RISK_ON = "fragile_risk_on"
    RISK_OFF_CORRECTION = "risk_off_correction"
    CRISIS = "crisis"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


class AssetClass(str, Enum):
    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    RATES = "rates"
    FX = "fx"
    COMMODITIES = "commodities"
    CREDIT = "credit"
    VOLATILITY = "volatility"
    CRYPTO = "crypto"


class PolicyStance(str, Enum):
    VERY_HAWKISH = "very_hawkish"
    HAWKISH = "hawkish"
    NEUTRAL = "neutral"
    DOVISH = "dovish"
    VERY_DOVISH = "very_dovish"
    CRISIS_EASING = "crisis_easing"
    AMBIGUOUS = "ambiguous"


class AlertLevel(str, Enum):
    CRITICAL = "CRITICAL"    # Immediate action required
    HIGH = "HIGH"            # Urgent review required
    MEDIUM = "MEDIUM"        # Monitor closely
    LOW = "LOW"              # Informational


# ---------------------------------------------------------------------------
# Market State Models
# ---------------------------------------------------------------------------

class YieldCurveSnapshot(BaseModel):
    timestamp: datetime
    y2: Optional[float] = None     # 2-year yield
    y5: Optional[float] = None     # 5-year yield
    y10: Optional[float] = None    # 10-year yield
    y30: Optional[float] = None    # 30-year yield
    slope_2_10: Optional[float] = None   # 10y - 2y spread (bps)
    slope_2_30: Optional[float] = None   # 30y - 2y spread (bps)
    slope_5_30: Optional[float] = None   # 30y - 5y spread (bps)
    real_yield_10: Optional[float] = None  # 10y TIPS yield
    breakeven_10: Optional[float] = None   # 10y breakeven inflation
    data_quality: float = Field(default=1.0, ge=0.0, le=1.0)
    stale: bool = False

    @model_validator(mode="after")
    def compute_slopes(self) -> "YieldCurveSnapshot":
        if self.y10 is not None and self.y2 is not None:
            self.slope_2_10 = (self.y10 - self.y2) * 100
        if self.y30 is not None and self.y2 is not None:
            self.slope_2_30 = (self.y30 - self.y2) * 100
        if self.y30 is not None and self.y5 is not None:
            self.slope_5_30 = (self.y30 - self.y5) * 100
        return self


class VolatilitySnapshot(BaseModel):
    timestamp: datetime
    vix_spot: Optional[float] = None        # VIX index level
    vix_1m: Optional[float] = None          # 1-month implied vol
    vix_3m: Optional[float] = None          # 3-month implied vol
    vix_term_structure_slope: Optional[float] = None  # 3m - 1m
    realized_vol_1m: Optional[float] = None  # 1-month realized vol SPX
    vol_risk_premium: Optional[float] = None  # implied - realized
    skew_25d: Optional[float] = None         # 25-delta put-call skew
    put_call_ratio: Optional[float] = None
    vvix: Optional[float] = None             # vol of vol
    move_index: Optional[float] = None       # rates vol index
    stale: bool = False


class LiquiditySnapshot(BaseModel):
    timestamp: datetime
    bid_ask_spread_spx_bps: Optional[float] = None
    market_depth_proxy: Optional[float] = None    # normalized 0-1
    funding_spread_libor_ois: Optional[float] = None  # bps
    ted_spread_bps: Optional[float] = None
    repo_rate_overnight: Optional[float] = None
    fx_swap_basis_eurusd: Optional[float] = None  # bps
    high_yield_bid_ask_bps: Optional[float] = None
    on_the_run_off_the_run_spread: Optional[float] = None  # bps
    composite_liquidity_score: Optional[float] = None  # 0-100, lower = worse
    stale: bool = False


class MarketBreadthSnapshot(BaseModel):
    timestamp: datetime
    advance_decline_ratio: Optional[float] = None
    new_highs_lows_ratio: Optional[float] = None
    pct_above_200ma: Optional[float] = None
    pct_above_50ma: Optional[float] = None
    mcclellan_oscillator: Optional[float] = None
    arms_index: Optional[float] = None           # TRIN
    up_volume_ratio: Optional[float] = None
    stale: bool = False


class EquityMarketSnapshot(BaseModel):
    timestamp: datetime
    spx_level: Optional[float] = None
    spx_1d_return: Optional[float] = None         # decimal
    spx_5d_return: Optional[float] = None
    spx_ytd_return: Optional[float] = None
    spx_from_52w_high: Optional[float] = None     # drawdown, negative
    nasdaq_level: Optional[float] = None
    nasdaq_1d_return: Optional[float] = None
    russell_2000_level: Optional[float] = None
    global_equity_index: Optional[float] = None   # MSCI World or proxy
    stale: bool = False


class CreditMarketSnapshot(BaseModel):
    timestamp: datetime
    ig_spread_bps: Optional[float] = None       # IG CDX or OAS
    hy_spread_bps: Optional[float] = None       # HY CDX or OAS
    em_spread_bps: Optional[float] = None       # EM sovereign spread
    cds_5y_sp500_bps: Optional[float] = None
    ig_1d_change_bps: Optional[float] = None
    hy_1d_change_bps: Optional[float] = None
    stale: bool = False


class FXSnapshot(BaseModel):
    timestamp: datetime
    dxy_index: Optional[float] = None
    eurusd: Optional[float] = None
    usdjpy: Optional[float] = None
    gbpusd: Optional[float] = None
    usdchf: Optional[float] = None
    audusd: Optional[float] = None
    usdcnh: Optional[float] = None
    em_fx_index: Optional[float] = None
    dxy_1d_return: Optional[float] = None
    stale: bool = False


class CommoditySnapshot(BaseModel):
    timestamp: datetime
    wti_crude: Optional[float] = None
    brent_crude: Optional[float] = None
    gold_spot: Optional[float] = None
    silver_spot: Optional[float] = None
    copper_spot: Optional[float] = None
    natgas_spot: Optional[float] = None
    gsci_index: Optional[float] = None
    gold_1d_return: Optional[float] = None
    oil_1d_return: Optional[float] = None
    stale: bool = False


class MarketStateSnapshot(BaseModel):
    """
    Consolidated pre-event market state. This is the canonical input
    to the Market Context Engine and downstream scoring modules.
    """
    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime
    session_state: MarketSessionState
    hours_since_close: Optional[float] = None   # None if markets open
    regime: RegimeType = RegimeType.UNKNOWN

    equity: Optional[EquityMarketSnapshot] = None
    yields: Optional[YieldCurveSnapshot] = None
    volatility: Optional[VolatilitySnapshot] = None
    liquidity: Optional[LiquiditySnapshot] = None
    breadth: Optional[MarketBreadthSnapshot] = None
    credit: Optional[CreditMarketSnapshot] = None
    fx: Optional[FXSnapshot] = None
    commodities: Optional[CommoditySnapshot] = None

    # Overall data quality: fraction of expected fields populated
    data_completeness: float = Field(default=1.0, ge=0.0, le=1.0)
    has_critical_data_gap: bool = False
    gap_description: Optional[str] = None


# ---------------------------------------------------------------------------
# Event Models
# ---------------------------------------------------------------------------

class MacroEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: datetime
    event_timestamp: datetime              # When the event occurred
    event_type: EventType
    severity: SeverityLevel = SeverityLevel.MEDIUM
    severity_score: float = Field(default=0.0, ge=0.0, le=100.0)

    institution: str                       # "Federal Reserve", "Treasury", etc.
    speaker: Optional[str] = None         # "Jerome Powell", etc.
    speaker_role: Optional[str] = None    # "Chair", "President", etc.

    title: str
    description: Optional[str] = None
    source_url: Optional[str] = None
    is_scheduled: bool = True
    is_weekend: bool = False
    is_after_hours: bool = False
    market_session_at_event: MarketSessionState = MarketSessionState.CLOSED_INTRADAY

    # Time context
    minutes_since_close: Optional[float] = None
    full_weekend_gap: bool = False         # True if Fri close -> Mon open
    next_market_open: Optional[datetime] = None
    hours_until_next_open: Optional[float] = None

    raw_text: Optional[str] = None        # Full transcript text
    headline_summary: Optional[str] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# NLP / Language Intelligence Models
# ---------------------------------------------------------------------------

class HawkishDovishScore(BaseModel):
    """Directional policy stance score with component breakdown."""
    overall_score: float = Field(ge=-1.0, le=1.0)  # -1=very dovish, +1=very hawkish
    stance: PolicyStance
    confidence: float = Field(ge=0.0, le=1.0)

    # Component scores
    rate_path_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    inflation_concern_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    growth_concern_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    financial_stability_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    urgency_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # Evidence
    hawkish_phrases: List[str] = Field(default_factory=list)
    dovish_phrases: List[str] = Field(default_factory=list)
    crisis_language_detected: bool = False
    policy_reversal_language: bool = False
    forward_guidance_change: bool = False

    method: str = "lexicon"  # "lexicon" | "transformer" | "ensemble"


class PolicySurpriseVector(BaseModel):
    """
    Structured representation of the policy surprise along multiple dimensions.
    Each dimension is scored relative to market expectations.
    Positive = more hawkish/tighter than expected.
    Negative = more dovish/looser than expected.
    """
    event_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Core dimensions (-1 to +1 scale, 0 = in-line with expectations)
    rate_path_surprise: float = Field(default=0.0, ge=-1.0, le=1.0)
    inflation_outlook_surprise: float = Field(default=0.0, ge=-1.0, le=1.0)
    growth_outlook_surprise: float = Field(default=0.0, ge=-1.0, le=1.0)
    balance_sheet_surprise: float = Field(default=0.0, ge=-1.0, le=1.0)
    financial_stability_surprise: float = Field(default=0.0, ge=-1.0, le=1.0)
    forward_guidance_surprise: float = Field(default=0.0, ge=-1.0, le=1.0)
    urgency_surprise: float = Field(default=0.0, ge=0.0, le=1.0)  # 0=none, 1=extreme

    # Composite surprise magnitude (always positive)
    composite_surprise_magnitude: float = Field(default=0.0, ge=0.0, le=1.0)

    # Direction of surprise
    net_direction: float = Field(default=0.0, ge=-1.0, le=1.0)  # hawkish vs dovish

    hawkish_dovish: Optional[HawkishDovishScore] = None
    key_phrases: List[str] = Field(default_factory=list)
    interpretation_notes: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Risk Scoring Models
# ---------------------------------------------------------------------------

class SubRiskScore(BaseModel):
    """Single sub-component risk score with full explainability."""
    name: str
    score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)
    weighted_contribution: float = Field(default=0.0)

    # Explainability
    primary_driver: str = ""
    contributing_factors: List[str] = Field(default_factory=list)
    data_quality: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def compute_contribution(self) -> "SubRiskScore":
        self.weighted_contribution = self.score * self.weight
        return self


class CompositeRiskScore(BaseModel):
    """
    Final composite macro shock risk score with full decomposition.
    This is the primary output of the Risk Scoring Engine.
    """
    score_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    composite_score: float = Field(ge=0.0, le=100.0)
    severity: SeverityLevel

    # Sub-scores
    liquidity_risk: SubRiskScore
    volatility_risk: SubRiskScore
    rate_shock_risk: SubRiskScore
    equity_downside_risk: SubRiskScore
    credit_spread_risk: SubRiskScore
    fx_risk: SubRiskScore
    commodity_shock_risk: SubRiskScore
    weekend_gap_risk: SubRiskScore
    policy_ambiguity_risk: SubRiskScore

    # Multipliers applied
    regime_multiplier: float = Field(default=1.0, ge=1.0, le=2.0)
    gap_risk_multiplier: float = Field(default=1.0, ge=1.0, le=1.5)
    regime: RegimeType = RegimeType.UNKNOWN

    # Top-line interpretation
    summary: str = ""
    primary_risk_drivers: List[str] = Field(default_factory=list)
    recommended_action_level: str = "MONITOR"

    # Data quality
    overall_data_quality: float = Field(default=1.0, ge=0.0, le=1.0)
    score_reliability: str = "HIGH"  # HIGH | MEDIUM | LOW


# ---------------------------------------------------------------------------
# Scenario Models
# ---------------------------------------------------------------------------

class ScenarioOutcome(BaseModel):
    """A single scenario branch in the probability-weighted scenario tree."""
    scenario_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    probability: float = Field(ge=0.0, le=1.0)

    # Expected market impacts (in standard deviations or bps)
    equity_impact_z: float = 0.0         # z-score vs historical distribution
    equity_impact_pct: float = 0.0       # estimated % move
    yield_10y_change_bps: float = 0.0
    yield_2y_change_bps: float = 0.0
    credit_hy_change_bps: float = 0.0
    vix_change: float = 0.0
    dxy_change_pct: float = 0.0
    gold_change_pct: float = 0.0
    oil_change_pct: float = 0.0

    # Risk characteristics
    is_tail_scenario: bool = False
    liquidity_impairment: float = Field(default=0.0, ge=0.0, le=1.0)
    correlation_spike_expected: bool = False
    trading_halt_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    forced_deleveraging_risk: float = Field(default=0.0, ge=0.0, le=1.0)

    # Horizon
    impact_horizon_hours: float = 24.0
    first_price_discovery: str = "next_cash_open"  # or "futures_immediate"


class ScenarioTree(BaseModel):
    """Probability-weighted scenario tree for the event."""
    tree_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    regime: RegimeType

    scenarios: List[ScenarioOutcome] = Field(default_factory=list)

    # Probability-weighted expected values
    expected_equity_impact_pct: float = 0.0
    expected_yield_change_bps: float = 0.0
    expected_vix_change: float = 0.0
    tail_loss_5pct: float = 0.0          # 5th percentile equity outcome
    tail_loss_1pct: float = 0.0          # 1st percentile equity outcome

    # Monday gap estimate (if weekend event)
    monday_gap_estimate_pct: Optional[float] = None
    monday_gap_confidence: Optional[float] = None

    @field_validator("scenarios")
    @classmethod
    def probabilities_sum_to_one(cls, v: List[ScenarioOutcome]) -> List[ScenarioOutcome]:
        if v:
            total = sum(s.probability for s in v)
            if abs(total - 1.0) > 0.02:
                raise ValueError(f"Scenario probabilities sum to {total:.3f}, expected ~1.0")
        return v


# ---------------------------------------------------------------------------
# Portfolio Impact Models
# ---------------------------------------------------------------------------

class HedgeRecommendation(BaseModel):
    asset_class: AssetClass
    instrument_description: str         # e.g. "SPX put spreads 2-week expiry"
    action: str                         # "BUY" | "SELL" | "REDUCE" | "ADD"
    urgency: str                        # "IMMEDIATE" | "PRE-OPEN" | "INTRADAY"
    sizing_guidance: str                # e.g. "5-10% of equity beta notional"
    rationale: str
    estimated_cost_bps: Optional[float] = None
    estimated_protection_value: Optional[str] = None
    requires_pm_approval: bool = True


class PortfolioImpactReport(BaseModel):
    """
    Actionable portfolio-level risk management guidance.
    Structured for downstream OMS/EMS/PMS integration.
    """
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    score_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Top-level action
    action_level: str                   # "NO_ACTION" | "MONITOR" | "REDUCE" | "HEDGE" | "EMERGENCY_DERISKING"
    recommended_gross_exposure_change: Optional[float] = None   # fractional, e.g. -0.20 = reduce 20%
    recommended_net_exposure_change: Optional[float] = None
    recommended_leverage_change: Optional[float] = None

    # Asset class guidance
    equity_guidance: str = ""
    fixed_income_guidance: str = ""
    rates_guidance: str = ""
    fx_guidance: str = ""
    commodity_guidance: str = ""
    credit_guidance: str = ""
    vol_guidance: str = ""

    # Specific hedges
    hedge_recommendations: List[HedgeRecommendation] = Field(default_factory=list)

    # Risk metrics post-event
    estimated_portfolio_var_change: Optional[float] = None  # fractional change
    estimated_drawdown_risk: Optional[float] = None

    # Operational flags
    trigger_kill_switch: bool = False
    alert_level: AlertLevel = AlertLevel.MEDIUM
    requires_immediate_review: bool = False
    human_override_required: bool = True

    notes: str = ""


# ---------------------------------------------------------------------------
# Monitoring / Alert Models
# ---------------------------------------------------------------------------

class RiskAlert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: Optional[str] = None
    score_id: Optional[str] = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    level: AlertLevel
    title: str
    message: str
    composite_score: Optional[float] = None
    triggered_thresholds: List[str] = Field(default_factory=list)

    requires_acknowledgment: bool = False
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None

    routing_targets: List[str] = Field(default_factory=list)  # ["slack", "pagerduty", "oms"]
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Backtesting Models
# ---------------------------------------------------------------------------

class BacktestEvent(BaseModel):
    """Historical event record for backtesting."""
    event_id: str
    event_date: datetime
    event_type: EventType
    is_weekend: bool
    institution: str
    speaker: Optional[str] = None
    actual_policy_stance: Optional[PolicyStance] = None
    description: str

    # Realized market outcomes (known post-hoc, never used in signal generation)
    realized_spx_next_session_return: Optional[float] = None
    realized_10y_yield_change_bps: Optional[float] = None
    realized_vix_change: Optional[float] = None
    realized_hy_spread_change_bps: Optional[float] = None
    trading_halt_occurred: bool = False
    emergency_action_followed: bool = False

    data_validated: bool = False


class BacktestResult(BaseModel):
    """Aggregate results from a backtest run."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config_hash: str = ""

    n_events: int = 0
    n_weekend_events: int = 0
    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None

    # Performance metrics
    mean_composite_score: float = 0.0
    score_accuracy: float = 0.0          # correlation of score with realized severity
    precision_at_critical: float = 0.0   # precision when score > 75
    recall_at_critical: float = 0.0

    # Risk metrics
    expected_shortfall_5pct: float = 0.0
    max_drawdown: float = 0.0
    tail_loss_1pct: float = 0.0
    avg_weekend_gap_estimate_error: float = 0.0

    regime_breakdown: Dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


# ---------------------------------------------------------------------------
# Pipeline / Orchestration Models
# ---------------------------------------------------------------------------

class PipelineRunContext(BaseModel):
    """Shared context object passed through the full pipeline."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    environment: str = "research"   # research | staging | production

    event: Optional[MacroEvent] = None
    market_state: Optional[MarketStateSnapshot] = None
    policy_surprise: Optional[PolicySurpriseVector] = None
    scenario_tree: Optional[ScenarioTree] = None
    risk_score: Optional[CompositeRiskScore] = None
    portfolio_impact: Optional[PortfolioImpactReport] = None
    alerts: List[RiskAlert] = Field(default_factory=list)

    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    completed_stages: List[str] = Field(default_factory=list)
    failed_stages: List[str] = Field(default_factory=list)

    def mark_stage_complete(self, stage: str) -> None:
        self.completed_stages.append(stage)

    def mark_stage_failed(self, stage: str, error: str) -> None:
        self.failed_stages.append(stage)
        self.errors.append(f"[{stage}] {error}")

    @property
    def is_viable(self) -> bool:
        """True if pipeline has enough data to generate a meaningful risk score."""
        return (
            self.event is not None
            and self.market_state is not None
            and not self.market_state.has_critical_data_gap
        )
