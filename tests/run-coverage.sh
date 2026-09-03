#!/usr/bin/env bash
# ============================================================================
# SOGo 6 backend coverage gate (introduced Round 17).
#
# Runs the same unit suite as CI (.github/workflows/test.yml) under coverage.py
# and then enforces the `fail_under` floor declared in
# [tool.coverage.report] of pyproject.toml (66% as of the round-17 baseline).
#
# Usage:
#   tests/run-coverage.sh            # full unit suite + report + gate
#   tests/run-coverage.sh -k tmp     # filter (passes extra args to pytest)
#
# Exit codes: 0 gate green, 1 coverage below floor OR test failures,
#             2 coverage.py missing.
# ============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python3}
if ! "$PY" -c "import coverage" >/dev/null 2>&1; then
    echo "coverage.py is not installed; run: pip install 'coverage>=7' 'pytest-cov>=5'" >&2
    exit 2
fi

rm -f .coverage
"$PY" -m coverage run --source=app -m pytest tests/ \
    --ignore=tests/integration --ignore=tests/test_integration \
    --ignore=tests/test_properties -q --tb=line --maxfail=10 "$@"
PYTEST_STATUS=$?

# Always render the report (even when env-flaky tests fail) so the totals are
# visible; `coverage report` exits non-zero when fail_under is breached.
"$PY" -m coverage report
COV_STATUS=$?

if [ "$PYTEST_STATUS" -ne 0 ]; then
    echo "pytest exited with status $PYTEST_STATUS (failures above)" >&2
fi
if [ "$PYTEST_STATUS" -ne 0 ]; then
    exit 1
fi
exit "$COV_STATUS"
