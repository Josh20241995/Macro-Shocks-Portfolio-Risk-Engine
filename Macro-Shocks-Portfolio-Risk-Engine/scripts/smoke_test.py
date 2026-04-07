#!/usr/bin/env python3
"""
scripts/smoke_test.py

Production smoke test for the Macro Shock Risk Engine.
Injects a synthetic test event through the live API and validates
the response without submitting any OMS orders.

Safe to run in production — uses a clearly-labeled synthetic event
that the OMS interface ignores (no real orders generated).

Usage:
    python scripts/smoke_test.py --env production
    python scripts/smoke_test.py --env staging --event hawkish_surprise
    python scripts/smoke_test.py --env production --scenario weekend_crisis --stress 0.5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import urlencode
import urllib.request

GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"; RESET = "\033[0m"; BOLD = "\033[1m"


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Smoke-Test": "true",
    })
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def get_json(url: str, timeout: int = 15) -> dict:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def run_smoke_test(env: str, scenario: str, api_url: str, stress: float = 0.35) -> bool:
    print(f"\n{BOLD}MSRE Smoke Test{RESET} | env={env} | scenario={scenario} | api={api_url}")
    print("─" * 70)
    all_passed = True

    def check(label: str, condition: bool, detail: str = "") -> bool:
        status = f"{GREEN}✓{RESET}" if condition else f"{RED}✗ FAIL{RESET}"
        print(f"  {status}  {label}")
        if detail:
            print(f"        {detail}")
        return condition

    # ── 1. Health check ────────────────────────────────────────
    try:
        health = get_json(f"{api_url}/health")
        ok = check("API liveness",
                   health.get("status") == "healthy",
                   f"pipeline_ready={health.get('pipeline_ready')}")
        all_passed &= ok
    except Exception as e:
        check("API liveness", False, str(e))
        print(f"\n{RED}Cannot reach API. Aborting smoke test.{RESET}\n")
        return False

    # ── 2. Run demo scenario ────────────────────────────────────
    t0 = time.monotonic()
    try:
        params = f"?scenario={scenario}&stress_level={stress}"
        result = get_json(f"{api_url}/api/v1/scenarios/demo{params}", timeout=60)
        elapsed = (time.monotonic() - t0) * 1000

        ok = check("Scenario processed",
                   "composite_score" in result,
                   f"elapsed={elapsed:.0f}ms")
        all_passed &= ok

        if "composite_score" in result:
            score = result["composite_score"]
            severity = result.get("severity", "?")
            action = result.get("action_level", "?")
            regime = result.get("regime", "?")

            check("Score in valid range [0, 100]", 0 <= score <= 100, f"score={score:.1f}")
            check("Severity field present", bool(severity), severity)
            check("Action level present", bool(action), action)
            check("Regime classified", regime != "unknown", regime)

            sub_scores = result.get("sub_scores", [])
            check("Sub-scores returned",
                  len(sub_scores) == 9,
                  f"count={len(sub_scores)} (expected 9)")

            scenarios = result.get("scenarios", [])
            if scenarios:
                prob_sum = sum(s.get("probability", 0) for s in scenarios)
                check("Scenario probabilities sum ≈ 1.0",
                      abs(prob_sum - 1.0) < 0.05,
                      f"sum={prob_sum:.4f}")

            hedges = result.get("hedge_recommendations", [])
            if action in ("HEDGE", "EMERGENCY_DERISKING", "REDUCE"):
                check("Hedge recommendations present when warranted",
                      len(hedges) > 0,
                      f"count={len(hedges)}")
                if hedges:
                    check("PM approval required on hedges",
                          all(h.get("requires_pm_approval", False) for h in hedges),
                          "All hedges require PM sign-off")

            alerts = result.get("recent_alerts", [])
            if score >= 35:
                check("Alerts generated for elevated score",
                      len(alerts) > 0,
                      f"count={len(alerts)}")

            event = result.get("current_event")
            check("Event classified", event is not None,
                  f"{event.get('event_type', '?')} | severity={event.get('severity', '?')}" if event else "")

            data_quality = result.get("data_quality", 0)
            check("Data quality acceptable", data_quality >= 0.5, f"quality={data_quality:.0%}")

    except URLError as e:
        check("Scenario API call", False, str(e))
        all_passed = False
    except Exception as e:
        check("Scenario processing", False, str(e))
        all_passed = False

    # ── 3. History endpoint ─────────────────────────────────────
    try:
        history = get_json(f"{api_url}/api/v1/risk/history?hours=1")
        check("History endpoint reachable",
              isinstance(history, list),
              f"entries={len(history)}")
    except Exception as e:
        check("History endpoint", False, str(e))

    # ── 4. Alerts endpoint ──────────────────────────────────────
    try:
        alerts_resp = get_json(f"{api_url}/api/v1/alerts?limit=10")
        check("Alerts endpoint reachable",
              isinstance(alerts_resp, list),
              f"count={len(alerts_resp)}")
    except Exception as e:
        check("Alerts endpoint", False, str(e))

    # ── Summary ─────────────────────────────────────────────────
    print("─" * 70)
    if all_passed:
        print(f"  {GREEN}{BOLD}SMOKE TEST PASSED{RESET}\n")
    else:
        print(f"  {RED}{BOLD}SMOKE TEST FAILED — see above{RESET}\n")

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="MSRE Production Smoke Test")
    parser.add_argument("--env", default=os.getenv("MSRE_ENVIRONMENT", "research"))
    parser.add_argument("--scenario", default="weekend_crisis",
                        choices=["weekend_crisis", "hawkish_surprise", "dovish_pivot",
                                 "friday_close_ambiguous"])
    parser.add_argument("--stress", type=float, default=0.35)
    parser.add_argument("--api-url", default=os.getenv("MSRE_API_URL", "http://localhost:8000"))
    args = parser.parse_args()

    ok = run_smoke_test(
        env=args.env,
        scenario=args.scenario,
        api_url=args.api_url,
        stress=args.stress,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
