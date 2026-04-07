#!/usr/bin/env python3
"""
scripts/health_check.py

Production health check for the Macro Shock Risk Engine.
Validates all system components: API, databases, data feeds, pipeline.

Usage:
    python scripts/health_check.py --env production
    python scripts/health_check.py --env staging --verbose
    python scripts/health_check.py --component api
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError

# ─── colour codes for terminal output ────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

OK      = f"{GREEN}✓ OK{RESET}"
WARN    = f"{YELLOW}⚠ WARN{RESET}"
FAIL    = f"{RED}✗ FAIL{RESET}"


def check_api(base_url: str, timeout: int = 10) -> Tuple[bool, str]:
    """Check that the MSRE API is reachable and healthy."""
    try:
        req = Request(f"{base_url}/health", headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            if body.get("status") == "healthy":
                return True, f"API healthy | env={body.get('environment')} | pipeline_ready={body.get('pipeline_ready')}"
            return False, f"API returned unexpected status: {body}"
    except URLError as e:
        return False, f"API unreachable: {e}"
    except Exception as e:
        return False, f"API check failed: {e}"


def check_postgres(dsn: Optional[str], timeout: int = 5) -> Tuple[bool, str]:
    """Check PostgreSQL connectivity."""
    if not dsn:
        return None, "POSTGRES_URL not set — skipping"
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(dsn, connect_timeout=timeout)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM macro_events")
        count = cur.fetchone()[0]
        conn.close()
        return True, f"PostgreSQL connected | macro_events rows: {count}"
    except ImportError:
        return None, "psycopg2 not installed — skipping"
    except Exception as e:
        return False, f"PostgreSQL failed: {e}"


def check_timescaledb(dsn: Optional[str], timeout: int = 5) -> Tuple[bool, str]:
    """Check TimescaleDB connectivity and hypertable status."""
    if not dsn:
        return None, "TIMESCALEDB_URL not set — skipping"
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(dsn, connect_timeout=timeout)
        cur = conn.cursor()
        cur.execute("""
            SELECT hypertable_name, num_chunks
            FROM timescaledb_information.hypertables
            WHERE hypertable_name IN ('market_snapshots', 'risk_scores')
        """)
        tables = dict(cur.fetchall())
        conn.close()
        if "market_snapshots" in tables:
            return True, f"TimescaleDB connected | chunks: {tables}"
        return False, "TimescaleDB connected but hypertables missing — run init_timescaledb.sql"
    except ImportError:
        return None, "psycopg2 not installed — skipping"
    except Exception as e:
        return False, f"TimescaleDB failed: {e}"


def check_redis(url: Optional[str], timeout: int = 5) -> Tuple[bool, str]:
    """Check Redis connectivity."""
    if not url:
        return None, "REDIS_URL not set — skipping"
    try:
        import redis  # type: ignore
        r = redis.from_url(url, socket_connect_timeout=timeout)
        pong = r.ping()
        info = r.info("memory")
        used_mb = info.get("used_memory_human", "?")
        return pong, f"Redis connected | memory used: {used_mb}"
    except ImportError:
        return None, "redis-py not installed — skipping"
    except Exception as e:
        return False, f"Redis failed: {e}"


def check_pipeline_import() -> Tuple[bool, str]:
    """Validate that the core pipeline module imports cleanly."""
    try:
        src_path = os.path.join(os.path.dirname(__file__), "..", "python", "src")
        sys.path.insert(0, os.path.abspath(src_path))
        from macro_shock.orchestration.pipeline import MacroShockPipeline  # noqa
        from macro_shock.data_schema.models import CompositeRiskScore      # noqa
        return True, "All core modules import successfully"
    except ImportError as e:
        return False, f"Import failed: {e}"


def check_config(env: str) -> Tuple[bool, str]:
    """Validate that the environment config file exists and is valid YAML."""
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "python", "configs", f"{env}.yaml"
    )
    try:
        import yaml  # type: ignore
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        keys = list(cfg.keys()) if cfg else []
        return True, f"Config loaded | env={env} | keys: {len(keys)}"
    except FileNotFoundError:
        return False, f"Config file not found: {config_path}"
    except ImportError:
        # No PyYAML — just check file exists
        if os.path.exists(config_path):
            return True, f"Config file exists: {config_path}"
        return False, f"Config file not found: {config_path}"
    except Exception as e:
        return False, f"Config invalid: {e}"


def run_checks(env: str, verbose: bool = False, component: Optional[str] = None) -> bool:
    api_url = os.getenv("MSRE_API_URL", "http://localhost:8000")
    pg_url  = os.getenv("POSTGRES_URL")
    ts_url  = os.getenv("TIMESCALEDB_URL")
    rd_url  = os.getenv("REDIS_URL")

    checks = {
        "pipeline_import": ("Core Modules Import", lambda: check_pipeline_import()),
        "config":          ("Config File",          lambda: check_config(env)),
        "api":             ("API Server",            lambda: check_api(api_url)),
        "postgres":        ("PostgreSQL",            lambda: check_postgres(pg_url)),
        "timescaledb":     ("TimescaleDB",           lambda: check_timescaledb(ts_url)),
        "redis":           ("Redis",                 lambda: check_redis(rd_url)),
    }

    if component:
        checks = {k: v for k, v in checks.items() if k == component}

    print(f"\n{BOLD}Macro Shock Risk Engine — Health Check{RESET}")
    print(f"Environment: {env}  |  Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("─" * 65)

    all_ok = True
    results: List[Dict] = []

    for key, (label, check_fn) in checks.items():
        t0 = time.monotonic()
        result, message = check_fn()
        elapsed = (time.monotonic() - t0) * 1000

        if result is True:
            status_str = OK
        elif result is False:
            status_str = FAIL
            all_ok = False
        else:
            status_str = WARN  # None = skipped

        print(f"  {status_str:<25} {label:<25} ({elapsed:.0f}ms)")
        if verbose or result is False:
            print(f"             {message}")

        results.append({"component": key, "ok": result, "message": message, "ms": elapsed})

    print("─" * 65)
    overall = f"{GREEN}ALL CHECKS PASSED{RESET}" if all_ok else f"{RED}SOME CHECKS FAILED{RESET}"
    print(f"  {overall}\n")

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="MSRE Health Check")
    parser.add_argument("--env", default=os.getenv("MSRE_ENVIRONMENT", "research"),
                        choices=["research", "staging", "production"])
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--component", choices=["api", "postgres", "timescaledb", "redis",
                                                  "pipeline_import", "config"])
    args = parser.parse_args()

    ok = run_checks(env=args.env, verbose=args.verbose, component=args.component)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
