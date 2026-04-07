"""
data/ingestion.py

Market Data Ingestion, Validation, and Market State Construction.

Responsibilities:
- Build MarketStateSnapshot from raw DataFrames (backtest mode)
- Build MarketStateSnapshot from live feeds (production mode)
- Validate data quality, staleness, and bounds
- Handle missing data with explicit impairment flags
- Align all data to UTC timestamps
- Build synthetic market state for testing and research
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import structlog

from macro_shock.data_schema.models import (
    CommoditySnapshot,
    CreditMarketSnapshot,
    EquityMarketSnapshot,
    FXSnapshot,
    LiquiditySnapshot,
    MarketBreadthSnapshot,
    MarketSessionState,
    MarketStateSnapshot,
    VolatilitySnapshot,
    YieldCurveSnapshot,
)
from macro_shock.event_detection.calendar import MarketCalendar

logger = structlog.get_logger(__name__)

MAX_STALENESS_EQUITY_MINUTES = 15
MAX_STALENESS_YIELDS_MINUTES = 30
MAX_STALENESS_CREDIT_MINUTES = 60
MAX_STALENESS_VOL_MINUTES = 30


def _is_stale(data_time: datetime, as_of: datetime, max_minutes: float) -> bool:
    delta = (as_of - data_time).total_seconds() / 60
    return delta > max_minutes


class MarketStateBuilder:
    """
    Constructs MarketStateSnapshot from various data sources.

    Handles:
    - DataFrame-based construction (backtesting)
    - Column name normalization
    - Missing data imputation with quality flags
    - Staleness detection
    """

    @staticmethod
    def build_from_dataframe(
        df: pd.DataFrame,
        as_of: datetime,
        calendar: MarketCalendar,
    ) -> MarketStateSnapshot:
        """
        Build MarketStateSnapshot from a pre-filtered DataFrame.
        Expects columns matching the canonical field names below.
        """
        as_of_utc = as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)

        session_state = MarketStateBuilder._get_session_state(as_of_utc, calendar)
        hours_since_close = None
        last_close = calendar.last_market_close(as_of_utc)
        if last_close:
            hours_since_close = (as_of_utc - last_close).total_seconds() / 3600

        latest = df.sort_values("timestamp").iloc[-1] if not df.empty else pd.Series(dtype=float)

        def safe(col, default=None):
            val = latest.get(col, default)
            if pd.isna(val) if val is not None else True:
                return default
            return val

        # Yields
        y2 = safe("yield_2y")
        y10 = safe("yield_10y")
        yields = YieldCurveSnapshot(
            timestamp=as_of_utc,
            y2=y2,
            y5=safe("yield_5y"),
            y10=y10,
            y30=safe("yield_30y"),
            real_yield_10=safe("real_yield_10y"),
            breakeven_10=safe("breakeven_10y"),
        ) if y10 is not None else None

        # Volatility
        vix = safe("vix")
        vol = VolatilitySnapshot(
            timestamp=as_of_utc,
            vix_spot=vix,
            vix_1m=safe("vix_1m"),
            vix_3m=safe("vix_3m"),
            realized_vol_1m=safe("realized_vol_1m"),
            vol_risk_premium=safe("vol_risk_premium"),
            skew_25d=safe("skew_25d"),
            put_call_ratio=safe("put_call_ratio"),
            vvix=safe("vvix"),
            move_index=safe("move_index"),
        ) if vix is not None else None

        # Liquidity
        liq = LiquiditySnapshot(
            timestamp=as_of_utc,
            bid_ask_spread_spx_bps=safe("bid_ask_spx_bps"),
            funding_spread_libor_ois=safe("libor_ois_bps"),
            ted_spread_bps=safe("ted_spread_bps"),
            composite_liquidity_score=safe("liquidity_score"),
        )

        # Equity
        spx = safe("spx_level")
        equity = EquityMarketSnapshot(
            timestamp=as_of_utc,
            spx_level=spx,
            spx_1d_return=safe("spx_1d_return"),
            spx_5d_return=safe("spx_5d_return"),
            spx_from_52w_high=safe("spx_from_52w_high"),
            nasdaq_level=safe("nasdaq_level"),
            nasdaq_1d_return=safe("nasdaq_1d_return"),
            russell_2000_level=safe("russell_level"),
        ) if spx is not None else None

        # Credit
        hy = safe("hy_spread_bps")
        credit = CreditMarketSnapshot(
            timestamp=as_of_utc,
            ig_spread_bps=safe("ig_spread_bps"),
            hy_spread_bps=hy,
            em_spread_bps=safe("em_spread_bps"),
            ig_1d_change_bps=safe("ig_1d_change_bps"),
            hy_1d_change_bps=safe("hy_1d_change_bps"),
        ) if hy is not None else None

        # FX
        dxy = safe("dxy_index")
        fx = FXSnapshot(
            timestamp=as_of_utc,
            dxy_index=dxy,
            eurusd=safe("eurusd"),
            usdjpy=safe("usdjpy"),
            gbpusd=safe("gbpusd"),
            usdchf=safe("usdchf"),
            audusd=safe("audusd"),
            dxy_1d_return=safe("dxy_1d_return"),
        ) if dxy is not None else None

        # Commodities
        gold = safe("gold_spot")
        commodities = CommoditySnapshot(
            timestamp=as_of_utc,
            wti_crude=safe("wti_crude"),
            brent_crude=safe("brent_crude"),
            gold_spot=gold,
            copper_spot=safe("copper_spot"),
            gold_1d_return=safe("gold_1d_return"),
            oil_1d_return=safe("oil_1d_return"),
        ) if gold is not None else None

        # Breadth
        adr = safe("advance_decline_ratio")
        breadth = MarketBreadthSnapshot(
            timestamp=as_of_utc,
            advance_decline_ratio=adr,
            pct_above_200ma=safe("pct_above_200ma"),
            pct_above_50ma=safe("pct_above_50ma"),
        ) if adr is not None else None

        # Data completeness
        n_possible = 8  # equity, yields, vol, liq, credit, fx, comm, breadth
        n_available = sum([
            equity is not None, yields is not None, vol is not None,
            liq is not None, credit is not None, fx is not None,
            commodities is not None, breadth is not None,
        ])
        completeness = n_available / n_possible

        has_gap = completeness < 0.5 or (yields is None and vol is None)
        gap_desc = None
        if has_gap:
            gap_desc = f"Missing critical data: completeness={completeness:.0%}"

        return MarketStateSnapshot(
            timestamp=as_of_utc,
            session_state=session_state,
            hours_since_close=hours_since_close,
            equity=equity,
            yields=yields,
            volatility=vol,
            liquidity=liq,
            breadth=breadth,
            credit=credit,
            fx=fx,
            commodities=commodities,
            data_completeness=completeness,
            has_critical_data_gap=has_gap,
            gap_description=gap_desc,
        )

    @staticmethod
    def build_synthetic(
        as_of: datetime,
        calendar: MarketCalendar,
        stress_level: float = 0.3,
        seed: Optional[int] = None,
    ) -> MarketStateSnapshot:
        """
        Build a synthetic market state for testing and research.
        stress_level in [0, 1]: 0 = benign, 1 = max stress.
        """
        rng = random.Random(seed)
        np_rng = np.random.RandomState(seed)

        as_of_utc = as_of.astimezone(timezone.utc)
        session_state = MarketStateBuilder._get_session_state(as_of_utc, calendar)

        vix = 12 + stress_level * 28 + np_rng.normal(0, 2)
        hy_spread = 300 + stress_level * 500 + np_rng.normal(0, 20)
        ig_spread = 60 + stress_level * 150 + np_rng.normal(0, 5)
        y2 = 4.5 - stress_level * 2.0 + np_rng.normal(0, 0.05)
        y10 = 4.0 - stress_level * 0.5 + np_rng.normal(0, 0.05)
        slope_2_10 = (y10 - y2) * 100
        spx = 4500 * (1 - stress_level * 0.15) + np_rng.normal(0, 50)
        dxy = 100 + stress_level * 8 + np_rng.normal(0, 0.5)

        yields = YieldCurveSnapshot(
            timestamp=as_of_utc,
            y2=float(y2),
            y5=float((y2 + y10) / 2),
            y10=float(y10),
            y30=float(y10 + 0.3),
        )

        vol = VolatilitySnapshot(
            timestamp=as_of_utc,
            vix_spot=float(np.clip(vix, 10, 80)),
            vix_1m=float(np.clip(vix * 0.98, 10, 80)),
            vix_3m=float(np.clip(vix * 0.95, 10, 80)),
            realized_vol_1m=float(np.clip(vix * 0.9, 8, 70)),
            put_call_ratio=float(np.clip(0.7 + stress_level * 0.5, 0.5, 1.5)),
            vvix=float(np.clip(90 + stress_level * 40, 70, 150)),
        )

        liquidity = LiquiditySnapshot(
            timestamp=as_of_utc,
            bid_ask_spread_spx_bps=float(np.clip(1.0 + stress_level * 6, 0.5, 10)),
            ted_spread_bps=float(np.clip(15 + stress_level * 80, 10, 120)),
            composite_liquidity_score=float(np.clip(80 - stress_level * 60, 10, 100)),
        )

        equity = EquityMarketSnapshot(
            timestamp=as_of_utc,
            spx_level=float(np.clip(spx, 2000, 6000)),
            spx_1d_return=float(np_rng.normal(-stress_level * 0.01, 0.008)),
            spx_from_52w_high=float(-stress_level * 0.15 + np_rng.normal(0, 0.01)),
            nasdaq_level=float(spx * 3.5),
        )

        credit = CreditMarketSnapshot(
            timestamp=as_of_utc,
            ig_spread_bps=float(np.clip(ig_spread, 40, 300)),
            hy_spread_bps=float(np.clip(hy_spread, 200, 1200)),
        )

        fx = FXSnapshot(
            timestamp=as_of_utc,
            dxy_index=float(np.clip(dxy, 85, 115)),
            eurusd=float(np.clip(1.10 - stress_level * 0.05, 0.95, 1.25)),
            usdjpy=float(np.clip(145 + stress_level * 10, 100, 160)),
        )

        commodities = CommoditySnapshot(
            timestamp=as_of_utc,
            gold_spot=float(np.clip(1900 + stress_level * 300, 1500, 3000)),
            wti_crude=float(np.clip(75 - stress_level * 20, 30, 130)),
        )

        breadth = MarketBreadthSnapshot(
            timestamp=as_of_utc,
            advance_decline_ratio=float(np.clip(0.6 - stress_level * 0.35, 0.15, 0.85)),
            pct_above_200ma=float(np.clip(65 - stress_level * 45, 10, 85)),
        )

        return MarketStateSnapshot(
            timestamp=as_of_utc,
            session_state=session_state,
            equity=equity,
            yields=yields,
            volatility=vol,
            liquidity=liquidity,
            breadth=breadth,
            credit=credit,
            fx=fx,
            commodities=commodities,
            data_completeness=1.0,
            has_critical_data_gap=False,
        )

    @staticmethod
    def build_minimal(
        as_of: datetime,
        calendar: MarketCalendar,
    ) -> MarketStateSnapshot:
        """Minimal snapshot with only session state; used as fallback."""
        as_of_utc = as_of.astimezone(timezone.utc)
        session_state = MarketStateBuilder._get_session_state(as_of_utc, calendar)
        return MarketStateSnapshot(
            timestamp=as_of_utc,
            session_state=session_state,
            data_completeness=0.0,
            has_critical_data_gap=True,
            gap_description="No market data available; minimal state.",
        )

    @staticmethod
    def _get_session_state(dt: datetime, calendar: MarketCalendar) -> MarketSessionState:
        if calendar.is_in_weekend_gap_corridor(dt):
            return MarketSessionState.CLOSED_WEEKEND
        if calendar.is_holiday(dt):
            return MarketSessionState.CLOSED_HOLIDAY
        if calendar.is_trading_day(dt):
            from zoneinfo import ZoneInfo
            et = dt.astimezone(ZoneInfo("America/New_York"))
            h, m = et.hour, et.minute
            if (9, 30) <= (h, m) < (16, 0):
                return MarketSessionState.OPEN
            if (4, 0) <= (h, m) < (9, 30):
                return MarketSessionState.PRE_MARKET
            return MarketSessionState.AFTER_HOURS
        return MarketSessionState.CLOSED_OVERNIGHT
