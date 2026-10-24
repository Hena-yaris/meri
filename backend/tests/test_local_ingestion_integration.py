"""
Meri Content Pipeline: Milestone 5.3.3 Local Ingestion Integration Test Suite.

Deterministic local integration test that exercises the actual JobWorker,
PipelineOrchestrator, and CandidatePersistenceService against a disposable local
PostgreSQL database running in Docker container 'leyu_postgres', with Gemini transport
mocked deterministically and zero external network access.

Test Scenarios Covered:
1. Positive End-to-End Ingestion:
   - Full worker lifecycle: atomic claim, preflight, transcript acquisition, in-memory AI extraction,
     atomic candidate persistence, and stage updates to human_review.
   - Comprehensive schema validation: processing_jobs, episodes (remains draft), transcript_segments,
     transcript_chunks, extraction_runs, insights, quotations, insight_evidence, and quotation_segments.
   - Verified relational provenance and foreign-key integrity.
   - Isolation check: asserts zero writes to unrelated episodes or jobs.
2. Operator Confirmation Safety:
   - Rejection of missing or whitespace-only confirmation before Gemini transport invocation.
3. Video ID Integrity Safety:
   - Rejection of mismatched YouTube video ID before Gemini transport invocation.
4. Editorial Protection & Rollback Safety:
   - Rejection of rerun against episodes containing verified editorial approvals.
   - Immediate transaction rollback preserving pre-existing verified content intact.
5. Published Episode Protection:
   - Rejection of rerun against published episodes.
6. Disposable Database Lifecycle & Isolation:
   - Creation, migration, and strict isolation of disposable test database.
   - Cleanup trap drops only the disposable test database, leaving pre-existing databases untouched.
7. Adapter Transaction Rollback & Type Preservation:
   - Manual-commit transaction rollback and commit semantics.
   - Session recovery and error surfacing.
   - Strict data type preservation (integers, floats, booleans, nulls, dicts, lists).
"""

import json
import logging
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
import unittest
import urllib.request
import uuid

from backend.src.candidate_persistence import CandidatePersistenceService
from backend.src.extraction_models import ValidationStatus
from backend.src.gemini_client import GeminiClient, GeminiConfig
from backend.src.job_worker import JobWorker, JobWorkerResult, StaticTranscriptProvider
from backend.src.pipeline_orchestrator import EditorialProtectionError, PipelineOrchestrator
from backend.tests.test_pipeline_orchestrator import create_sample_gemini_response_payload

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = ROOT_DIR / "supabase" / "migrations"
BOOTSTRAP_FILE = ROOT_DIR / "backend" / "tests" / "local_test_bootstrap.sql"
FIXTURE_PATH = ROOT_DIR / "backend" / "tests" / "fixtures" / "sample_transcript.json"

CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "leyu_postgres")
DB_USER = os.environ.get("DB_USER", "postgres")
DISPOSABLE_DB_PREFIX = "meri_integ_"


# =============================================================================
# PEP 249 DB-API 2.0 Local Connection Adapter for Docker PostgreSQL
# =============================================================================

def _format_param(param: Any) -> str:
    """Safely formats a parameter for PostgreSQL SQL query injection."""
    if param is None:
        return "NULL"
    elif isinstance(param, bool):
        return "TRUE" if param else "FALSE"
    elif isinstance(param, (int, float)):
        return str(param)
    elif isinstance(param, (list, tuple)):
        if len(param) == 0:
            return "ARRAY[]::text[]"
        escaped_items = [_format_param(item) for item in param]
        return f"ARRAY[{', '.join(escaped_items)}]"
    elif isinstance(param, dict):
        json_str = json.dumps(param)
        escaped = json_str.replace("'", "''")
        return f"'{escaped}'::jsonb"
    elif isinstance(param, str):
        escaped = param.replace("'", "''")
        return f"'{escaped}'"
    else:
        escaped = str(param).replace("'", "''")
        return f"'{escaped}'"


def _format_sql(sql: str, params: Optional[Sequence[Any]] = None) -> str:
    """Substitutes %s placeholders with safely escaped literals."""
    if not params:
        return sql.replace("%%", "%")
    parts = sql.split("%s")
    if len(parts) - 1 != len(params):
        raise ValueError(
            f"Parameter count mismatch: query has {len(parts)-1} placeholders, but {len(params)} params provided."
        )
    formatted_parts = [parts[0]]
    for idx, p in enumerate(params):
        formatted_parts.append(_format_param(p))
        formatted_parts.append(parts[idx + 1])
    return "".join(formatted_parts).replace("%%", "%")


class LocalPsqlCursor:
    """
    Focused cursor wrapping interactive psql in Docker.

    Specialized for the queries and DB-API operations used by JobWorker,
    PipelineOrchestrator, and CandidatePersistenceService. Preserves exact
    schema types (integers, booleans, floats, nulls, dicts) via row_to_json.
    """

    def __init__(self, connection: "LocalPsqlConnection") -> None:
        self.connection = connection
        self._rows: List[Tuple[Any, ...]] = []
        self._row_idx: int = 0
        self._closed: bool = False
        self.rowcount: int = -1

    def execute(self, query: str, params: Optional[Sequence[Any]] = None) -> "LocalPsqlCursor":
        if self._closed or self.connection._closed:
            raise RuntimeError("Cannot execute query on closed cursor or connection.")

        formatted_sql = _format_sql(query, params).strip()
        clean = formatted_sql.rstrip(";\n\t ")
        norm = " ".join(clean.split()).upper()

        if norm in ("BEGIN", "BEGIN TRANSACTION"):
            self.connection._in_transaction = True
            return self
        elif norm in ("COMMIT", "COMMIT TRANSACTION"):
            self.connection.commit()
            return self
        elif norm in ("ROLLBACK", "ROLLBACK TRANSACTION"):
            self.connection.rollback()
            return self

        # Begin transaction automatically if not already active (PEP 249 default manual-commit mode)
        if not self.connection._in_transaction:
            self.connection._send_command("BEGIN;")
            self.connection._in_transaction = True

        is_returning = "RETURNING" in norm
        is_select = norm.startswith("SELECT")
        is_with = norm.startswith("WITH")

        # Use PostgreSQL row_to_json to preserve exact data types (integers, strings, booleans, nulls)
        if is_returning:
            wrapped = f"WITH __q AS ({clean}) SELECT row_to_json(__q) FROM __q;"
        elif is_select or (is_with and "SELECT" in norm):
            wrapped = f"SELECT row_to_json(__q) FROM ({clean}) __q;"
        else:
            wrapped = f"{clean};"

        raw_lines = self.connection._send_command(wrapped)
        full_text = "".join(raw_lines)
        if "ERROR:" in full_text or "FATAL:" in full_text:
            err_lines = [l.strip() for l in full_text.splitlines() if "ERROR:" in l or "FATAL:" in l]
            raise RuntimeError("\n".join(err_lines) if err_lines else full_text.strip())

        parsed_rows: List[Tuple[Any, ...]] = []
        for line in raw_lines:
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    obj = json.loads(line_str)
                    parsed_rows.append(tuple(obj.values()))
                except Exception:
                    pass

        self._rows = parsed_rows
        self._row_idx = 0
        self.rowcount = len(parsed_rows)
        return self

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if self._closed:
            raise RuntimeError("Cursor is closed.")
        if self._row_idx < len(self._rows):
            row = self._rows[self._row_idx]
            self._row_idx += 1
            return row
        return None

    def fetchall(self) -> List[Tuple[Any, ...]]:
        if self._closed:
            raise RuntimeError("Cursor is closed.")
        remaining = self._rows[self._row_idx:]
        self._row_idx = len(self._rows)
        return remaining

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "LocalPsqlCursor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class LocalPsqlConnection:
    """
    Focused database connection backed by a persistent psql process in Docker.

    Implements PEP 249 commit/rollback and cursor semantics tailored specifically
    to the ingestion worker and orchestrator. Not a general-purpose native driver.
    """

    def __init__(self, db_name: str, container_name: str = CONTAINER_NAME, db_user: str = DB_USER) -> None:
        # Enforce strict safety boundary: target database must be a verified disposable test database
        if not db_name.startswith(DISPOSABLE_DB_PREFIX):
            raise ValueError(
                f"Safety violation: target database '{db_name}' does not match disposable prefix '{DISPOSABLE_DB_PREFIX}'!"
            )

        self.db_name = db_name
        self.container_name = container_name
        self.db_user = db_user
        self._closed = False
        self._in_transaction = False

        cmd = [
            "docker", "exec", "-i", container_name,
            "sh", "-c", f"exec psql -U {db_user} -d {db_name} -v ON_ERROR_STOP=0 2>&1",
        ]
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        init_sql = (
            "\\set QUIET on\n"
            "\\pset format unaligned\n"
            "\\pset tuples_only on\n"
            "SET client_min_messages = warning;\n"
            "SET standard_conforming_strings = on;\n"
        )
        self._send_command(init_sql)

    def _send_command(self, sql: str) -> List[str]:
        if self._closed or self.proc.poll() is not None:
            raise RuntimeError("Connection is closed or underlying psql process died.")

        marker = f"__SENTINEL_{time.time_ns()}__"
        payload = f"{sql.strip()}\n\\echo '{marker}'\n"
        if self.proc.stdin:
            self.proc.stdin.write(payload)
            self.proc.stdin.flush()

        output_lines: List[str] = []
        if self.proc.stdout:
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    break
                if line.strip() == marker:
                    break
                output_lines.append(line)

        return output_lines

    def cursor(self) -> LocalPsqlCursor:
        return LocalPsqlCursor(self)

    def commit(self) -> None:
        if not self._closed and self._in_transaction:
            self._send_command("COMMIT;")
            self._in_transaction = False

    def rollback(self) -> None:
        if not self._closed and self._in_transaction:
            self._send_command("ROLLBACK;")
            self._in_transaction = False

    def get_transaction_status(self) -> int:
        return 2 if self._in_transaction else 0

    @property
    def in_transaction(self) -> bool:
        return self._in_transaction

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                if self._in_transaction:
                    try:
                        self._send_command("ROLLBACK;")
                    except Exception:
                        pass
                    self._in_transaction = False
                if self.proc.stdin and not self.proc.stdin.closed:
                    try:
                        self.proc.stdin.write("\\q\n")
                        self.proc.stdin.flush()
                    except Exception:
                        pass
                    self.proc.stdin.close()
                if self.proc.stdout and not self.proc.stdout.closed:
                    self.proc.stdout.close()
                self.proc.terminate()
                self.proc.wait(timeout=1)
            except Exception:
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=1)
                except Exception:
                    pass

    def __del__(self) -> None:
        self.close()

    def __enter__(self) -> "LocalPsqlConnection":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()


# =============================================================================
# Integration Test Case
# =============================================================================

class TestLocalIngestionIntegration(unittest.TestCase):
    """Deterministic local ingestion integration tests against PostgreSQL in Docker."""

    temp_db: str = ""
    container_verified: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        """Verifies local Docker PostgreSQL container and provisions isolated disposable database."""
        # 1. Verify container readiness
        try:
            check = subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-c", "SELECT 1;"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if check.returncode != 0:
                raise unittest.SkipTest(f"Docker PostgreSQL container '{CONTAINER_NAME}' is not reachable.")
        except Exception as exc:
            raise unittest.SkipTest(f"Docker PostgreSQL check failed: {exc}")

        cls.container_verified = True

        # 2. Generate unique disposable database name
        timestamp = int(time.time())
        token = uuid.uuid4().hex[:6]
        cls.temp_db = f"{DISPOSABLE_DB_PREFIX}{timestamp}_{token}"

        # 3. Create disposable test database
        subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-c", f"CREATE DATABASE {cls.temp_db};"],
            check=True,
            capture_output=True,
        )

        # 4. Apply local test bootstrap
        with open(BOOTSTRAP_FILE, "rb") as f:
            subprocess.run(
                ["docker", "exec", "-i", CONTAINER_NAME, "psql", "-U", DB_USER, "-d", cls.temp_db],
                stdin=f,
                check=True,
                capture_output=True,
            )

        # 5. Apply all 3 migrations in sorted order
        for mig_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            with open(mig_path, "rb") as f:
                subprocess.run(
                    ["docker", "exec", "-i", CONTAINER_NAME, "psql", "-U", DB_USER, "-d", cls.temp_db],
                    stdin=f,
                    check=True,
                    capture_output=True,
                )

    @classmethod
    def tearDownClass(cls) -> None:
        """Cleans up disposable database strictly ensuring no pre-existing databases are touched."""
        if cls.temp_db and cls.temp_db.startswith(DISPOSABLE_DB_PREFIX):
            # Terminate active backends on test database
            subprocess.run(
                [
                    "docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-c",
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{cls.temp_db}' AND pid <> pg_backend_pid();",
                ],
                capture_output=True,
            )
            # Drop disposable database
            subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-c", f"DROP DATABASE IF EXISTS {cls.temp_db};"],
                capture_output=True,
            )

    def setUp(self) -> None:
        """Tracks all connections opened during individual tests for guaranteed cleanup."""
        self._opened_connections: List[LocalPsqlConnection] = []

    def tearDown(self) -> None:
        """Deterministically closes all connections opened by the test."""
        for conn in self._opened_connections:
            try:
                conn.close()
            except Exception:
                pass
        self._opened_connections.clear()

    def _get_connection_factory(self) -> Callable[[], LocalPsqlConnection]:
        """Returns connection factory providing isolated LocalPsqlConnection to the disposable DB."""
        def factory() -> LocalPsqlConnection:
            conn = LocalPsqlConnection(self.temp_db, container_name=CONTAINER_NAME, db_user=DB_USER)
            self._opened_connections.append(conn)
            return conn
        return factory

    def _build_mock_gemini_client(self, timeline_hook: Optional[List[str]] = None) -> Tuple[GeminiClient, List[int]]:
        """Constructs a GeminiClient configured with a deterministic mock transport."""
        invocations = [0]
        raw_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(create_sample_gemini_response_payload())}]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 500,
                "candidatesTokenCount": 250,
            },
        }
        api_response_body = json.dumps(raw_response)

        def mock_transport(req: urllib.request.Request, timeout: float) -> Tuple[int, Dict[str, str], str]:
            invocations[0] += 1
            if timeline_hook is not None:
                timeline_hook.append("gemini_call")
            return 200, {}, api_response_body

        client = GeminiClient(
            config=GeminiConfig(model_id="gemini-2.0-flash", api_key="test-synthetic-mock-key"),
            transport=mock_transport,
        )
        return client, invocations

    def test_01_positive_end_to_end_ingestion(self) -> None:
        """
        Exercises the complete end-to-end ingestion pipeline with actual JobWorker,
        PipelineOrchestrator, and PostgreSQL persistence against the disposable database.
        """
        conn_factory = self._get_connection_factory()

        # Seed synthetic guest, draft episode, and pending processing job
        guest_id = str(uuid.uuid4())
        episode_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        video_id = "sample101"

        # Seed unrelated episode and job to verify no accidental cross-writes
        unrelated_guest_id = str(uuid.uuid4())
        unrelated_episode_id = str(uuid.uuid4())
        unrelated_job_id = str(uuid.uuid4())

        seed_conn = conn_factory()
        cur = seed_conn.cursor()

        # Target entities
        cur.execute(
            """
            INSERT INTO guests (id, slug, name, title, company, bio, industry)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
            """,
            (guest_id, f"synth-guest-{guest_id[:8]}", "Dawit Tadesse", "Managing Director", "Nile Cold Chain", "Bio", "Logistics"),
        )
        cur.execute(
            """
            INSERT INTO episodes (id, legacy_id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s);
            """,
            (episode_id, f"ep-{episode_id[:8]}", 901, "Synthetic Cold Chain Episode", "Synthetic summary", guest_id, 30, f"https://youtu.be/{video_id}", video_id),
        )
        cur.execute(
            """
            INSERT INTO processing_jobs (id, episode_id, youtube_url, youtube_video_id, status, current_stage)
            VALUES (%s, %s, %s, %s, 'pending', 'submission');
            """,
            (job_id, episode_id, f"https://youtu.be/{video_id}", video_id),
        )

        # Unrelated entities
        cur.execute(
            """
            INSERT INTO guests (id, slug, name, title, company, bio, industry)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
            """,
            (unrelated_guest_id, f"synth-unrelated-{unrelated_guest_id[:8]}", "Unrelated Guest", "Title", "Co", "Bio", "Fintech"),
        )
        cur.execute(
            """
            INSERT INTO episodes (id, legacy_id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s);
            """,
            (unrelated_episode_id, f"ep-unrelated-{unrelated_episode_id[:8]}", 902, "Unrelated Episode", "Summary", unrelated_guest_id, 45, "https://youtu.be/unrelated01", "unrelated01"),
        )
        cur.execute(
            """
            INSERT INTO processing_jobs (id, episode_id, youtube_url, youtube_video_id, status, current_stage)
            VALUES (%s, %s, %s, %s, 'pending', 'submission');
            """,
            (unrelated_job_id, unrelated_episode_id, "https://youtu.be/unrelated01", "unrelated01"),
        )

        seed_conn.commit()
        cur.close()
        seed_conn.close()

        # Build worker with mock Gemini transport
        timeline: List[str] = []
        gemini_client, mock_invocations = self._build_mock_gemini_client(timeline_hook=timeline)
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            transcript_content = json.load(f)

        provider = StaticTranscriptProvider(default_content=transcript_content, requires_confirmation=True)
        worker = JobWorker(
            connection_factory=conn_factory,
            transcript_provider=provider,
            orchestrator=orchestrator,
        )

        # Execute worker processing
        result = worker.process_job(job_id, confirm_youtube_video_id=video_id)

        # Assert worker result structure
        self.assertIsInstance(result, JobWorkerResult)
        self.assertTrue(result.processed)
        self.assertEqual(result.job_id, job_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.stage, "human_review")
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.pipeline_result)
        self.assertEqual(mock_invocations[0], 1)

        # ---------------------------------------------------------------------
        # Database Schema Assertions
        # ---------------------------------------------------------------------
        verify_conn = conn_factory()
        v_cur = verify_conn.cursor()

        # 1. Processing job status, stage, completion timestamp, error state
        v_cur.execute(
            "SELECT status, current_stage, completed_at, error_summary FROM processing_jobs WHERE id = %s;",
            (job_id,),
        )
        job_row = v_cur.fetchone()
        self.assertIsNotNone(job_row)
        self.assertEqual(job_row[0], "completed")
        self.assertEqual(job_row[1], "human_review")
        # In Meri ingestion, human_review is an editorial staging phase; completed_at remains NULL until publication/failure
        self.assertIsNone(job_row[2])
        self.assertIsNone(job_row[3])

        # 2. Episode remains draft and unpublished
        v_cur.execute(
            "SELECT publication_status, published_at FROM episodes WHERE id = %s;",
            (episode_id,),
        )
        ep_row = v_cur.fetchone()
        self.assertIsNotNone(ep_row)
        self.assertEqual(ep_row[0], "draft")
        self.assertIsNone(ep_row[1])

        # 3. Transcript segments: count, indices, and generated start_seconds column
        v_cur.execute(
            "SELECT segment_index, start_ms, end_ms, start_seconds, text FROM transcript_segments WHERE episode_id = %s ORDER BY segment_index ASC;",
            (episode_id,),
        )
        segments_rows = v_cur.fetchall()
        self.assertEqual(len(segments_rows), 4)

        expected_time_ranges = [
            (0, 0, 14200, 0.0),
            (1, 14201, 35000, 14.2),
            (2, 35001, 58000, 35.0),
            (3, 58001, 85000, 58.0),
        ]
        for idx, row in enumerate(segments_rows):
            exp_idx, exp_start, exp_end, exp_sec = expected_time_ranges[idx]
            self.assertEqual(row[0], exp_idx)
            self.assertEqual(row[1], exp_start)
            self.assertEqual(row[2], exp_end)
            self.assertAlmostEqual(float(row[3]), exp_sec, places=1)

        # 4. Transcript chunks
        v_cur.execute(
            "SELECT count(*) FROM transcript_chunks WHERE episode_id = %s;",
            (episode_id,),
        )
        chunks_count = int(v_cur.fetchone()[0])
        self.assertGreaterEqual(chunks_count, 1)

        # 5. Extraction run record: status, run_number, model_id
        v_cur.execute(
            "SELECT run_number, validation_status, model_id FROM extraction_runs WHERE job_id = %s;",
            (job_id,),
        )
        run_row = v_cur.fetchone()
        self.assertIsNotNone(run_row)
        self.assertEqual(run_row[0], 1)
        self.assertEqual(run_row[1], "passed")
        self.assertEqual(run_row[2], "gemini-2.0-flash")

        # 6. Candidate insights: strictly 'candidate' review_status
        v_cur.execute(
            "SELECT id, title, category, review_status FROM insights WHERE episode_id = %s;",
            (episode_id,),
        )
        insight_rows = v_cur.fetchall()
        self.assertEqual(len(insight_rows), 1)
        ins_id = insight_rows[0][0]
        self.assertEqual(insight_rows[0][1], "የሎጂስቲክስ ስራ እና የመንገድ ላይ ብክነት")
        self.assertEqual(insight_rows[0][2], "Operations")
        self.assertEqual(insight_rows[0][3], "candidate")

        # 7. Candidate quotations: strictly 'candidate' review_status and anchor segment
        v_cur.execute(
            "SELECT id, segment_id, amharic_quote, timestamp_seconds, review_status FROM quotations WHERE episode_id = %s;",
            (episode_id,),
        )
        quote_rows = v_cur.fetchall()
        self.assertEqual(len(quote_rows), 1)
        quote_id = quote_rows[0][0]
        anchor_seg_id = quote_rows[0][1]
        self.assertEqual(quote_rows[0][4], "candidate")
        self.assertEqual(quote_rows[0][3], 14)

        # Verify anchor segment points to segment 1
        v_cur.execute("SELECT id FROM transcript_segments WHERE episode_id = %s AND segment_index = 1;", (episode_id,))
        expected_seg_1_id = v_cur.fetchone()[0]
        self.assertEqual(anchor_seg_id, expected_seg_1_id)

        # 8. Insight evidence foreign-key link to segment 1
        v_cur.execute(
            "SELECT segment_id FROM insight_evidence WHERE insight_id = %s;",
            (ins_id,),
        )
        ev_row = v_cur.fetchone()
        self.assertIsNotNone(ev_row)
        self.assertEqual(ev_row[0], expected_seg_1_id)

        # 9. Quotation segments relational provenance link to segment 1
        v_cur.execute(
            "SELECT segment_id, sequence_order FROM quotation_segments WHERE quotation_id = %s;",
            (quote_id,),
        )
        qs_row = v_cur.fetchone()
        self.assertIsNotNone(qs_row)
        self.assertEqual(qs_row[0], expected_seg_1_id)
        self.assertEqual(qs_row[1], 0)

        # 10. Isolation check: no writes to unrelated episode or job
        v_cur.execute(
            "SELECT count(*) FROM transcript_segments WHERE episode_id = %s;",
            (unrelated_episode_id,),
        )
        self.assertEqual(int(v_cur.fetchone()[0]), 0)

        v_cur.execute(
            "SELECT count(*) FROM insights WHERE episode_id = %s;",
            (unrelated_episode_id,),
        )
        self.assertEqual(int(v_cur.fetchone()[0]), 0)

        v_cur.execute(
            "SELECT status, current_stage FROM processing_jobs WHERE id = %s;",
            (unrelated_job_id,),
        )
        unrelated_j_row = v_cur.fetchone()
        self.assertEqual(unrelated_j_row[0], "pending")
        self.assertEqual(unrelated_j_row[1], "submission")

        v_cur.close()
        verify_conn.close()

    def test_02_rejection_missing_or_whitespace_confirmation(self) -> None:
        """
        Asserts that missing or whitespace-only operator confirmation is rejected
        before transcript processing and before Gemini mock transport is invoked.
        """
        conn_factory = self._get_connection_factory()
        guest_id = str(uuid.uuid4())
        episode_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        video_id = "sample102"

        seed_conn = conn_factory()
        cur = seed_conn.cursor()
        cur.execute(
            "INSERT INTO guests (id, slug, name, title, company, bio, industry) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (guest_id, f"guest-{guest_id[:8]}", "Name", "Title", "Co", "Bio", "Ind"),
        )
        cur.execute(
            "INSERT INTO episodes (id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id) VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s, %s);",
            (episode_id, 903, "Title", "Summary", guest_id, 30, f"https://youtu.be/{video_id}", video_id),
        )
        cur.execute(
            "INSERT INTO processing_jobs (id, episode_id, youtube_url, youtube_video_id, status, current_stage) VALUES (%s, %s, %s, %s, 'pending', 'submission');",
            (job_id, episode_id, f"https://youtu.be/{video_id}", video_id),
        )
        seed_conn.commit()
        cur.close()
        seed_conn.close()

        gemini_client, mock_invocations = self._build_mock_gemini_client()
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            transcript_content = json.load(f)

        provider = StaticTranscriptProvider(default_content=transcript_content, requires_confirmation=True)
        worker = JobWorker(connection_factory=conn_factory, transcript_provider=provider, orchestrator=PipelineOrchestrator(gemini_client=gemini_client))

        # Test with whitespace-only confirmation
        res = worker.process_job(job_id, confirm_youtube_video_id="   ")

        self.assertEqual(res.status, "failed")
        self.assertEqual(res.stage, "submission")
        self.assertIn("cannot be empty or whitespace-only", res.error or "")
        self.assertEqual(mock_invocations[0], 0, "Gemini transport was invoked despite empty confirmation!")

        # Verify DB failure status
        check_conn = conn_factory()
        c_cur = check_conn.cursor()
        c_cur.execute("SELECT status, current_stage, error_summary FROM processing_jobs WHERE id = %s;", (job_id,))
        j_row = c_cur.fetchone()
        self.assertEqual(j_row[0], "failed")
        self.assertEqual(j_row[1], "submission")
        self.assertIn("whitespace-only", j_row[2])

        # Assert no segments were created
        c_cur.execute("SELECT count(*) FROM transcript_segments WHERE episode_id = %s;", (episode_id,))
        self.assertEqual(int(c_cur.fetchone()[0]), 0)

        c_cur.close()
        check_conn.close()

    def test_03_rejection_mismatched_video_id(self) -> None:
        """
        Asserts that confirmed YouTube video ID mismatch is rejected before AI extraction.
        """
        conn_factory = self._get_connection_factory()
        guest_id = str(uuid.uuid4())
        episode_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        video_id = "sample103"

        seed_conn = conn_factory()
        cur = seed_conn.cursor()
        cur.execute(
            "INSERT INTO guests (id, slug, name, title, company, bio, industry) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (guest_id, f"guest-{guest_id[:8]}", "Name", "Title", "Co", "Bio", "Ind"),
        )
        cur.execute(
            "INSERT INTO episodes (id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id) VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s, %s);",
            (episode_id, 904, "Title", "Summary", guest_id, 30, f"https://youtu.be/{video_id}", video_id),
        )
        cur.execute(
            "INSERT INTO processing_jobs (id, episode_id, youtube_url, youtube_video_id, status, current_stage) VALUES (%s, %s, %s, %s, 'pending', 'submission');",
            (job_id, episode_id, f"https://youtu.be/{video_id}", video_id),
        )
        seed_conn.commit()
        cur.close()
        seed_conn.close()

        gemini_client, mock_invocations = self._build_mock_gemini_client()
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            transcript_content = json.load(f)

        provider = StaticTranscriptProvider(default_content=transcript_content, requires_confirmation=True)
        worker = JobWorker(connection_factory=conn_factory, transcript_provider=provider, orchestrator=PipelineOrchestrator(gemini_client=gemini_client))

        # Test with mismatched confirmation
        res = worker.process_job(job_id, confirm_youtube_video_id="MISMATCHED_ID")

        self.assertEqual(res.status, "failed")
        self.assertEqual(res.stage, "submission")
        self.assertIn("does not match", res.error or "")
        self.assertEqual(mock_invocations[0], 0, "Gemini transport was invoked despite video ID mismatch!")

        # Verify DB failure status
        check_conn = conn_factory()
        c_cur = check_conn.cursor()
        c_cur.execute("SELECT status, current_stage, error_summary FROM processing_jobs WHERE id = %s;", (job_id,))
        j_row = c_cur.fetchone()
        self.assertEqual(j_row[0], "failed")
        self.assertEqual(j_row[1], "submission")
        self.assertIn("MISMATCHED_ID", j_row[2])

        c_cur.close()
        check_conn.close()

    def test_04_editorial_protection_against_verified_content_and_rollback(self) -> None:
        """
        Asserts that ingestion rerun against an episode with verified editorial content
        is strictly rejected, triggering transaction rollback and preserving verified content.
        """
        conn_factory = self._get_connection_factory()
        guest_id = str(uuid.uuid4())
        episode_id = str(uuid.uuid4())
        job_id_1 = str(uuid.uuid4())
        job_id_2 = str(uuid.uuid4())
        video_id = "sample104"

        seed_conn = conn_factory()
        cur = seed_conn.cursor()
        cur.execute(
            "INSERT INTO guests (id, slug, name, title, company, bio, industry) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (guest_id, f"guest-{guest_id[:8]}", "Name", "Title", "Co", "Bio", "Ind"),
        )
        cur.execute(
            "INSERT INTO episodes (id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id) VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s, %s);",
            (episode_id, 905, "Title", "Summary", guest_id, 30, f"https://youtu.be/{video_id}", video_id),
        )
        cur.execute(
            "INSERT INTO processing_jobs (id, episode_id, youtube_url, youtube_video_id, status, current_stage) VALUES (%s, %s, %s, %s, 'pending', 'submission');",
            (job_id_1, episode_id, f"https://youtu.be/{video_id}", video_id),
        )
        seed_conn.commit()
        cur.close()
        seed_conn.close()

        gemini_client, mock_invocations = self._build_mock_gemini_client()
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            transcript_content = json.load(f)

        provider = StaticTranscriptProvider(default_content=transcript_content, requires_confirmation=True)
        worker = JobWorker(connection_factory=conn_factory, transcript_provider=provider, orchestrator=PipelineOrchestrator(gemini_client=gemini_client))

        # First run succeeds
        res1 = worker.process_job(job_id_1, confirm_youtube_video_id=video_id)
        self.assertEqual(res1.status, "completed")
        self.assertEqual(mock_invocations[0], 1)

        # Reviewer approves candidate insight via database RPC
        review_conn = conn_factory()
        r_cur = review_conn.cursor()
        r_cur.execute("SELECT id FROM insights WHERE episode_id = %s;", (episode_id,))
        cand_ins_id = r_cur.fetchone()[0]

        # Execute review RPC
        review_result = CandidatePersistenceService.execute_editorial_review(
            cursor=r_cur,
            item_type="insight",
            item_id=cand_ins_id,
            decision="verified",
        )
        self.assertTrue(review_result.get("success"))
        self.assertEqual(review_result.get("review_status"), "verified")
        review_conn.commit()
        r_cur.close()
        review_conn.close()

        # Seed second job attempting rerun on same episode
        seed_conn2 = conn_factory()
        cur2 = seed_conn2.cursor()
        cur2.execute(
            "INSERT INTO processing_jobs (id, episode_id, youtube_url, youtube_video_id, status, current_stage) VALUES (%s, %s, %s, %s, 'pending', 'submission');",
            (job_id_2, episode_id, f"https://youtu.be/{video_id}", video_id),
        )
        seed_conn2.commit()
        cur2.close()
        seed_conn2.close()

        # Rerun attempted (even with allow_candidate_rerun=True)
        res2 = worker.process_job(job_id_2, allow_candidate_rerun=True, confirm_youtube_video_id=video_id)

        # Assert rejection by editorial preflight protection
        self.assertEqual(res2.status, "failed")
        self.assertEqual(res2.stage, "human_review")
        self.assertIn("verified/reviewed", res2.error or "")
        # Gemini transport was NOT invoked on the second attempt
        self.assertEqual(mock_invocations[0], 1, "Gemini transport was called despite editorial review protection!")

        # Verify pre-existing verified insight is strictly preserved
        check_conn = conn_factory()
        c_cur = check_conn.cursor()
        c_cur.execute("SELECT review_status FROM insights WHERE id = %s;", (cand_ins_id,))
        self.assertEqual(c_cur.fetchone()[0], "verified")
        c_cur.close()
        check_conn.close()

    def test_05_editorial_protection_against_published_episode(self) -> None:
        """
        Asserts that ingestion against an already published episode is strictly rejected.
        """
        conn_factory = self._get_connection_factory()
        guest_id = str(uuid.uuid4())
        episode_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        video_id = "sample105"

        seed_conn = conn_factory()
        cur = seed_conn.cursor()
        cur.execute(
            "INSERT INTO guests (id, slug, name, title, company, bio, industry) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (guest_id, f"guest-{guest_id[:8]}", "Name", "Title", "Co", "Bio", "Ind"),
        )
        cur.execute(
            """
            INSERT INTO episodes (id, episode_number, title, summary, guest_id, duration_minutes, publication_status, published_at, youtube_url, youtube_video_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'published', now(), %s, %s);
            """,
            (episode_id, 906, "Published Episode", "Summary", guest_id, 30, f"https://youtu.be/{video_id}", video_id),
        )
        cur.execute(
            "INSERT INTO processing_jobs (id, episode_id, youtube_url, youtube_video_id, status, current_stage) VALUES (%s, %s, %s, %s, 'pending', 'submission');",
            (job_id, episode_id, f"https://youtu.be/{video_id}", video_id),
        )
        seed_conn.commit()
        cur.close()
        seed_conn.close()

        gemini_client, mock_invocations = self._build_mock_gemini_client()
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            transcript_content = json.load(f)

        provider = StaticTranscriptProvider(default_content=transcript_content, requires_confirmation=True)
        worker = JobWorker(connection_factory=conn_factory, transcript_provider=provider, orchestrator=PipelineOrchestrator(gemini_client=gemini_client))

        res = worker.process_job(job_id, confirm_youtube_video_id=video_id)

        self.assertEqual(res.status, "failed")
        self.assertEqual(res.stage, "human_review")
        self.assertIn("already published", res.error or "")
        self.assertEqual(mock_invocations[0], 0, "Gemini transport was called for published episode!")

        # Verify episode publication status remains untouched
        check_conn = conn_factory()
        c_cur = check_conn.cursor()
        c_cur.execute("SELECT publication_status FROM episodes WHERE id = %s;", (episode_id,))
        self.assertEqual(c_cur.fetchone()[0], "published")
        c_cur.close()
        check_conn.close()

    def test_06_disposable_database_cleanup_isolation(self) -> None:
        """
        Verifies that cleanup drops only the disposable test database and
        leaves all other pre-existing databases untouched.
        """
        isolated_db_name = f"{DISPOSABLE_DB_PREFIX}isolation_check_{int(time.time())}"

        # Create isolated disposable DB
        subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-c", f"CREATE DATABASE {isolated_db_name};"],
            check=True,
            capture_output=True,
        )

        # Confirm existence
        chk = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-t", "-A", "-c", f"SELECT count(*) FROM pg_database WHERE datname = '{isolated_db_name}';"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(chk.stdout.strip(), "1")

        # Cleanup isolated disposable DB
        subprocess.run(
            [
                "docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-c",
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{isolated_db_name}' AND pid <> pg_backend_pid();",
            ],
            capture_output=True,
        )
        subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-c", f"DROP DATABASE IF EXISTS {isolated_db_name};"],
            check=True,
            capture_output=True,
        )

        # Confirm dropped
        chk_after = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-t", "-A", "-c", f"SELECT count(*) FROM pg_database WHERE datname = '{isolated_db_name}';"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(chk_after.stdout.strip(), "0")

        # Confirm standard default database 'postgres' remains untouched
        chk_default = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "psql", "-U", DB_USER, "-t", "-A", "-c", "SELECT count(*) FROM pg_database WHERE datname = 'postgres';"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(chk_default.stdout.strip(), "1")

    def test_07_adapter_transaction_rollback_and_type_preservation(self) -> None:
        """
        Adapter regression test verifying LocalPsqlConnection and LocalPsqlCursor:
        1. Manual-commit transaction rollback leaves uncommitted writes discarded.
        2. Manual-commit transaction commit makes writes permanent.
        3. Transaction status tracking (in_transaction / get_transaction_status).
        4. Strict data type preservation (int, float, bool, null, dict, list, str).
        5. PostgreSQL error surfacing and session recovery after rollback.
        """
        conn_factory = self._get_connection_factory()

        # 1. Transaction rollback verification
        conn = conn_factory()
        cur = conn.cursor()
        self.assertFalse(conn.in_transaction)
        self.assertEqual(conn.get_transaction_status(), 0)

        rollback_guest_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO guests (id, slug, name, title, company, bio, industry) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (rollback_guest_id, f"rb-{rollback_guest_id[:8]}", "Rollback Guest", "Title", "Co", "Bio", "Ind"),
        )
        self.assertTrue(conn.in_transaction)
        self.assertEqual(conn.get_transaction_status(), 2)

        conn.rollback()
        self.assertFalse(conn.in_transaction)
        self.assertEqual(conn.get_transaction_status(), 0)

        # Confirm row was NOT persisted
        cur.execute("SELECT count(*) FROM guests WHERE id = %s;", (rollback_guest_id,))
        self.assertEqual(int(cur.fetchone()[0]), 0)

        # 2. Transaction commit verification
        commit_guest_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO guests (id, slug, name, title, company, bio, industry) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (commit_guest_id, f"cm-{commit_guest_id[:8]}", "Commit Guest", "Title", "Co", "Bio", "Ind"),
        )
        conn.commit()
        self.assertFalse(conn.in_transaction)

        # Check in a separate session
        reader_conn = conn_factory()
        r_cur = reader_conn.cursor()
        r_cur.execute("SELECT name FROM guests WHERE id = %s;", (commit_guest_id,))
        row = r_cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Commit Guest")

        # 3. Data type preservation verification
        cur.execute(
            """
            SELECT
                42::integer AS int_val,
                3.14::numeric AS float_val,
                true::boolean AS bool_val,
                NULL::text AS null_val,
                'Dawit Tadesse'::text AS str_val,
                '{"category": "Logistics", "verified": true}'::jsonb AS json_val,
                ARRAY['tag1', 'tag2']::text[] AS arr_val;
            """
        )
        type_row = cur.fetchone()
        self.assertIsNotNone(type_row)
        self.assertIsInstance(type_row[0], int)
        self.assertEqual(type_row[0], 42)
        self.assertAlmostEqual(float(type_row[1]), 3.14, places=2)
        self.assertIs(type_row[2], True)
        self.assertIsNone(type_row[3])
        self.assertEqual(type_row[4], "Dawit Tadesse")
        self.assertIsInstance(type_row[5], dict)
        self.assertEqual(type_row[5]["category"], "Logistics")
        self.assertEqual(type_row[5]["verified"], True)
        self.assertIsInstance(type_row[6], list)
        self.assertEqual(type_row[6], ["tag1", "tag2"])

        # 4. Error surfacing and session recovery verification
        with self.assertRaises(RuntimeError) as ctx:
            cur.execute("SELECT * FROM non_existent_table_for_error_test;")
        self.assertIn("non_existent_table_for_error_test", str(ctx.exception))
        self.assertTrue(conn.in_transaction)

        # Session recovers after rollback
        conn.rollback()
        self.assertFalse(conn.in_transaction)
        cur.execute("SELECT 101;")
        recovery_row = cur.fetchone()
        self.assertIsNotNone(recovery_row)
        self.assertEqual(recovery_row[0], 101)


if __name__ == "__main__":
    unittest.main()
