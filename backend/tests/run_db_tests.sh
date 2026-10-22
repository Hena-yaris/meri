#!/usr/bin/env bash
# =============================================================================
# Meri: Content Pipeline Database Foundation Test Runner (Milestone 4B)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MIGRATIONS_DIR="${ROOT_DIR}/supabase/migrations"
BOOTSTRAP_FILE="${ROOT_DIR}/backend/tests/local_test_bootstrap.sql"
TEST_SQL_FILE="${ROOT_DIR}/backend/tests/verify_database_foundation.sql"
TEST_M3_SQL_FILE="${ROOT_DIR}/backend/tests/verify_milestone3_boundaries.sql"

# Configuration defaults
CONTAINER_NAME="${CONTAINER_NAME:-leyu_postgres}"
DB_USER="${DB_USER:-postgres}"
TEMP_DB="meri_verification_$(date +%s)"

echo "============================================================================="
echo "Meri Database Foundation: Automated Verification Runner"
echo "============================================================================="

# 1. Determine execution mode (Direct psql or Docker container)
EXEC_MODE=""
if command -v psql >/dev/null 2>&1 && psql -U "${DB_USER}" -c '\q' >/dev/null 2>&1; then
    EXEC_MODE="local_psql"
    echo "[INFO] Detected local PostgreSQL instance via 'psql'."
elif command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    EXEC_MODE="docker"
    echo "[INFO] Detected running PostgreSQL Docker container: '${CONTAINER_NAME}'."
else
    echo "[WARN] No active PostgreSQL or Docker container '${CONTAINER_NAME}' reachable."
    echo ""
    echo "To run these verification tests against Supabase or Docker:"
    echo "  1. Using Docker:"
    echo "     docker run -d --name meri_postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15-alpine"
    echo "     CONTAINER_NAME=meri_postgres ./backend/tests/run_db_tests.sh"
    echo ""
    echo "  2. Using Supabase CLI:"
    echo "     npx supabase db push"
    echo "     psql \$DATABASE_URL -f backend/tests/verify_database_foundation.sql"
    exit 0
fi

# Function to execute SQL against a specific database
run_sql_cmd() {
    local target_db="$1"
    local sql_file="$2"

    if [ "${EXEC_MODE}" = "docker" ]; then
        docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${target_db}" < "${sql_file}"
    else
        psql -U "${DB_USER}" -d "${target_db}" -f "${sql_file}"
    fi
}

run_raw_cmd() {
    local cmd="$1"
    if [ "${EXEC_MODE}" = "docker" ]; then
        docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -c "${cmd}"
    else
        psql -U "${DB_USER}" -c "${cmd}"
    fi
}

# Cleanup hook on script exit
cleanup() {
    echo "[INFO] Cleaning up temporary test database '${TEMP_DB}'..."
    run_raw_cmd "DROP DATABASE IF EXISTS ${TEMP_DB};" >/dev/null 2>&1 || true
    echo "[INFO] Cleanup completed."
}
trap cleanup EXIT

echo "[1/4] Creating clean isolated test database: ${TEMP_DB}..."
run_raw_cmd "CREATE DATABASE ${TEMP_DB};"

echo "[2/4] Bootstrapping local test roles & auth stubs (Docker only)..."
run_sql_cmd "${TEMP_DB}" "${BOOTSTRAP_FILE}" >/dev/null

echo "[3/4] Applying Supabase migrations in order..."
for mig in $(ls "${MIGRATIONS_DIR}"/*.sql | sort); do
    echo "       Applying: $(basename "${mig}")..."
    run_sql_cmd "${TEMP_DB}" "${mig}" >/dev/null
done

echo "[4/4] Running Database Verification Test Suites..."
echo "       Suite 1: Foundation Verification (9 tests)..."
run_sql_cmd "${TEMP_DB}" "${TEST_SQL_FILE}"

echo "       Suite 2: Milestone 3 Boundaries & Provenance (11 tests)..."
run_sql_cmd "${TEMP_DB}" "${TEST_M3_SQL_FILE}"

echo "============================================================================="
echo "Verification run completed successfully."
echo "============================================================================="
