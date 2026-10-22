# Database Foundation Verification & Deployment Guide

## 1. Executive Summary & Verification Status

Milestone 4B verifies and hardens the Supabase/PostgreSQL database migration ([`backend/migrations/20261020000001_content_pipeline_foundation.sql`](../../backend/migrations/20261020000001_content_pipeline_foundation.sql)).

### 1.1 Test Execution Truth Matrix

| Test Suite / Check | Environment | Execution Status | Actual Result |
| :--- | :--- | :--- | :--- |
| **Migration Syntax & Structure** | PostgreSQL 15.18 (Alpine Container) | **EXECUTED LIVE** | Clean execution of all extensions, tables, generated columns, indexes, RLS, and RPCs with 0 errors. |
| **Duplicate Video ID Rejection** | PostgreSQL 15.18 (Alpine Container) | **EXECUTED LIVE** | `unique_violation` caught and verified. |
| **Timestamp Boundary Checks** | PostgreSQL 15.18 (Alpine Container) | **EXECUTED LIVE** | `check_violation` caught on negative `start_ms` and `end_ms < start_ms`. |
| **Evidence Foreign Key & RESTRICT**| PostgreSQL 15.18 (Alpine Container) | **EXECUTED LIVE** | `foreign_key_violation` caught on invalid segment, deletion restricted on active evidence. |
| **Draft & Unverified Denial** | PostgreSQL 15.18 (Alpine Container, `anon` role) | **EXECUTED LIVE** | Public `anon` role returned 0 draft episodes and 0 candidate insights. |
| **Unauthorized Publication Denial** | PostgreSQL 15.18 (Alpine Container, `anon` role) | **EXECUTED LIVE** | `insufficient_privilege` / `Access denied` exception raised. |
| **Valid Atomic Publication** | PostgreSQL 15.18 (Alpine Container, Admin) | **EXECUTED LIVE** | Episode atomically transitioned to `published` with `published_at` set. |
| **Publication Idempotency** | PostgreSQL 15.18 (Alpine Container, Admin) | **EXECUTED LIVE** | Repeated call safely returned idempotent status without side-effects. |
| **Atomic Rollback on Missing Evidence** | PostgreSQL 15.18 (Alpine Container) | **EXECUTED LIVE** | Exception raised, transaction rolled back, episode retained `draft` status. |
| **Dart Static Schema & Model Parity**| Flutter SDK 3.x / Dart Test Runner | **EXECUTED LIVE** | 94/94 tests passed (`flutter test`). |
| **Dart Static Analysis** | Flutter SDK 3.x (`flutter analyze`) | **EXECUTED LIVE** | `No issues found!`. |
| **Live Supabase Cloud Project** | Supabase Cloud Hosted Instance | **NOT CONNECTED** | Remote Supabase credentials were not configured in this environment; tests were executed in an isolated local PostgreSQL 15 container. |

---

## 2. Issues Identified & Corrective Actions Applied

During initial inspection and clean-database execution, five critical Supabase/PostgreSQL compatibility issues were identified and resolved:

### 2.1 Issue 1: Missing Role Bootstrapping in Clean / Local Environments
- **Problem**: Running the migration on clean PostgreSQL or non-Supabase CI failed immediately with:
  `ERROR: role "anon" does not exist` and `ERROR: role "authenticated" does not exist`.
- **Fix**: Added dynamic role bootstrapping:
  ```sql
  DO $$ BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
          CREATE ROLE anon NOLOGIN;
      END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
          CREATE ROLE authenticated NOLOGIN;
      END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
          CREATE ROLE service_role NOLOGIN;
      END IF;
  END $$;
  ```

### 2.2 Issue 2: Standalone `auth` Schema & `auth.jwt()` Portability
- **Problem**: Policies referencing `auth.jwt()` fail on vanilla PostgreSQL instances if the Supabase GoTrue `auth` schema is absent.
- **Fix**: Created stubs for `auth.jwt()` and `auth.uid()` reading from PostgREST session claims (`request.jwt.claims`), guaranteeing complete portability.

### 2.3 Issue 3: Missing Grants (RLS Enabled Without Table Grants)
- **Problem**: In PostgreSQL, enabling RLS without granting table usage causes `permission denied for table ...` errors for `anon` and `authenticated` before RLS policies can even evaluate.
- **Fix**: Implemented explicit access grants:
  ```sql
  GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
  GRANT SELECT ON episodes, guests, insights, quotations TO anon, authenticated;
  GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
  REVOKE ALL ON processing_jobs, transcript_segments, transcript_chunks, extraction_runs, insight_evidence FROM anon, PUBLIC;
  ```

### 2.4 Issue 4: `SECURITY DEFINER` Search Path & Authorization
- **Problem**: `publish_episode` lacked `SET search_path = public, auth, pg_temp`, creating vulnerability to search-path hijacking. Furthermore, unprivileged callers were not explicitly checked.
- **Fix**: Added `SET search_path`, verified caller credentials against admin claims or service-role, and explicitly revoked execution permissions from `PUBLIC` and `anon`.

### 2.5 Issue 5: Rigid Quotation Publication Rule
- **Problem**: Requiring $\ge 1$ verified quotation hardcoded into the publication RPC blocked valid insight-driven episodes (e.g., technical operational walkthroughs).
- **Decision & Fix**: Made quotation requirements configurable:
  - `p_min_insights INT DEFAULT 1`: Meri strictly enforces $\ge 1$ verified insight with evidence.
  - `p_require_quotations BOOLEAN DEFAULT FALSE`: Configurable flag for quote requirements.
  - `p_min_quotations INT DEFAULT 0`: Number of quotes required when enforced.
  - Rationale: While Meri emphasizes authentic Amharic dialogue, some formats focus primarily on operational models or business milestones. Making quotations configurable gives editors flexibility without sacrificing insight evidence integrity.

---

## 3. How to Execute Verification Tests Locally

### Option A: Using the Automated Runner Script
The repository includes an automated test runner script that executes the complete test suite against a clean temporary database:

```bash
# Run against local PostgreSQL or active Docker container
./backend/tests/run_db_tests.sh
```

### Option B: Using a Dedicated Docker Container
```bash
# 1. Spin up an isolated PostgreSQL 15 container
docker run -d --name meri_postgres_test \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:15-alpine

# 2. Execute the verification runner specifying the container
CONTAINER_NAME=meri_postgres_test ./backend/tests/run_db_tests.sh

# 3. Teardown container
docker stop meri_postgres_test && docker rm meri_postgres_test
```

### Option C: Manual `psql` Execution
```bash
# 1. Create a clean test database
psql -U postgres -c "CREATE DATABASE meri_test_db;"

# 2. Apply migration
psql -U postgres -d meri_test_db -f backend/migrations/20261020000001_content_pipeline_foundation.sql

# 3. Run verification test suite
psql -U postgres -d meri_test_db -f backend/tests/verify_database_foundation.sql

# 4. Clean up
psql -U postgres -c "DROP DATABASE meri_test_db;"
```

---

## 4. Deploying to Remote Supabase Environment

When deploying to a Supabase project via the Supabase CLI:

```bash
# 1. Authenticate with Supabase
npx supabase login

# 2. Link your local project to your remote Supabase project
npx supabase link --project-ref <YOUR_SUPABASE_PROJECT_REF>

# 3. Push migrations to the remote database
npx supabase db push

# 4. Run verification tests against the staging/remote database (Read-only or test project)
psql "$SUPABASE_DB_URL" -f backend/tests/verify_database_foundation.sql
```

> [!SECURITY NOTE]
> Never store the Supabase DB URL, Service Role Secret, or JWT tokens in the repository or within Flutter source files. All administrative access must be restricted to backend workers and deployment pipelines via environment secrets.
