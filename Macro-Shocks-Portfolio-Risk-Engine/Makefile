# Makefile
# Macro Shock Risk Engine — Developer Commands
# Usage: make <target>

PYTHON      = python
PYTEST      = pytest
PIP         = pip
CMAKE       = cmake
DOTNET      = dotnet
DOCKER      = docker

PYTHON_SRC  = python/src
PYTHON_TESTS= python/tests
CPP_DIR     = cpp
CSHARP_DIR  = csharp

.PHONY: all help install install-dev test test-unit test-integration test-cpp test-csharp \
        build build-cpp build-csharp lint format typecheck clean \
        run-demo run-demo-all run-backtest generate-synthetic docker-up docker-down

# ---------------------------------------------------------------------------
help:
	@echo "Macro Shock Risk Engine — Make Targets"
	@echo ""
	@echo "  Setup:"
	@echo "    install          Install Python runtime dependencies"
	@echo "    install-dev      Install all dev dependencies"
	@echo "    build            Build all components (Python + C++ + C#)"
	@echo "    build-cpp        Build C++ components only"
	@echo "    build-csharp     Build C# dashboard only"
	@echo ""
	@echo "  Testing:"
	@echo "    test             Run all tests (unit + integration + C++)"
	@echo "    test-unit        Run Python unit tests only"
	@echo "    test-integration Run integration tests (needs docker-up)"
	@echo "    test-cpp         Run C++ tests"
	@echo "    test-csharp      Run C# tests"
	@echo ""
	@echo "  Code Quality:"
	@echo "    lint             Run ruff linter"
	@echo "    format           Run black formatter"
	@echo "    typecheck        Run mypy type checking"
	@echo ""
	@echo "  Run:"
	@echo "    run-demo                Run weekend_crisis scenario demo"
	@echo "    run-demo-all            Run all scenario demos"
	@echo "    run-backtest            Run backtest over synthetic events"
	@echo "    generate-synthetic      Generate synthetic test datasets"
	@echo ""
	@echo "  Infrastructure:"
	@echo "    docker-up        Start local data stack (DB, Redis, ES)"
	@echo "    docker-down      Stop local data stack"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

install:
	$(PIP) install -e "."

install-dev:
	$(PIP) install -e ".[all]"

build: build-cpp build-csharp
	@echo "All components built."

build-cpp:
	@echo "Building C++ components..."
	cd $(CPP_DIR) && $(CMAKE) -B build -DCMAKE_BUILD_TYPE=Release && $(CMAKE) --build build --parallel
	@echo "C++ build complete."

build-csharp:
	@echo "Building C# dashboard..."
	cd $(CSHARP_DIR) && $(DOTNET) build --configuration Release
	@echo "C# build complete."

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: test-unit test-cpp test-csharp
	@echo "All tests complete."

test-unit:
	@echo "Running Python unit tests..."
	$(PYTEST) $(PYTHON_TESTS)/unit/ -v --cov=macro_shock --cov-report=term-missing --cov-fail-under=80

test-integration:
	@echo "Running Python integration tests (requires docker-up)..."
	$(PYTEST) $(PYTHON_TESTS)/integration/ -v -m integration

test-cpp:
	@echo "Running C++ tests..."
	@if [ -d "$(CPP_DIR)/build" ]; then \
		cd $(CPP_DIR)/build && ctest --output-on-failure; \
	else \
		echo "C++ not built. Run: make build-cpp"; \
	fi

test-csharp:
	@echo "Running C# tests..."
	cd $(CSHARP_DIR) && $(DOTNET) test --verbosity normal

coverage:
	$(PYTEST) $(PYTHON_TESTS)/unit/ -v \
		--cov=macro_shock \
		--cov-report=html:coverage_report \
		--cov-report=term-missing
	@echo "Coverage report: coverage_report/index.html"

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------

lint:
	ruff check $(PYTHON_SRC) $(PYTHON_TESTS) examples/

format:
	black $(PYTHON_SRC) $(PYTHON_TESTS) examples/
	isort $(PYTHON_SRC) $(PYTHON_TESTS) examples/

format-check:
	black --check $(PYTHON_SRC) $(PYTHON_TESTS) examples/
	isort --check $(PYTHON_SRC) $(PYTHON_TESTS) examples/

typecheck:
	mypy $(PYTHON_SRC) --ignore-missing-imports

ci: format-check lint typecheck test-unit
	@echo "CI checks passed."

# ---------------------------------------------------------------------------
# Run Examples
# ---------------------------------------------------------------------------

run-demo:
	$(PYTHON) examples/run_end_to_end.py --env research --event-scenario weekend_crisis

run-demo-hawkish:
	$(PYTHON) examples/run_end_to_end.py --env research --event-scenario hawkish_surprise

run-demo-dovish:
	$(PYTHON) examples/run_end_to_end.py --env research --event-scenario dovish_pivot

run-demo-all:
	$(PYTHON) examples/run_end_to_end.py --env research --run-all-scenarios

run-backtest:
	$(PYTHON) examples/run_end_to_end.py --env research --run-backtest

generate-synthetic:
	$(PYTHON) examples/synthetic_data_generator.py
	@echo "Synthetic data written to examples/data/"

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

docker-up:
	$(DOCKER) compose up -d
	@echo "Waiting for services to be ready..."
	sleep 5
	@echo "Local stack running. Connect at:"
	@echo "  TimescaleDB: localhost:5432"
	@echo "  Redis:       localhost:6379"
	@echo "  Elasticsearch: localhost:9200"

docker-down:
	$(DOCKER) compose down

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf coverage_report/ .coverage htmlcov/
	rm -rf $(CPP_DIR)/build/
	cd $(CSHARP_DIR) && $(DOTNET) clean 2>/dev/null || true
	@echo "Clean complete."
