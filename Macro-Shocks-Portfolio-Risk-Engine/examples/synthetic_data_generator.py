"""
examples/synthetic_data_generator.py

Generates synthetic historical event datasets and market data for
testing, demonstration, and research purposes.

All generated data is clearly labeled as synthetic.
Do not use for production model calibration without replacing with real data.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

SYNTHETIC_EVENTS = [
    {
        "event_id": "SYNTH_FED_2022_11_02",
        "description": "FOMC press conference following 75bps rate hike. Powell signals more hikes ahead.",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_date": "2022-11-02T18:30:00+00:00",
        "event_type": "press_conference",
        "is_weekend": False,
        "realized_spx_next_session_return": -0.025,
        "realized_10y_yield_change_bps": 8.0,
        "realized_vix_change": 2.3,
        "realized_hy_spread_change_bps": 18.0,
        "trading_halt_occurred": False,
        "emergency_action_followed": False,
    },
    {
        "event_id": "SYNTH_FED_2023_03_22",
        "description": "Emergency weekend statement on SVB collapse and bank stress. Discount window expanded.",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_date": "2023-03-12T16:00:00+00:00",
        "event_type": "weekend_policy_action",
        "is_weekend": True,
        "realized_spx_next_session_return": -0.018,
        "realized_10y_yield_change_bps": -22.0,
        "realized_vix_change": 5.1,
        "realized_hy_spread_change_bps": 55.0,
        "trading_halt_occurred": False,
        "emergency_action_followed": True,
    },
    {
        "event_id": "SYNTH_FED_2020_03_15",
        "description": "Emergency Sunday rate cut to zero. QE infinity announced. COVID response.",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_date": "2020-03-15T17:00:00+00:00",
        "event_type": "unscheduled_emergency",
        "is_weekend": True,
        "realized_spx_next_session_return": -0.120,
        "realized_10y_yield_change_bps": -35.0,
        "realized_vix_change": 18.5,
        "realized_hy_spread_change_bps": 280.0,
        "trading_halt_occurred": True,
        "emergency_action_followed": True,
    },
    {
        "event_id": "SYNTH_FED_2023_07_26",
        "description": "FOMC press conference. 25bps hike. Powell signals data dependence, less hawkish.",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_date": "2023-07-26T18:30:00+00:00",
        "event_type": "press_conference",
        "is_weekend": False,
        "realized_spx_next_session_return": 0.012,
        "realized_10y_yield_change_bps": -4.0,
        "realized_vix_change": -1.2,
        "realized_hy_spread_change_bps": -8.0,
        "trading_halt_occurred": False,
        "emergency_action_followed": False,
    },
    {
        "event_id": "SYNTH_FED_2024_09_18",
        "description": "Fed cuts rates 50bps. First cut since 2020. Signals easing cycle beginning.",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_date": "2024-09-18T18:30:00+00:00",
        "event_type": "press_conference",
        "is_weekend": False,
        "realized_spx_next_session_return": 0.008,
        "realized_10y_yield_change_bps": -12.0,
        "realized_vix_change": -2.0,
        "realized_hy_spread_change_bps": -12.0,
        "trading_halt_occurred": False,
        "emergency_action_followed": False,
    },
    {
        "event_id": "SYNTH_FED_FRI_2024_08_23",
        "description": "Powell Jackson Hole speech Friday 4:30pm ET. Dovish pivot signal. It's time.",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_date": "2024-08-23T20:30:00+00:00",
        "event_type": "scheduled_post_close",
        "is_weekend": False,
        "realized_spx_next_session_return": 0.023,
        "realized_10y_yield_change_bps": -15.0,
        "realized_vix_change": -3.5,
        "realized_hy_spread_change_bps": -20.0,
        "trading_halt_occurred": False,
        "emergency_action_followed": False,
    },
]


def generate_market_data_df(
    n_days: int = 365,
    end_date: Optional[datetime] = None,
    stress_profile: str = "normal",
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate synthetic daily market data DataFrame.
    stress_profile: "normal" | "stressed" | "crisis"
    """
    rng = np.random.RandomState(seed)
    end = end_date or datetime(2024, 12, 31, tzinfo=timezone.utc)
    dates = [end - timedelta(days=i) for i in range(n_days, 0, -1)]

    stress_level = {"normal": 0.2, "stressed": 0.5, "crisis": 0.85}.get(stress_profile, 0.2)

    vix_base = 15 + stress_level * 25
    hy_base = 320 + stress_level * 450

    records = []
    vix = vix_base
    spx = 4500.0
    y10 = 4.0
    y2 = 4.5

    for dt in dates:
        # Simulate mean-reverting with regime-consistent noise
        vix += rng.normal(0, 1.5) + (vix_base - vix) * 0.05
        vix = max(10, min(80, vix))
        spx_ret = rng.normal(-stress_level * 0.0005, 0.012)
        spx *= (1 + spx_ret)
        y10 += rng.normal(0, 0.04)
        y2 += rng.normal(0, 0.05)
        hy = hy_base + rng.normal(0, 25) + (hy_base - 320) * 0.1
        ig = 80 + stress_level * 80 + rng.normal(0, 5)
        dxy = 100 + stress_level * 8 + rng.normal(0, 0.5)
        gold = 1900 + stress_level * 200 + rng.normal(0, 15)
        adr = max(0.15, min(0.85, 0.55 - stress_level * 0.3 + rng.normal(0, 0.05)))

        records.append({
            "timestamp": dt,
            "spx_level": max(2000, spx),
            "spx_1d_return": spx_ret,
            "spx_5d_return": spx_ret * 3,
            "spx_from_52w_high": min(0, -stress_level * 0.15 + rng.normal(0, 0.02)),
            "nasdaq_level": max(5000, spx * 3.5),
            "nasdaq_1d_return": spx_ret * 1.3,
            "russell_level": max(1000, spx * 0.45),
            "vix": max(10, vix),
            "vix_1m": max(10, vix * 0.98),
            "vix_3m": max(10, vix * 0.95),
            "realized_vol_1m": max(8, vix * 0.9),
            "vol_risk_premium": max(0, vix - vix * 0.9),
            "put_call_ratio": max(0.5, min(1.6, 0.8 + stress_level * 0.3 + rng.normal(0, 0.05))),
            "vvix": max(70, 95 + stress_level * 35 + rng.normal(0, 5)),
            "move_index": max(50, 90 + stress_level * 80 + rng.normal(0, 8)),
            "yield_2y": max(0.01, y2),
            "yield_5y": max(0.01, (y2 + y10) / 2),
            "yield_10y": max(0.01, y10),
            "yield_30y": max(0.01, y10 + 0.3),
            "real_yield_10y": max(-2, y10 - 2.3),
            "breakeven_10y": min(4.0, y10 - (y10 - 2.3)),
            "hy_spread_bps": max(200, hy),
            "ig_spread_bps": max(40, ig),
            "hy_1d_change_bps": rng.normal(0, 8),
            "ig_1d_change_bps": rng.normal(0, 2),
            "bid_ask_spx_bps": max(0.3, 1.2 + stress_level * 4 + rng.normal(0, 0.3)),
            "libor_ois_bps": max(5, 15 + stress_level * 60 + rng.normal(0, 3)),
            "ted_spread_bps": max(5, 20 + stress_level * 70 + rng.normal(0, 5)),
            "liquidity_score": max(10, 80 - stress_level * 55 + rng.normal(0, 3)),
            "dxy_index": max(85, min(115, dxy)),
            "dxy_1d_return": rng.normal(stress_level * 0.0003, 0.004),
            "eurusd": max(0.95, min(1.25, 1.10 - stress_level * 0.05 + rng.normal(0, 0.003))),
            "usdjpy": max(100, min(160, 145 + stress_level * 8 + rng.normal(0, 0.5))),
            "gbpusd": max(1.10, min(1.40, 1.27 - stress_level * 0.05 + rng.normal(0, 0.003))),
            "gold_spot": max(1400, gold),
            "gold_1d_return": rng.normal(stress_level * 0.0005, 0.008),
            "wti_crude": max(30, 75 - stress_level * 18 + rng.normal(0, 2)),
            "oil_1d_return": rng.normal(-stress_level * 0.001, 0.015),
            "advance_decline_ratio": adr,
            "pct_above_200ma": max(10, 65 - stress_level * 40 + rng.normal(0, 3)),
            "pct_above_50ma": max(10, 55 - stress_level * 35 + rng.normal(0, 3)),
            "spx_return": spx_ret,  # Alias for backtest engine
        })

    return pd.DataFrame(records)


def generate_synthetic_events() -> List[Dict]:
    """Return the synthetic event list with proper datetime objects."""
    events = []
    for e in SYNTHETIC_EVENTS:
        ev = dict(e)
        ev["event_date"] = datetime.fromisoformat(ev["event_date"])
        ev["data_validated"] = True
        events.append(ev)
    return events


def save_synthetic_dataset(output_dir: str = "examples/data") -> None:
    """Save synthetic data to disk for use in tests and notebooks."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Market data
    for profile in ["normal", "stressed", "crisis"]:
        df = generate_market_data_df(stress_profile=profile)
        df.to_csv(f"{output_dir}/market_data_{profile}.csv", index=False)
        print(f"Saved {profile} market data: {len(df)} rows")

    # Events
    events = generate_synthetic_events()
    with open(f"{output_dir}/synthetic_events.json", "w") as f:
        json.dump(
            [{k: str(v) if isinstance(v, datetime) else v for k, v in e.items()} for e in events],
            f, indent=2,
        )
    print(f"Saved {len(events)} synthetic events")


if __name__ == "__main__":
    save_synthetic_dataset()
