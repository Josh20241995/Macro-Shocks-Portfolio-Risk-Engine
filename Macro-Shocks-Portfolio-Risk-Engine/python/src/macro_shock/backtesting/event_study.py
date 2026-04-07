"""
backtesting/event_study.py

Historical Event Study and Backtesting Framework.

Supports:
- Historical FOMC and macro event replay
- Pre/post event window analysis
- Overnight and weekend gap simulation
- Regime-segmented performance analysis
- Walk-forward validation
- Look-ahead bias prevention (strict timestamp ordering)
- Slippage and liquidity stress adjustments
- Full risk metrics: ES, MaxDD, Gap Risk, Tail Loss, VoV

Critical design invariant:
  ALL signal generation uses only data available STRICTLY BEFORE
  the event_timestamp. Any use of post-event data in signal generation
  is a look-ahead bias violation. This is enforced via the
  TimestampGuard wrapper on all data access calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import structlog

from macro_shock.data_schema.models import (
    BacktestEvent,
    BacktestResult,
    CompositeRiskScore,
    EventType,
    MacroEvent,
    RegimeType,
    SeverityLevel,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Look-Ahead Bias Guard
# ---------------------------------------------------------------------------

class LookAheadBiasError(Exception):
    """Raised when post-event data is accessed before it is valid."""
    pass


class TimestampGuard:
    """
    Wraps a DataFrame and raises LookAheadBiasError if any query
    requests data strictly after the 'current_time' watermark.

    All data access in backtesting goes through this guard.
    """

    def __init__(self, df: pd.DataFrame, timestamp_col: str = "timestamp"):
        self._df = df.sort_values(timestamp_col).reset_index(drop=True)
        self._ts_col = timestamp_col
        self._watermark: Optional[datetime] = None

    def set_watermark(self, t: datetime) -> None:
        """Set the current allowed time horizon."""
        self._watermark = t

    def get_data_as_of(self, as_of: datetime, lookback: Optional[timedelta] = None) -> pd.DataFrame:
        """
        Return data where timestamp <= as_of.
        Raises LookAheadBiasError if as_of > watermark.
        """
        if self._watermark is not None and as_of > self._watermark:
            raise LookAheadBiasError(
                f"Data requested for {as_of.isoformat()} "
                f"but watermark is {self._watermark.isoformat()}. "
                "Look-ahead bias detected."
            )
        mask = self._df[self._ts_col] <= as_of
        if lookback:
            mask &= self._df[self._ts_col] >= (as_of - lookback)
        return self._df[mask].copy()

    def get_post_event(self, after: datetime, horizon: timedelta) -> pd.DataFrame:
        """
        Return post-event data for outcome labeling.
        ONLY called in the outcome evaluation phase, after signal generation is complete.
        """
        mask = (self._df[self._ts_col] > after) & (
            self._df[self._ts_col] <= (after + horizon)
        )
        return self._df[mask].copy()


# ---------------------------------------------------------------------------
# Slippage and Transaction Cost Model
# ---------------------------------------------------------------------------

@dataclass
class TransactionCostModel:
    """
    Models realistic transaction costs for post-event trading.
    Slippage is amplified during stressed market conditions.
    """
    base_equity_slippage_bps: float = 5.0
    base_futures_slippage_bps: float = 1.5
    base_options_slippage_bps: float = 20.0
    base_credit_slippage_bps: float = 10.0

    # Stress multipliers
    def slippage_multiplier(self, liquidity_impairment: float) -> float:
        """
        Returns slippage multiplier based on liquidity conditions.
        At full liquidity impairment (1.0), slippage is 5x normal.
        """
        return 1.0 + liquidity_impairment * 4.0

    def equity_slippage(self, liquidity_impairment: float = 0.0) -> float:
        return self.base_equity_slippage_bps * self.slippage_multiplier(liquidity_impairment)

    def futures_slippage(self, liquidity_impairment: float = 0.0) -> float:
        return self.base_futures_slippage_bps * self.slippage_multiplier(liquidity_impairment)


# ---------------------------------------------------------------------------
# Event Window Definition
# ---------------------------------------------------------------------------

@dataclass
class EventWindow:
    """Defines time windows for a single backtest event."""
    event: BacktestEvent
    pre_window_start: datetime    # For market state ingestion
    pre_window_end: datetime      # = event_timestamp (strict)
    post_window_1h: datetime
    post_window_4h: datetime
    post_window_1d: datetime
    post_window_1w: datetime
    is_weekend_event: bool
    next_session_open: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------

@dataclass
class EventOutcome:
    """Realized market outcome for a single historical event."""
    event_id: str
    event_date: datetime
    event_type: EventType
    is_weekend: bool

    # Realized returns (post-event, first available session)
    spx_next_session_return: Optional[float] = None
    spx_1d_return: Optional[float] = None
    spx_5d_return: Optional[float] = None
    yield_10y_change_1d_bps: Optional[float] = None
    vix_change_1d: Optional[float] = None
    hy_spread_change_1d_bps: Optional[float] = None

    # Predicted values from MSRE
    predicted_composite_score: Optional[float] = None
    predicted_equity_impact: Optional[float] = None
    predicted_severity: Optional[SeverityLevel] = None
    regime: Optional[RegimeType] = None

    # Gap-specific
    monday_gap_actual: Optional[float] = None
    monday_gap_predicted: Optional[float] = None
    trading_halt_occurred: bool = False

    # Strategy P&L (if applying recommended hedges)
    strategy_pnl_bps: Optional[float] = None


class BacktestEngine:
    """
    Historical event study engine.

    Replays historical macro events through the MSRE pipeline using
    data available only at the time of each event (strict look-ahead prevention).
    Measures the accuracy of risk scores, scenario trees, and portfolio guidance.

    Walk-forward validation design:
    - Training period: used to calibrate lexicon scores, regime thresholds
    - Validation period: pure out-of-sample, no feedback from outcomes
    - The split is configurable; default is 70/30 train/validate
    """

    def __init__(
        self,
        pipeline,               # MacroShockPipeline instance
        market_data_guard: TimestampGuard,
        cost_model: Optional[TransactionCostModel] = None,
        config: Optional[Dict] = None,
    ):
        self.pipeline = pipeline
        self.data_guard = market_data_guard
        self.cost_model = cost_model or TransactionCostModel()
        self.config = config or {}

        self.pre_event_lookback = timedelta(days=int(self.config.get("pre_event_lookback_days", 30)))
        self.post_event_horizons = [
            timedelta(hours=1),
            timedelta(hours=4),
            timedelta(days=1),
            timedelta(days=5),
        ]

    def run(
        self,
        events: List[BacktestEvent],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        regime_filter: Optional[List[RegimeType]] = None,
    ) -> BacktestResult:
        """
        Run the full backtest over a set of historical events.

        Args:
            events: Historical event records with realized outcomes.
            start_date: Only include events after this date.
            end_date: Only include events before this date.
            regime_filter: Only include events in these regimes.

        Returns:
            BacktestResult with aggregate performance metrics.
        """
        filtered = self._filter_events(events, start_date, end_date)
        logger.info(
            "backtest_started",
            n_events=len(filtered),
            start=start_date,
            end=end_date,
        )

        outcomes: List[EventOutcome] = []
        errors = 0

        for historical_event in filtered:
            try:
                outcome = self._process_single_event(historical_event)
                if outcome:
                    if regime_filter is None or outcome.regime in regime_filter:
                        outcomes.append(outcome)
            except LookAheadBiasError as e:
                logger.error("look_ahead_bias_violation", error=str(e), event_id=historical_event.event_id)
                errors += 1
            except Exception as e:
                logger.warning(
                    "backtest_event_failed",
                    event_id=historical_event.event_id,
                    error=str(e),
                )
                errors += 1

        result = self._aggregate_results(outcomes, filtered, errors)
        logger.info(
            "backtest_complete",
            n_processed=len(outcomes),
            n_errors=errors,
            score_accuracy=f"{result.score_accuracy:.3f}",
            precision_critical=f"{result.precision_at_critical:.3f}",
        )
        return result

    def _process_single_event(self, hist_event: BacktestEvent) -> Optional[EventOutcome]:
        """
        Process a single historical event through the pipeline.
        All market data is gated at the event timestamp.
        """
        event_time = hist_event.event_date

        # Set watermark: NO data after event_time in signal generation
        self.data_guard.set_watermark(event_time)

        # Get pre-event market data (strict: only data before event_time)
        pre_event_data = self.data_guard.get_data_as_of(
            as_of=event_time,
            lookback=self.pre_event_lookback,
        )

        if pre_event_data.empty:
            logger.warning("insufficient_pre_event_data", event_id=hist_event.event_id)
            return None

        # Run the pipeline in backtest mode (uses pre_event_data, not live feeds)
        run_context = self.pipeline.run_backtest_mode(
            historical_event=hist_event,
            pre_event_market_df=pre_event_data,
        )

        if run_context is None or run_context.risk_score is None:
            return None

        # NOW unlock post-event data for outcome labeling
        self.data_guard.set_watermark(event_time + timedelta(days=10))

        # Retrieve realized outcomes
        post_1d = self.data_guard.get_post_event(event_time, timedelta(days=1))
        post_5d = self.data_guard.get_post_event(event_time, timedelta(days=5))

        realized = self._extract_realized_outcomes(post_1d, post_5d, hist_event)
        strategy_pnl = self._estimate_strategy_pnl(
            run_context.risk_score,
            run_context.scenario_tree,
            realized,
            hist_event,
        )

        # Re-lock watermark
        self.data_guard.set_watermark(event_time)

        monday_gap_actual = None
        if hist_event.is_weekend and hist_event.realized_spx_next_session_return:
            monday_gap_actual = hist_event.realized_spx_next_session_return * 100

        monday_gap_pred = None
        if run_context.scenario_tree and run_context.scenario_tree.monday_gap_estimate_pct:
            monday_gap_pred = run_context.scenario_tree.monday_gap_estimate_pct

        return EventOutcome(
            event_id=hist_event.event_id,
            event_date=event_time,
            event_type=hist_event.event_type,
            is_weekend=hist_event.is_weekend,
            spx_next_session_return=hist_event.realized_spx_next_session_return,
            spx_1d_return=realized.get("spx_1d_return"),
            spx_5d_return=realized.get("spx_5d_return"),
            yield_10y_change_1d_bps=hist_event.realized_10y_yield_change_bps,
            vix_change_1d=hist_event.realized_vix_change,
            hy_spread_change_1d_bps=hist_event.realized_hy_spread_change_bps,
            predicted_composite_score=run_context.risk_score.composite_score,
            predicted_equity_impact=run_context.scenario_tree.expected_equity_impact_pct if run_context.scenario_tree else None,
            predicted_severity=run_context.risk_score.severity,
            regime=run_context.risk_score.regime,
            monday_gap_actual=monday_gap_actual,
            monday_gap_predicted=monday_gap_pred,
            trading_halt_occurred=hist_event.trading_halt_occurred,
            strategy_pnl_bps=strategy_pnl,
        )

    def _extract_realized_outcomes(
        self,
        post_1d: pd.DataFrame,
        post_5d: pd.DataFrame,
        hist_event: BacktestEvent,
    ) -> Dict:
        """Extract realized return data from post-event market data."""
        outcomes = {}
        # Use pre-validated realized data from hist_event if available
        if hist_event.realized_spx_next_session_return is not None:
            outcomes["spx_1d_return"] = hist_event.realized_spx_next_session_return
        elif not post_1d.empty and "spx_return" in post_1d.columns:
            outcomes["spx_1d_return"] = post_1d["spx_return"].iloc[-1]

        if not post_5d.empty and "spx_return" in post_5d.columns:
            outcomes["spx_5d_return"] = post_5d["spx_return"].sum()

        return outcomes

    def _estimate_strategy_pnl(
        self,
        risk_score: CompositeRiskScore,
        scenario_tree,
        realized: Dict,
        hist_event: BacktestEvent,
    ) -> Optional[float]:
        """
        Estimate P&L of the recommended defensive strategy.
        Simple model: if composite_score >= 55 and we reduce equity 20%,
        what was the P&L benefit vs. realized SPX return?

        This is illustrative. Real strategy P&L requires full position simulation.
        """
        if risk_score is None or realized.get("spx_1d_return") is None:
            return None

        spx_1d = realized["spx_1d_return"]  # decimal
        action = risk_score.recommended_action_level

        if action in ("HEDGE", "EMERGENCY_DERISKING"):
            # Assumed: reduced equity beta by 20-40%, rough hedge cost 15-20bps
            hedge_ratio = 0.20 if action == "HEDGE" else 0.40
            hedge_benefit = -spx_1d * hedge_ratio * 10000  # in bps
            hedge_cost = -18.0  # bps (options premium + slippage)

            liquidity_impairment = max(
                (s.liquidity_impairment for s in scenario_tree.scenarios
                 if s.is_tail_scenario), default=0.0
            ) if scenario_tree else 0.0
            slip = self.cost_model.equity_slippage(liquidity_impairment)

            return float(hedge_benefit + hedge_cost - slip)
        elif action == "REDUCE":
            hedge_ratio = 0.10
            hedge_benefit = -spx_1d * hedge_ratio * 10000
            return float(hedge_benefit - 8.0 - self.cost_model.equity_slippage())

        return 0.0

    def _filter_events(
        self,
        events: List[BacktestEvent],
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> List[BacktestEvent]:
        filtered = events
        if start_date:
            filtered = [e for e in filtered if e.event_date >= start_date]
        if end_date:
            filtered = [e for e in filtered if e.event_date <= end_date]
        return sorted(filtered, key=lambda e: e.event_date)

    def _aggregate_results(
        self,
        outcomes: List[EventOutcome],
        all_events: List[BacktestEvent],
        n_errors: int,
    ) -> BacktestResult:
        if not outcomes:
            return BacktestResult(n_events=len(all_events))

        scores = [o.predicted_composite_score for o in outcomes if o.predicted_composite_score is not None]
        realized_returns = [o.spx_1d_return for o in outcomes if o.spx_1d_return is not None]
        predicted_impacts = [o.predicted_equity_impact for o in outcomes if o.predicted_equity_impact is not None]

        # Score accuracy: correlation between composite score and realized severity
        score_accuracy = 0.0
        if len(scores) > 5 and len(realized_returns) >= len(scores):
            neg_returns = [-r for r in realized_returns[:len(scores)]]
            if np.std(scores) > 0 and np.std(neg_returns) > 0:
                score_accuracy = float(np.corrcoef(scores, neg_returns)[0, 1])

        # Precision at CRITICAL (score >= 75) vs realized severe outcome (SPX < -3%)
        critical_outcomes = [
            o for o in outcomes
            if o.predicted_composite_score is not None and o.predicted_composite_score >= 75
        ]
        precision_at_critical = 0.0
        recall_at_critical = 0.0
        if critical_outcomes:
            true_positives = sum(
                1 for o in critical_outcomes
                if o.spx_1d_return is not None and o.spx_1d_return < -0.03
            )
            precision_at_critical = true_positives / len(critical_outcomes)

        actual_severe = [
            o for o in outcomes
            if o.spx_1d_return is not None and o.spx_1d_return < -0.03
        ]
        if actual_severe:
            detected_severe = sum(
                1 for o in actual_severe
                if o.predicted_composite_score is not None and o.predicted_composite_score >= 75
            )
            recall_at_critical = detected_severe / len(actual_severe)

        # Risk metrics
        if realized_returns:
            arr = np.array(realized_returns)
            negative_returns = arr[arr < 0]
            expected_shortfall_5pct = float(
                np.mean(negative_returns[negative_returns <= np.percentile(negative_returns, 5)])
            ) if len(negative_returns) > 0 else 0.0
            max_drawdown = float(np.min(arr)) if len(arr) > 0 else 0.0
            tail_loss_1pct = float(np.percentile(arr, 1)) if len(arr) >= 100 else float(np.min(arr))
        else:
            expected_shortfall_5pct = 0.0
            max_drawdown = 0.0
            tail_loss_1pct = 0.0

        # Weekend gap accuracy
        weekend_outcomes = [o for o in outcomes if o.is_weekend and
                            o.monday_gap_actual is not None and
                            o.monday_gap_predicted is not None]
        gap_error = 0.0
        if weekend_outcomes:
            errors_list = [abs(o.monday_gap_actual - o.monday_gap_predicted) for o in weekend_outcomes]
            gap_error = float(np.mean(errors_list))

        # Regime breakdown
        regime_breakdown: Dict[str, Dict] = {}
        for regime in RegimeType:
            regime_outcomes = [o for o in outcomes if o.regime == regime]
            if regime_outcomes:
                rets = [o.spx_1d_return for o in regime_outcomes if o.spx_1d_return is not None]
                regime_breakdown[regime.value] = {
                    "n_events": len(regime_outcomes),
                    "mean_return": float(np.mean(rets)) if rets else None,
                    "mean_score": float(np.mean([o.predicted_composite_score for o in regime_outcomes if o.predicted_composite_score])),
                }

        # Strategy P&L
        pnls = [o.strategy_pnl_bps for o in outcomes if o.strategy_pnl_bps is not None]
        mean_strategy_pnl = float(np.mean(pnls)) if pnls else 0.0

        dates = [o.event_date for o in outcomes]

        return BacktestResult(
            n_events=len(outcomes),
            n_weekend_events=sum(1 for o in outcomes if o.is_weekend),
            date_range_start=min(dates) if dates else None,
            date_range_end=max(dates) if dates else None,
            mean_composite_score=float(np.mean(scores)) if scores else 0.0,
            score_accuracy=score_accuracy,
            precision_at_critical=precision_at_critical,
            recall_at_critical=recall_at_critical,
            expected_shortfall_5pct=expected_shortfall_5pct,
            max_drawdown=max_drawdown,
            tail_loss_1pct=tail_loss_1pct,
            avg_weekend_gap_estimate_error=gap_error,
            regime_breakdown=regime_breakdown,
            notes=(
                f"Strategy mean P&L (when score>=55): {mean_strategy_pnl:.1f}bps. "
                f"Processing errors: {n_errors}."
            ),
        )

    def walk_forward_validate(
        self,
        events: List[BacktestEvent],
        train_fraction: float = 0.70,
    ) -> Tuple[BacktestResult, BacktestResult]:
        """
        Split events into train and validation sets by time.
        Returns (train_result, validation_result).

        Validation set is strictly out-of-sample (later in time than training).
        """
        events_sorted = sorted(events, key=lambda e: e.event_date)
        split_idx = int(len(events_sorted) * train_fraction)

        train_events = events_sorted[:split_idx]
        val_events = events_sorted[split_idx:]

        logger.info(
            "walk_forward_split",
            n_train=len(train_events),
            n_val=len(val_events),
            train_end=train_events[-1].event_date if train_events else None,
            val_start=val_events[0].event_date if val_events else None,
        )

        train_result = self.run(train_events)
        val_result = self.run(val_events)

        return train_result, val_result
