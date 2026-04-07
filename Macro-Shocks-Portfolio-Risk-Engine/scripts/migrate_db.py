#!/usr/bin/env python3
"""
scripts/migrate_db.py

Database migration manager for the Macro Shock Risk Engine.
Tracks applied migrations and applies pending ones in order.

Usage:
    python scripts/migrate_db.py --env staging --apply
    python scripts/migrate_db.py --env production --apply --version 1.0.0
    python scripts/migrate_db.py --env production --verify
    python scripts/migrate_db.py --env production --status
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


# ─── Migration definitions (ordered) ─────────────────────────
MIGRATIONS = [
    {
        "id": "001_init_timescaledb",
        "description": "Initialize TimescaleDB hypertables",
        "file": "scripts/init_timescaledb.sql",
        "db": "timescaledb",
        "required": True,
    },
    {
        "id": "002_init_postgres",
        "description": "Initialize PostgreSQL metadata schema",
        "file": "scripts/init_postgres.sql",
        "db": "postgres",
        "required": True,
    },
]


def sha256_file(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def get_connection(db: str, env: str):
    """Get database connection based on db type and environment."""
    try:
        import psycopg2  # type: ignore
    except ImportError:
        print("  psycopg2 not installed — cannot apply migrations")
        print("  Install with: pip install psycopg2-binary")
        return None

    if db == "timescaledb":
        dsn = os.getenv("TIMESCALEDB_URL", "postgresql://msre:msre_dev_password@localhost:5432/market_data")
    else:
        dsn = os.getenv("POSTGRES_URL", "postgresql://msre:msre_dev_password@localhost:5433/msre_meta")

    try:
        return psycopg2.connect(dsn)
    except Exception as e:
        print(f"  Connection failed for {db}: {e}")
        return None


def ensure_migration_table(conn) -> None:
    """Create the migration tracking table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_id    TEXT        PRIMARY KEY,
                description     TEXT,
                applied_at      TIMESTAMPTZ DEFAULT NOW(),
                applied_by      TEXT,
                checksum        TEXT,
                version         TEXT
            )
        """)
    conn.commit()


def is_applied(conn, migration_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM schema_migrations WHERE migration_id = %s", (migration_id,))
        return cur.fetchone() is not None


def apply_migration(conn, migration: dict, version: str, dry_run: bool = False) -> bool:
    path = migration["file"]
    if not Path(path).exists():
        print(f"  WARNING: Migration file not found: {path}")
        return False

    sql = Path(path).read_text()
    checksum = sha256_file(path)

    if dry_run:
        print(f"  [DRY-RUN] Would apply: {migration['id']} from {path}")
        return True

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                """INSERT INTO schema_migrations
                   (migration_id, description, applied_by, checksum, version)
                   VALUES (%s, %s, %s, %s, %s)""",
                (migration["id"], migration["description"],
                 os.getenv("USER", "deploy"), checksum, version),
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ERROR applying {migration['id']}: {e}")
        return False


def run_apply(env: str, version: str, dry_run: bool) -> bool:
    print(f"\nApplying migrations | env={env} | version={version}")
    print("─" * 50)

    all_ok = True
    for migration in MIGRATIONS:
        db = migration["db"]
        conn = get_connection(db, env)
        if conn is None:
            if migration["required"] and not dry_run:
                all_ok = False
            print(f"  SKIP  {migration['id']} (no connection)")
            continue

        ensure_migration_table(conn)

        if is_applied(conn, migration["id"]):
            print(f"  ✓ ALREADY APPLIED  {migration['id']}")
        else:
            print(f"  → APPLYING  {migration['id']}: {migration['description']}")
            ok = apply_migration(conn, migration, version, dry_run)
            if ok:
                print(f"    ✓ Applied successfully")
            else:
                print(f"    ✗ FAILED")
                all_ok = False
                if migration["required"]:
                    break

        conn.close()

    status = "COMPLETE" if all_ok else "FAILED"
    print(f"\nMigration {status}")
    return all_ok


def run_status(env: str) -> None:
    print(f"\nMigration status | env={env}")
    print("─" * 50)
    for migration in MIGRATIONS:
        conn = get_connection(migration["db"], env)
        if conn is None:
            print(f"  UNKNOWN  {migration['id']} (no connection)")
            continue
        try:
            ensure_migration_table(conn)
            applied = is_applied(conn, migration["id"])
            status = "✓ APPLIED " if applied else "  PENDING"
            print(f"  {status}  {migration['id']}: {migration['description']}")
        finally:
            conn.close()


def run_verify(env: str) -> bool:
    print(f"\nVerifying migrations | env={env}")
    all_ok = True
    for migration in MIGRATIONS:
        conn = get_connection(migration["db"], env)
        if conn is None:
            if migration["required"]:
                print(f"  ✗  {migration['id']}: cannot connect")
                all_ok = False
            continue
        try:
            ensure_migration_table(conn)
            if not is_applied(conn, migration["id"]) and migration["required"]:
                print(f"  ✗  {migration['id']}: NOT APPLIED (required)")
                all_ok = False
            else:
                print(f"  ✓  {migration['id']}")
        finally:
            conn.close()
    print(f"\nVerification: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="MSRE Database Migration Manager")
    parser.add_argument("--env", default=os.getenv("MSRE_ENVIRONMENT", "research"))
    parser.add_argument("--apply",   action="store_true")
    parser.add_argument("--verify",  action="store_true")
    parser.add_argument("--status",  action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--version", default="0.0.0")
    args = parser.parse_args()

    ok = True
    if args.apply:
        ok = run_apply(args.env, args.version, args.dry_run)
    elif args.verify:
        ok = run_verify(args.env)
    else:
        run_status(args.env)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
