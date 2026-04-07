#!/usr/bin/env bash
# scripts/run_backtest.sh
# Run a historical backtest over configurable event sets.
# Usage: bash scripts/run_backtest.sh [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--events all_fed]

set -euo pipefail

START_DATE=""
END_DATE=""
EVENT_SET="synthetic"
ENV="research"

while [[ $# -gt 0 ]]; do
    case $1 in
        --start)   START_DATE="$2"; shift 2 ;;
        --end)     END_DATE="$2";   shift 2 ;;
        --events)  EVENT_SET="$2";  shift 2 ;;
        --env)     ENV="$2";        shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo ""
echo "================================="
echo "  MSRE Backtest Run"
echo "  Events:  $EVENT_SET"
echo "  Start:   ${START_DATE:-earliest}"
echo "  End:     ${END_DATE:-latest}"
echo "  Env:     $ENV"
echo "================================="
echo ""

source .venv/bin/activate 2>/dev/null || true

python examples/run_end_to_end.py \
    --env "$ENV" \
    --run-backtest

echo ""
echo "Backtest complete."
