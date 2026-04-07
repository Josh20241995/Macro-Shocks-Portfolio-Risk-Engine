#!/usr/bin/env bash
# scripts/setup_env.sh
# One-time environment setup for the Macro Shock Risk Engine.
# Run from the repository root: bash scripts/setup_env.sh

set -euo pipefail

echo ""
echo "=============================================="
echo "  Macro Shock Risk Engine — Environment Setup"
echo "=============================================="
echo ""

# ---------------------------------------------------------------------------
# Python version check
# ---------------------------------------------------------------------------
REQUIRED_PYTHON="3.11"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
MAJOR_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f1,2)

if [ "$MAJOR_MINOR" != "$REQUIRED_PYTHON" ]; then
    echo "WARNING: Python $REQUIRED_PYTHON required, found $PYTHON_VERSION"
    echo "         Consider using pyenv: pyenv install 3.11.x"
fi

echo "Python: $PYTHON_VERSION ✓"

# ---------------------------------------------------------------------------
# Virtual environment
# ---------------------------------------------------------------------------
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "Virtual environment: active ✓"

# ---------------------------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------------------------
echo "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"
echo "Python dependencies installed ✓"

# ---------------------------------------------------------------------------
# Environment file
# ---------------------------------------------------------------------------
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ".env created from .env.example — fill in your values ✓"
else
    echo ".env already exists ✓"
fi

# ---------------------------------------------------------------------------
# C++ build (optional)
# ---------------------------------------------------------------------------
if command -v cmake &> /dev/null && command -v g++ &> /dev/null; then
    echo "Building C++ components..."
    cd cpp
    cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=OFF 2>/dev/null
    cmake --build build --parallel 2>/dev/null && echo "C++ build ✓" || echo "C++ build failed (non-fatal)"
    cd ..
else
    echo "cmake/g++ not found — skipping C++ build (optional)"
fi

# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------
echo "Generating synthetic test datasets..."
python examples/synthetic_data_generator.py 2>/dev/null && echo "Synthetic data generated ✓" || echo "Synthetic data generation skipped"

# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------
echo ""
echo "Running smoke test..."
python examples/run_end_to_end.py --env research --event-scenario hawkish_surprise > /dev/null 2>&1 \
    && echo "Smoke test passed ✓" \
    || echo "Smoke test failed — check logs"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=============================================="
echo "  Setup complete."
echo ""
echo "  Next steps:"
echo "  1. Edit .env with your data feed credentials"
echo "  2. Start local stack: make docker-up"
echo "  3. Run demo: make run-demo"
echo "  4. Run tests: make test-unit"
echo "=============================================="
echo ""
