"""
tests/unit/test_backtesting.py

Unit tests for the Backtesting and Simulation framework.
Validates look-ahead bias enforcement, metric computation, and event filtering.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from macro_shock.backtesting.event_study import (
    BacktestEngine, LookAheadBiasError, TimestampGuard, TransactionCostModel
)
from macro_shock.data_schema.models import BacktestEvent, BacktestResult, EventType


# ─── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def simple_market_df():
    """A minimal market DataFrame spanning 30 days."""
    dates = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(30)]
    return pd.DataFrame({
        "timestamp": dates,
        "spx_level": [4500.0 + i * 5 for i in range(30)],
        "spx_return": [0.001 * (i % 3 - 1) for i in range(30)],
        "vix": [18.0 - i * 0.1 for i in range(30)],
        "yield_10y": [4.0 + i * 0.01 for i in range(30)],
        "hy_spread_bps": [400.0 - i * 2 for i in range(30)],
        "dxy_index": [104.0] * 30,
        "gold_spot": [2000.0] * 30,
    })


@pytest.fixture
def timestamp_guard(simple_market_df):
    return TimestampGuard(simple_market_df, timestamp_col="timestamp")


@pytest.fixture
def sample_backtest_event():
    return BacktestEvent(
        event_id="TEST_001",
        event_date=datetime(2024, 1, 15, 18, 30, tzinfo=timezone.utc),
        event_type=EventType.PRESS_CONFERENCE,
        is_weekend=False,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        description="Test FOMC press conference",
        realized_spx_next_session_return=-0.025,
        realized_10y_yield_change_bps=10.0,
        realized_vix_change=3.0,
        trading_halt_occurred=False,
        data_validated=True,
    )


@pytest.fixture
def weekend_backtest_event():
    return BacktestEvent(
        event_id="TEST_WEEKEND_001",
        event_date=datetime(2024, 1, 13, 19, 0, tzinfo=timezone.utc),  # Saturday
        event_type=EventType.WEEKEND_POLICY_ACTION,
        is_weekend=True,
        institution="Federal Reserve",
        speaker="Jerome Powell",
        description="Weekend emergency statement",
        realized_spx_next_session_return=-0.055,
        realized_10y_yield_change_bps=-20.0,
        realized_vix_change=8.5,
        trading_halt_occurred=False,
        data_validated=True,
    )


# ─── TimestampGuard ───────────────────────────────────────────

class TestTimestampGuard:

    def test_get_data_as_of_returns_only_past_data(self, timestamp_guard):
        watermark = datetime(2024, 1, 15, tzinfo=timezone.utc)
        timestamp_guard.set_watermark(watermark)
        data = timestamp_guard.get_data_as_of(datetime(2024, 1, 10, tzinfo=timezone.utc))
        assert not data.empty
        assert all(data["timestamp"] <= datetime(2024, 1, 10, tzinfo=timezone.utc))

    def test_get_data_after_watermark_raises(self, timestamp_guard):
        watermark = datetime(2024, 1, 15, tzinfo=timezone.utc)
        timestamp_guard.set_watermark(watermark)
        with pytest.raises(LookAheadBiasError):
            timestamp_guard.get_data_as_of(datetime(2024, 1, 20, tzinfo=timezone.utc))

    def test_get_post_event_data_works_after_watermark_reset(self, timestamp_guard):
        event_time = datetime(2024, 1, 10, tzinfo=timezone.utc)
        timestamp_guard.set_watermark(datetime(2024, 1, 30, tzinfo=timezone.utc))
        post_data = timestamp_guard.get_post_event(event_time, timedelta(days=5))
        assert not post_data.empty
        assert all(post_data["timestamp"] > event_time)

    def test_data_is_sorted_by_timestamp(self, simple_market_df):
        # Shuffle the df to test sorting
        shuffled = simple_market_df.sample(frac=1, random_state=42).reset_index(drop=True)
        guard = TimestampGuard(shuffled, timestamp_col="timestamp")
        guard.set_watermark(datetime(2024, 2, 1, tzinfo=timezone.utc))
        data = guard.get_data_as_of(datetime(2024, 1, 20, tzinfo=timezone.utc))
        timestamps = list(data["timestamp"])
        assert timestamps == sorted(timestamps)

    def test_lookback_filter_works(self, timestamp_guard):
        timestamp_guard.set_watermark(datetime(2024, 2, 1, tzinfo=timezone.utc))
        data = timestamp_guard.get_data_as_of(
            datetime(2024, 1, 20, tzinfo=timezone.utc),
            lookback=timedelta(days=5),
        )
        min_ts = datetime(2024, 1, 15, tzinfo=timezone.utc)
        assert all(data["timestamp"] >= min_ts)


# ─── TransactionCostModel ────────────────────────────────────

class TestTransactionCostModel:

    def test_base_slippage_returned(self):
        model = TransactionCostModel()
        assert model.equity_slippage(0.0) == model.base_equity_slippage_bps

    def test_slippage_increases_with_impairment(self):
        model = TransactionCostModel()
        low  = model.equity_slippage(0.0)
        high = model.equity_slippage(0.8)
        assert high > low

    def test_max_impairment_5x_base(self):
        model = TransactionCostModel()
        max_slip = model.equity_slippage(1.0)
        assert max_slip == pytest.approx(model.base_equity_slippage_bps * 5.0)

    def test_futures_cheaper_than_equity(self):
        model = TransactionCostModel()
        assert model.futures_slippage(0.0) < model.equity_slippage(0.0)


# ─── BacktestEngine (lightweight) ────────────────────────────

class TestBacktestEngineFiltering:
    """Test event filtering and result aggregation without running full pipeline."""

    def test_filter_by_date_range(self):
        events = [
            BacktestEvent(
                event_id=f"E{i}", institution="Federal Reserve",
                event_date=datetime(2024, 1, 1 + i * 10, tzinfo=timezone.utc),
                event_type=EventType.PRESS_CONFERENCE, is_weekend=False,
                description="test",
            )
            for i in range(5)
        ]
        # Use engine's private filter method
        from macro_shock.backtesting.event_study import BacktestEngine
        eng = BacktestEngine.__new__(BacktestEngine)  # bypass __init__

        start = datetime(2024, 1, 11, tzinfo=timezone.utc)
        end   = datetime(2024, 1, 31, tzinfo=timezone.utc)
        filtered = eng._filter_events(events, start, end)

        assert all(start <= e.event_date <= end for e in filtered)
        assert len(filtered) < len(events)

    def test_filter_is_sorted_by_date(self):
        from macro_shock.backtesting.event_study import BacktestEngine
        eng = BacktestEngine.__new__(BacktestEngine)

        events = [
            BacktestEvent(
                event_id=f"E{i}", institution="Federal Reserve",
                event_date=datetime(2024, 1, 15 - i, tzinfo=timezone.utc),
                event_type=EventType.PRESS_CONFERENCE, is_weekend=False,
                description="test",
            )
            for i in range(4)
        ]
        filtered = eng._filter_events(events, None, None)
        dates = [e.event_date for e in filtered]
        assert dates == sorted(dates)


class TestBacktestResultAggregation:
    """Test that aggregate metrics compute correctly."""

    def test_empty_outcomes_returns_zero_metrics(self):
        from macro_shock.backtesting.event_study import BacktestEngine
        eng = BacktestEngine.__new__(BacktestEngine)
        result = eng._aggregate_results([], [], 0)
        assert result.n_events == 0
        assert result.score_accuracy == 0.0

    def test_precision_at_critical_computes(self):
        """With known outcomes, precision at critical should be calculable."""
        from macro_shock.backtesting.event_study import BacktestEngine, EventOutcome
        eng = BacktestEngine.__new__(BacktestEngine)

        # 2 CRITICAL predictions; 1 correct (SPX < -3%), 1 wrong
        outcomes = [
            EventOutcome(
                event_id="A", event_date=datetime.now(timezone.utc),
                event_type=EventType.PRESS_CONFERENCE, is_weekend=False,
                predicted_composite_score=80.0, spx_1d_return=-0.05,  # True positive
            ),
            EventOutcome(
                event_id="B", event_date=datetime.now(timezone.utc),
                event_type=EventType.PRESS_CONFERENCE, is_weekend=False,
                predicted_composite_score=78.0, spx_1d_return=0.01,  # False positive
            ),
        ]
        result = eng._aggregate_results(outcomes, outcomes, 0)
        assert result.precision_at_critical == pytest.approx(0.5)

    def test_recall_at_critical_computes(self):
        from macro_shock.backtesting.event_study import BacktestEngine, EventOutcome
        eng = BacktestEngine.__new__(BacktestEngine)

        # 2 actual severe events; system caught 1 (score>=75), missed 1
        outcomes = [
            EventOutcome(
                event_id="A", event_date=datetime.now(timezone.utc),
                event_type=EventType.PRESS_CONFERENCE, is_weekend=False,
                predicted_composite_score=80.0, spx_1d_return=-0.06,  # Caught
            ),
            EventOutcome(
                event_id="B", event_date=datetime.now(timezone.utc),
                event_type=EventType.PRESS_CONFERENCE, is_weekend=False,
                predicted_composite_score=30.0, spx_1d_return=-0.04,  # Missed
            ),
        ]
        result = eng._aggregate_results(outcomes, outcomes, 0)
        assert result.recall_at_critical == pytest.approx(0.5)
