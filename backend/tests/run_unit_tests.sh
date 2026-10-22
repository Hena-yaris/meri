#!/usr/bin/env bash
# =============================================================================
# Meri: Content Pipeline Backend Unit Test Runner (Milestones 1 & 2)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "============================================================================="
echo "Running Meri Content Pipeline Backend Test Suite"
echo "============================================================================="

cd "${ROOT_DIR}"
python3 -m unittest discover -v -s backend/tests -p "test_*.py"

echo "============================================================================="
echo "All backend tests passed successfully."
echo "============================================================================="
