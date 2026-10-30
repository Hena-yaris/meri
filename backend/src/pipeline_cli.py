"""
Meri Content Pipeline v1: Ingestion Pipeline CLI.

A thin command-line interface for running the ingestion worker in one-shot mode:
- `python3 -m backend.src.pipeline_cli run-job <job_id>`: Claims and processes a specific job.
- `python3 -m backend.src.pipeline_cli run-next`: Claims and processes the next pending job.

Environment & Dependencies:
- DATABASE_URL: PostgreSQL connection string (e.g. postgresql://user:pass@localhost:5432/meri).
- GEMINI_API_KEY: Google Gemini API key.
- Requires either `psycopg2` or `psycopg` installed for direct database connectivity.
"""

import argparse
import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Union

from .candidate_persistence import CandidatePersistenceService
from .candidate_reconciliation import CandidateReconciler
from .chunker import TranscriptChunker
from .extraction_models import ValidationErrorCode, ValidationSeverity, ValidationStatus
from .extraction_service import ExtractionService
from .gemini_client import GeminiClient, GeminiConfig, validate_model_id_syntax
from .job_worker import (
    JobWorker,
    JobWorkerResult,
    StaticTranscriptProvider,
    TranscriptProvider,
)
from .caption_reconstructor import RollingCaptionReconstructor
from .transcript_normalizer import TranscriptNormalizer
from .transcript_parser import parse_transcript

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("meri.pipeline_cli")


def _redact_secrets(text: Optional[str]) -> str:
    """Strips API keys, bearer tokens, database credentials, passwords, and sensitive parameters."""
    if not text:
        return "" if text is None else text
    scrubbed = str(text)
    # Strip ?key=... or query parameters with sensitive names
    scrubbed = re.sub(
        r"([?&](?:key|password|pwd|secret|token)=)[^&\s'\"]+",
        r"\1[REDACTED]",
        scrubbed,
        flags=re.IGNORECASE,
    )
    # Strip Google API Keys (AIzaSy...)
    scrubbed = re.sub(r"AIza[0-9A-Za-z-_]{30,40}", "[REDACTED_API_KEY]", scrubbed)
    # Strip Bearer tokens
    scrubbed = re.sub(
        r"(Bearer\s+)[A-Za-z0-9\-_.]{10,}",
        r"\1[REDACTED_TOKEN]",
        scrubbed,
        flags=re.IGNORECASE,
    )
    # Strip key-value DSN passwords: password=... or pwd=...
    scrubbed = re.sub(
        r"(\b(?:password|pwd)\s*=\s*)(?:\"[^\"]*\"|'[^']*'|[^\s'\"]+)",
        r"\1[REDACTED]",
        scrubbed,
        flags=re.IGNORECASE,
    )
    # Strip database credentials embedded in connection URIs (e.g. postgres://user:pass@host or ://:pass@host)
    scrubbed = re.sub(r"(://[^:@\s]*):([^@\s]+)@", r"\1:[REDACTED]@", scrubbed)
    return scrubbed


def get_db_driver() -> Optional[str]:
    """Detects available PostgreSQL driver in python environment."""
    try:
        import psycopg2  # noqa: F401
        return "psycopg2"
    except ImportError:
        pass

    try:
        import psycopg  # noqa: F401
        return "psycopg"
    except ImportError:
        pass

    return None


def create_connection_factory(database_url: Optional[str] = None) -> Callable[[], Any]:
    """
    Creates a database connection factory using installed drivers and DATABASE_URL.

    Raises:
        RuntimeError: If no PostgreSQL driver is installed or DATABASE_URL is missing.
    """
    driver = get_db_driver()
    if driver is None:
        raise RuntimeError(
            "PostgreSQL Python driver ('psycopg2' or 'psycopg') is not installed in the environment.\n"
            "To execute the CLI against a live database, please install a compatible driver:\n"
            "  pip install psycopg2-binary\n"
            "or\n"
            "  pip install 'psycopg[binary]'\n"
            "Note: SQL verification tests can still be executed via './backend/tests/run_db_tests.sh'."
        )

    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Missing DATABASE_URL environment variable.\n"
            "Please specify a valid PostgreSQL connection URI:\n"
            "  export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/meri"
        )

    if driver == "psycopg2":
        import psycopg2

        def factory():
            return psycopg2.connect(url)

        return factory

    else:
        import psycopg

        def factory():
            return psycopg.connect(url)

        return factory


def create_transcript_provider(
    transcript_file: Optional[str] = None,
) -> Optional[TranscriptProvider]:
    """Creates transcript provider from local file if specified."""
    if not transcript_file:
        return None

    path = Path(transcript_file)
    if not path.is_file():
        raise FileNotFoundError(f"Transcript file not found: {transcript_file}")

    content = path.read_text(encoding="utf-8")
    # If JSON file, attempt parsing into dictionary or raw string
    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(content)
            return StaticTranscriptProvider(default_content=parsed, requires_confirmation=True)
        except Exception:
            pass

    return StaticTranscriptProvider(default_content=content, requires_confirmation=True)


REQUIRED_TABLES = [
    "guests",
    "episodes",
    "processing_jobs",
    "transcript_segments",
    "transcript_chunks",
    "extraction_runs",
    "insights",
    "quotations",
    "insight_evidence",
    "quotation_segments",
]

EXPECTED_MIGRATIONS = [
    "20261020000001",
    "20261022000001",
    "20261024000001",
]

REVIEW_RPC_NAME = "review_candidate_item"
REVIEW_RPC_EXPECTED_PARAMS = [
    ("p_item_type", "text"),
    ("p_item_id", "uuid"),
    ("p_decision", "text"),
    ("p_reviewer_id", "uuid"),
]
REVIEW_RPC_EXPECTED_RETURN = "jsonb"


def load_env_file(
    env_path: Optional[Union[str, Path]] = None,
    *,
    raise_if_missing: bool = False,
) -> bool:
    """
    Safely loads key=value pairs from a simple .env file into os.environ if not already set.

    Supported Format:
    - Lines formatted as KEY=VALUE or KEY="VALUE" or KEY='VALUE'.
    - Empty lines and lines containing only whitespace are ignored.
    - Full-line comments starting with '#' (with optional leading whitespace) are ignored.
    - Leading and trailing whitespace around keys and values is stripped.
    - Values wrapped in matching single quotes ('...') or double quotes ("...") have
      their enclosing quotes stripped. Unmatched quotes are preserved literally.
    - Process environment precedence: if a key already exists in os.environ, its value
      is NEVER overwritten by .env.

    Unsupported Shell Syntax (Not Evaluated):
    - Shell variable expansions (e.g. $VAR, ${VAR}) are not expanded.
    - Command substitutions (e.g. `cmd`, $(cmd)) are not executed.
    - Shell keywords such as 'export' are not supported; lines starting with 'export '
      are treated as malformed and ignored.
    - Multiline unquoted values or inline comments are not supported to avoid
      accidentally corrupting connection strings or passwords containing '#' or special characters.

    Args:
        env_path: Path to .env file. If None, checks .env in current working directory,
                  then repository root.
        raise_if_missing: If True and the specified file does not exist, raises FileNotFoundError.
                          If False (default), missing file returns False without raising.

    Returns:
        bool: True if an env file was found and processed, False otherwise.
    """
    if env_path is None:
        candidate = Path(".env")
        if not candidate.is_file():
            candidate = Path(__file__).resolve().parent.parent.parent / ".env"
        env_path = candidate
        is_default_candidate = True
    else:
        env_path = Path(env_path)
        is_default_candidate = False

    if not env_path.is_file():
        if raise_if_missing and not is_default_candidate:
            raise FileNotFoundError(f"Environment file not found: {env_path}")
        return False

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    logger.debug("Skipping line %d in %s: missing '=' delimiter", line_no, env_path.name)
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()

                # Validate key name: POSIX identifier (letter/underscore followed by letters/digits/underscores)
                if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                    logger.debug("Skipping line %d in %s: invalid or unsupported key syntax", line_no, env_path.name)
                    continue

                # Strip matching surrounding quotes if present
                if len(val) >= 2 and (
                    (val.startswith('"') and val.endswith('"'))
                    or (val.startswith("'") and val.endswith("'"))
                ):
                    val = val[1:-1]

                # Precedence: never override existing process environment
                if key not in os.environ:
                    os.environ[key] = val
        return True
    except Exception as err:
        logger.warning("Could not read .env file %s: %s", env_path.name, _redact_secrets(str(err)))
        return False


def run_db_health_check(connection_factory: Callable[[], Any]) -> dict[str, Any]:
    """
    Executes a strict read-only database health check:
    1. Connects using the configured factory.
    2. Enforces read-only behavior at driver/connection level and SQL session level.
    3. Queries database identity (db name, user, version) without exposing secrets.
    4. Confirms required public tables exist.
    5. Confirms review_candidate_item RPC exists and verifies its parameter and return signatures.
    6. Confirms migration state from supabase_migrations.schema_migrations if present,
       clearly distinguishing verified migrations from an unsupported tracking table query.
    7. Cleanly rolls back any transaction and closes the connection on both success and failure.
    """
    report: dict[str, Any] = {
        "status": "failed",
        "driver": get_db_driver(),
        "database": None,
        "user": None,
        "version": None,
        "tables": {},
        "functions": {},
        "migrations": {},
        "errors": [],
    }

    conn = None
    cur = None
    try:
        conn = connection_factory()

        # Enforce read-only behavior at connection/driver level where supported
        if hasattr(conn, "set_session"):
            try:
                conn.set_session(readonly=True)
            except Exception as e:
                logger.debug("set_session(readonly=True) unsupported or failed: %s", e)
        elif hasattr(conn, "read_only"):
            try:
                conn.read_only = True
            except Exception as e:
                logger.debug("conn.read_only=True unsupported or failed: %s", e)

        cur = conn.cursor()

        # Enforce read-only behavior at session and transaction level in PostgreSQL
        try:
            cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;")
        except Exception as e:
            logger.debug("SET SESSION CHARACTERISTICS failed: %s", e)
        try:
            cur.execute("SET TRANSACTION READ ONLY;")
        except Exception as e:
            logger.debug("SET TRANSACTION READ ONLY failed: %s", e)

        # 1. Identity & Version (Safe, no credentials)
        cur.execute("SELECT current_database(), current_user, version();")
        row = cur.fetchone()
        if row:
            report["database"] = row[0]
            report["user"] = row[1]
            report["version"] = str(row[2]).split("\n")[0]

        # 2. Required tables
        placeholders = ", ".join(["%s"] * len(REQUIRED_TABLES))
        cur.execute(
            f"SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = 'public' AND table_name IN ({placeholders});",
            tuple(REQUIRED_TABLES),
        )
        found_tables = {r[0] for r in cur.fetchall()}
        missing_tables = [t for t in REQUIRED_TABLES if t not in found_tables]
        report["tables"] = {
            "expected_count": len(REQUIRED_TABLES),
            "found_count": len(found_tables),
            "found": sorted(list(found_tables)),
            "missing": missing_tables,
        }
        if missing_tables:
            report["errors"].append(f"Missing required tables: {', '.join(missing_tables)}")

        # 3. Required function: review_candidate_item & Signature Verification
        cur.execute(
            "SELECT specific_name, routine_name, data_type FROM information_schema.routines "
            "WHERE routine_schema = 'public' AND routine_name = %s;",
            (REVIEW_RPC_NAME,),
        )
        routine_rows = cur.fetchall()
        if not routine_rows:
            report["functions"][REVIEW_RPC_NAME] = {
                "status": "missing",
                "signature_verified": False,
            }
            report["errors"].append(f"Missing required function: public.{REVIEW_RPC_NAME}")
        else:
            specific_name = routine_rows[0][0]
            ret_type = str(routine_rows[0][2] or "").lower()

            cur.execute(
                "SELECT parameter_name, data_type, parameter_mode, ordinal_position "
                "FROM information_schema.parameters "
                "WHERE specific_schema = 'public' AND specific_name = %s "
                "ORDER BY ordinal_position;",
                (specific_name,),
            )
            param_rows = cur.fetchall()
            params_actual = [
                {
                    "name": r[0],
                    "type": str(r[1]).lower(),
                    "mode": r[2],
                    "position": r[3],
                }
                for r in param_rows
            ]

            # Verify parameters match expected signature
            actual_param_sig = [(p["name"], p["type"]) for p in params_actual]
            sig_match = (
                actual_param_sig == REVIEW_RPC_EXPECTED_PARAMS
                and ret_type in (REVIEW_RPC_EXPECTED_RETURN, "user-defined")
            )

            report["functions"][REVIEW_RPC_NAME] = {
                "status": "present",
                "signature_verified": sig_match,
                "return_type": ret_type,
                "parameters": params_actual,
            }
            if not sig_match:
                report["errors"].append(
                    f"Signature mismatch for public.{REVIEW_RPC_NAME}: "
                    f"expected params {REVIEW_RPC_EXPECTED_PARAMS} -> {REVIEW_RPC_EXPECTED_RETURN}, "
                    f"found params {actual_param_sig} -> {ret_type}"
                )

        # 4. Check migration tracking table if present
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'supabase_migrations' AND table_name = 'schema_migrations'"
            ");"
        )
        has_mig_table = bool(cur.fetchone()[0])
        if has_mig_table:
            cur.execute("SELECT version FROM supabase_migrations.schema_migrations ORDER BY version;")
            applied_versions = [str(r[0]) for r in cur.fetchall()]
            missing_migs = [m for m in EXPECTED_MIGRATIONS if m not in applied_versions]
            report["migrations"] = {
                "supported": True,
                "status": "verified" if not missing_migs else "missing_migrations",
                "tracking_table": "supabase_migrations.schema_migrations",
                "expected": EXPECTED_MIGRATIONS,
                "applied": applied_versions,
                "missing": missing_migs,
            }
            if missing_migs:
                report["errors"].append(
                    f"Missing expected migrations in tracking table: {', '.join(missing_migs)}"
                )
        else:
            report["migrations"] = {
                "supported": False,
                "status": "unsupported",
                "tracking_table": "supabase_migrations.schema_migrations (not present)",
                "expected": EXPECTED_MIGRATIONS,
                "applied": [],
                "missing": [],
                "detail": "Migration tracking table 'supabase_migrations.schema_migrations' is not present; migration history query is unsupported on this database.",
            }

        if not report["errors"]:
            report["status"] = "healthy"

    except Exception as err:
        err_msg = _redact_secrets(f"Database error: {type(err).__name__}: {err}")
        report["errors"].append(err_msg)
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    return report


def classify_transcript_source(file_path: Path, raw_content: str) -> str:
    """
    Classifies transcript source as synthetic or unverified based on verifiable metadata.
    Never marks synthetic fixtures or unverified local files as authentic Meri Podcast content.
    """
    path_str = str(file_path).lower()
    if any(k in path_str for k in ("fixture", "sample_transcript", "synthetic", "tests/", "test/")):
        return "synthetic_test_fixture"
    known_synthetic_cues = (
        "Nile Cold Chain Logistics",
        "Dawit Tadesse",
        "ዳዊት ታደሰ",
        "የቀዝቃዛ ሰንሰለት ሎጂስቲክስ",
    )
    if any(cue in raw_content for cue in known_synthetic_cues):
        return "synthetic_test_fixture"

    return "unverified_local_transcript"


def _emit_validation_report(
    report: Dict[str, Any],
    output_file: Optional[str] = None,
) -> None:
    """Safely emits JSON report to stdout and optionally to an output file."""
    report_json = json.dumps(report, indent=2, ensure_ascii=False)
    print(report_json)
    if output_file:
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_json, encoding="utf-8")


def run_validate_extraction(
    args: argparse.Namespace,
    extraction_service: Optional[Any] = None,
) -> int:
    """
    Executes an isolated extraction validation run on a local transcript file.
    Validates parsing, normalization, chunking, Gemini extraction, schema, and evidence provenance
    without opening database connections, claiming jobs, or writing to Supabase/PostgreSQL.

    Returns exit codes:
      0: Passed (extraction succeeded and structural/evidence validation passed).
      1: Validation Failure (syntactic schema or semantic evidence validation failed).
      2: Configuration or Provider Error (missing file, invalid provider, missing API key, network timeout).
    """
    provider = getattr(args, "provider", "fake") or "fake"
    allow_network = bool(getattr(args, "allow_network", False))
    model_id = getattr(args, "model_id", "gemini-2.0-flash") or "gemini-2.0-flash"
    request_timeout = getattr(args, "request_timeout", None)
    transcript_file = getattr(args, "transcript_file", None)
    output_file = getattr(args, "output_file", None)
    format_hint = getattr(args, "format_hint", None)

    if request_timeout is not None and request_timeout <= 0:
        err_msg = f"Invalid --request-timeout: {request_timeout}. Must be a positive number of seconds."
        logger.error(err_msg)
        report = {
            "status": "error",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": "unknown",
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "INVALID_TIMEOUT", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 2

    # 1. Provider configuration and security boundaries
    if provider not in ("fake", "gemini"):
        err_msg = f"Unsupported provider: '{provider}'. Supported providers are 'fake' and 'gemini'."
        logger.error(err_msg)
        report = {
            "status": "error",
            "run_mode": "offline_fake",
            "transcript_source": "unknown",
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "INVALID_PROVIDER", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 2

    if provider == "gemini":
        if not allow_network:
            err_msg = (
                "Network access is blocked: --provider gemini requires explicit opt-in via '--allow-network'. "
                "Execution safely aborted before provider initialization."
            )
            logger.error(err_msg)
            report = {
                "status": "error",
                "run_mode": "gemini_live",
                "transcript_source": "unknown",
                "provider": "gemini",
                "model_id": model_id,
                "counts": None,
                "validation": {
                    "schema_valid": False,
                    "evidence_grounded": False,
                    "provenance_valid": False,
                    "error_count": 1,
                    "warning_count": 0,
                    "errors": [{"severity": "error", "error_code": "NETWORK_OPT_IN_REQUIRED", "message": err_msg}],
                },
                "disclaimer": (
                    "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                    "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                    "editorial review before approval or publication."
                ),
            }
            _emit_validation_report(report, output_file)
            return 2

        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            err_msg = (
                "Missing GEMINI_API_KEY environment variable for Gemini extraction provider. "
                "Execution safely aborted before network transport initialization."
            )
            logger.error(err_msg)
            report = {
                "status": "error",
                "run_mode": "gemini_live",
                "transcript_source": "unknown",
                "provider": "gemini",
                "model_id": model_id,
                "counts": None,
                "validation": {
                    "schema_valid": False,
                    "evidence_grounded": False,
                    "provenance_valid": False,
                    "error_count": 1,
                    "warning_count": 0,
                    "errors": [{"severity": "error", "error_code": "MISSING_GEMINI_API_KEY", "message": err_msg}],
                },
                "disclaimer": (
                    "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                    "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                    "editorial review before approval or publication."
                ),
            }
            _emit_validation_report(report, output_file)
            return 2

    # 2. Transcript file reading
    if not transcript_file:
        err_msg = "Missing required --transcript-file argument."
        logger.error(err_msg)
        report = {
            "status": "error",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": "unknown",
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "MISSING_TRANSCRIPT_FILE", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 2

    path = Path(transcript_file)
    if not path.is_file():
        err_msg = f"Transcript file not found: {transcript_file}"
        logger.error(err_msg)
        report = {
            "status": "error",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": "unknown",
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "FILE_NOT_FOUND", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 2

    try:
        raw_content = path.read_text(encoding="utf-8")
    except Exception as exc:
        err_msg = f"Failed to read transcript file: {_redact_secrets(str(exc))}"
        logger.error(err_msg)
        report = {
            "status": "error",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": "unknown",
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "FILE_READ_ERROR", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 2

    source_classification = classify_transcript_source(path, raw_content)

    # 3. Parse transcript
    try:
        cues = parse_transcript(raw_content, format_hint=format_hint)
    except Exception as exc:
        err_msg = f"Transcript parsing failed: {_redact_secrets(str(exc))}"
        logger.error(err_msg)
        report = {
            "status": "validation_failed",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": source_classification,
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "TRANSCRIPT_PARSE_ERROR", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 1

    if not cues:
        err_msg = "Transcript parsing produced zero cues."
        logger.error(err_msg)
        report = {
            "status": "validation_failed",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": source_classification,
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "EMPTY_TRANSCRIPT_CUES", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 1

    # 4. Normalize cues (or reconstruct rolling captions if enabled)
    try:
        reconstruct_rolling = bool(getattr(args, "reconstruct_rolling", False))
        if reconstruct_rolling:
            reconstructor = RollingCaptionReconstructor()
            segments = reconstructor.reconstruct_to_segments(cues)
        else:
            normalizer = TranscriptNormalizer()
            segments = normalizer.normalize(cues)
    except Exception as exc:
        err_msg = f"Transcript normalization failed: {_redact_secrets(str(exc))}"
        logger.error(err_msg)
        report = {
            "status": "validation_failed",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": source_classification,
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "TRANSCRIPT_NORMALIZATION_ERROR", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 1

    if not segments:
        err_msg = "Transcript normalization produced zero segments."
        logger.error(err_msg)
        report = {
            "status": "validation_failed",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": source_classification,
            "provider": provider,
            "model_id": model_id,
            "counts": None,
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "EMPTY_TRANSCRIPT_SEGMENTS", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 1

    # 5. Chunk segments
    try:
        chunker = TranscriptChunker()
        chunks = chunker.chunk(segments)
    except Exception as exc:
        err_msg = f"Transcript chunking failed: {_redact_secrets(str(exc))}"
        logger.error(err_msg)
        report = {
            "status": "validation_failed",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": source_classification,
            "provider": provider,
            "model_id": model_id,
            "counts": {"segments": len(segments), "chunks": 0},
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "CHUNKING_ERROR", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 1

    if not chunks:
        err_msg = "Transcript chunking produced zero chunks."
        logger.error(err_msg)
        report = {
            "status": "validation_failed",
            "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
            "transcript_source": source_classification,
            "provider": provider,
            "model_id": model_id,
            "counts": {"segments": len(segments), "chunks": 0},
            "validation": {
                "schema_valid": False,
                "evidence_grounded": False,
                "provenance_valid": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [{"severity": "error", "error_code": "EMPTY_CHUNKS", "message": err_msg}],
            },
            "disclaimer": (
                "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                "editorial review before approval or publication."
            ),
        }
        _emit_validation_report(report, output_file)
        return 1

    # 5b. Chunk selection validation
    chunk_index_arg = getattr(args, "chunk_index", None)
    selected_chunk_info: Optional[Dict[str, Any]] = None
    if chunk_index_arg is not None:
        if chunk_index_arg < 0 or chunk_index_arg >= len(chunks):
            err_msg = (
                f"Invalid --chunk-index {chunk_index_arg}: transcript has {len(chunks)} chunks "
                f"(valid zero-based indices: 0..{len(chunks) - 1})."
            )
            logger.error(err_msg)
            report = {
                "status": "error",
                "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
                "transcript_source": source_classification,
                "provider": provider,
                "model_id": model_id,
                "counts": {"segments": len(segments), "chunks": len(chunks)},
                "selected_chunk": None,
                "validation": {
                    "schema_valid": False,
                    "evidence_grounded": False,
                    "provenance_valid": False,
                    "error_count": 1,
                    "warning_count": 0,
                    "errors": [{"severity": "error", "error_code": "INVALID_CHUNK_INDEX", "message": err_msg}],
                },
                "disclaimer": (
                    "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                    "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                    "editorial review before approval or publication."
                ),
            }
            _emit_validation_report(report, output_file)
            return 2

        target_chunk = chunks[chunk_index_arg]
        target_chunks = [target_chunk]
        selected_chunk_info = {
            "chunk_index": target_chunk.chunk_index,
            "start_segment_index": target_chunk.start_segment_index,
            "end_segment_index": target_chunk.end_segment_index,
            "segment_count": target_chunk.end_segment_index - target_chunk.start_segment_index + 1,
            "start_ms": target_chunk.start_ms,
            "end_ms": target_chunk.end_ms,
            "start_seconds": round(target_chunk.start_ms / 1000.0, 2),
            "end_seconds": round(target_chunk.end_ms / 1000.0, 2),
        }
    else:
        target_chunks = chunks

    # 6. Extraction service instantiation
    if extraction_service is None:
        if provider == "fake":
            try:
                from backend.tests.fake_extraction_provider import DeterministicFakeExtractor
            except ImportError:
                from ..tests.fake_extraction_provider import DeterministicFakeExtractor
            fake_extractor = DeterministicFakeExtractor(model_id=model_id)
            effective_service = fake_extractor.create_extraction_service()
        else:
            try:
                validate_model_id_syntax(model_id)
            except Exception as exc:
                err_msg = f"Invalid model identifier configuration: {_redact_secrets(str(exc))}"
                logger.error(err_msg)
                report = {
                    "status": "error",
                    "run_mode": "gemini_live",
                    "transcript_source": source_classification,
                    "provider": "gemini",
                    "model_id": model_id,
                    "counts": {"segments": len(segments), "chunks": len(chunks)},
                    "selected_chunk": selected_chunk_info,
                    "validation": {
                        "schema_valid": False,
                        "evidence_grounded": False,
                        "provenance_valid": False,
                        "error_count": 1,
                        "warning_count": 0,
                        "errors": [{"severity": "error", "error_code": "INVALID_MODEL_CONFIG", "message": err_msg}],
                    },
                    "disclaimer": (
                        "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                        "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                        "editorial review before approval or publication."
                    ),
                }
                _emit_validation_report(report, output_file)
                return 2

            config_kwargs: Dict[str, Any] = {"model_id": model_id, "api_key": gemini_key}
            if request_timeout is not None:
                config_kwargs["timeout_seconds"] = request_timeout
            config = GeminiConfig(**config_kwargs)
            client = GeminiClient(config=config)

            # Preflight model availability check before chunk extraction loop
            try:
                client.check_availability()
            except Exception as exc:
                safe_exc = _redact_secrets(str(exc))
                err_msg = f"Model preflight availability check failed: {safe_exc}"
                logger.error(err_msg)
                report = {
                    "status": "error",
                    "run_mode": "gemini_live",
                    "transcript_source": source_classification,
                    "provider": "gemini",
                    "model_id": model_id,
                    "counts": {"segments": len(segments), "chunks": len(chunks)},
                    "selected_chunk": selected_chunk_info,
                    "validation": {
                        "schema_valid": False,
                        "evidence_grounded": False,
                        "provenance_valid": False,
                        "error_count": 1,
                        "warning_count": 0,
                        "errors": [{"severity": "error", "error_code": "MODEL_AVAILABILITY_ERROR", "message": err_msg}],
                    },
                    "disclaimer": (
                        "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                        "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                        "editorial review before approval or publication."
                    ),
                }
                _emit_validation_report(report, output_file)
                return 2

            effective_service = ExtractionService(gemini_client=client)
    else:
        effective_service = extraction_service

    # 7. Execute extraction and chunk-level validation
    chunk_records = []
    chunk_payloads = []
    for chunk in target_chunks:
        try:
            run_record = effective_service.extract_and_validate(
                segments=segments,
                chunks=[chunk],
                run_number=1,
            )
            chunk_records.append(run_record)
            if run_record.candidate_payload:
                chunk_payloads.append(run_record.candidate_payload)
        except Exception as exc:
            safe_err = _redact_secrets(str(exc))
            err_msg = f"Extraction provider error for chunk {chunk.chunk_index}: {safe_err}"
            logger.error(err_msg)
            report = {
                "status": "error",
                "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
                "transcript_source": source_classification,
                "provider": provider,
                "model_id": model_id,
                "counts": {"segments": len(segments), "chunks": len(chunks)},
                "selected_chunk": selected_chunk_info,
                "validation": {
                    "schema_valid": False,
                    "evidence_grounded": False,
                    "provenance_valid": False,
                    "error_count": 1,
                    "warning_count": 0,
                    "errors": [{"severity": "error", "error_code": "PROVIDER_ERROR", "message": err_msg}],
                },
                "disclaimer": (
                    "Notice: Successful structural and evidence validation does not prove factual accuracy, "
                    "speaker authenticity, or Amharic extraction quality. All candidate items require human "
                    "editorial review before approval or publication."
                ),
            }
            _emit_validation_report(report, output_file)
            return 2

    # 8. Reconcile multi-chunk candidate payloads
    all_validation_errors: List[Dict[str, Any]] = []
    has_syntactic_error = False
    has_semantic_error = False

    SYNTACTIC_ERROR_CODES = {
        ValidationErrorCode.MALFORMED_JSON,
        ValidationErrorCode.SCHEMA_VIOLATION,
        ValidationErrorCode.MISSING_REQUIRED_KEY,
        ValidationErrorCode.TYPE_MISMATCH,
        ValidationErrorCode.INVALID_CATEGORY,
        ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
        ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS,
    }

    for r in chunk_records:
        if r.candidate_payload is None and not any(
            err.error_code in SYNTACTIC_ERROR_CODES for err in r.validation_errors
        ):
            has_syntactic_error = True

        for err in r.validation_errors:
            err_dict = {
                "severity": err.severity.value if hasattr(err.severity, "value") else str(err.severity),
                "error_code": err.error_code.value if hasattr(err.error_code, "value") else str(err.error_code),
                "item_type": err.item_type,
                "item_index": err.item_index,
                "field": err.field,
                "message": err.message,
            }
            all_validation_errors.append(err_dict)
            if err.severity == ValidationSeverity.ERROR:
                if err.error_code in SYNTACTIC_ERROR_CODES:
                    has_syntactic_error = True
                else:
                    has_semantic_error = True

    reconciled_payload = None
    if chunk_payloads and not has_syntactic_error:
        try:
            reconciler = CandidateReconciler()
            reconciliation_res = reconciler.reconcile_payloads(chunk_payloads)
            reconciled_payload = reconciliation_res.payload
        except Exception as exc:
            has_semantic_error = True
            safe_err = _redact_secrets(str(exc))
            all_validation_errors.append({
                "severity": "error",
                "error_code": "RECONCILIATION_ERROR",
                "item_type": "payload",
                "item_index": None,
                "field": None,
                "message": f"Multi-chunk candidate reconciliation failed: {safe_err}",
            })

    # 9. In-memory provenance validation against source segments
    provenance_valid = True
    if reconciled_payload is not None:
        try:
            segment_index_to_id = {s.segment_index: f"seg-{s.segment_index}" for s in segments}
            CandidatePersistenceService.validate_candidate_payload_references(
                payload=reconciled_payload,
                segment_index_to_id=segment_index_to_id,
            )
        except Exception as exc:
            provenance_valid = False
            has_semantic_error = True
            safe_err = _redact_secrets(str(exc))
            all_validation_errors.append({
                "severity": "error",
                "error_code": "SEGMENT_REFERENCE_INTEGRITY_ERROR",
                "item_type": "evidence",
                "item_index": None,
                "field": "evidence_references",
                "message": f"Segment provenance validation failed: {safe_err}",
            })

        if len(reconciled_payload.insights) == 0 and len(reconciled_payload.quotations) == 0:
            has_semantic_error = True
            all_validation_errors.append({
                "severity": "error",
                "error_code": "EMPTY_EXTRACTED_CONTENT",
                "item_type": "payload",
                "item_index": None,
                "field": None,
                "message": "Extraction yielded zero insights and zero quotations across all chunks.",
            })
    else:
        if not has_syntactic_error:
            has_semantic_error = True
            all_validation_errors.append({
                "severity": "error",
                "error_code": "NO_CANDIDATE_PAYLOAD",
                "item_type": "payload",
                "item_index": None,
                "field": None,
                "message": "Extraction produced no candidate payload.",
            })

    schema_valid = not has_syntactic_error
    evidence_grounded = (not has_semantic_error) and provenance_valid and (reconciled_payload is not None)

    if schema_valid and evidence_grounded:
        overall_status = "passed"
        exit_code = 0
    else:
        overall_status = "validation_failed"
        exit_code = 1

    counts = {
        "segments": len(segments),
        "chunks": len(chunks),
        "evaluated_chunks": len(target_chunks),
        "insights": len(reconciled_payload.insights) if reconciled_payload else 0,
        "quotations": len(reconciled_payload.quotations) if reconciled_payload else 0,
        "evidence_references": len(reconciled_payload.evidence_references) if reconciled_payload else 0,
        "quotation_segments": len(reconciled_payload.quotation_segments) if reconciled_payload else 0,
        "milestones": len(reconciled_payload.journey_milestones) if reconciled_payload else 0,
        "has_episode_summary": bool(reconciled_payload.episode_summary and reconciled_payload.episode_summary.brief) if reconciled_payload else False,
        "has_guest_profile": bool(reconciled_payload.guest_profile and reconciled_payload.guest_profile.name) if reconciled_payload else False,
    }

    report = {
        "status": overall_status,
        "run_mode": "gemini_live" if provider == "gemini" else "offline_fake",
        "transcript_source": source_classification,
        "provider": provider,
        "model_id": model_id,
        "counts": counts,
        "selected_chunk": selected_chunk_info,
        "validation": {
            "schema_valid": schema_valid,
            "evidence_grounded": evidence_grounded,
            "provenance_valid": provenance_valid,
            "error_count": len([e for e in all_validation_errors if e.get("severity") == "error"]),
            "warning_count": len([e for e in all_validation_errors if e.get("severity") == "warning"]),
            "errors": all_validation_errors,
        },
        "disclaimer": (
            "Notice: Successful structural and evidence validation does not prove factual accuracy, "
            "speaker authenticity, or Amharic extraction quality. All candidate items require human "
            "editorial review before approval or publication."
        ),
    }

    if getattr(args, "include_raw_responses", False):
        report["raw_responses"] = [
            _redact_secrets(r.raw_response_json)
            for r in chunk_records
            if r.raw_response_json
        ]

    _emit_validation_report(report, output_file)
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    """Builds and returns the ArgumentParser for the pipeline CLI."""
    parser = argparse.ArgumentParser(
        prog="python3 -m backend.src.pipeline_cli",
        description="Meri Content Pipeline Ingestion Worker CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: run-job <job_id>
    job_parser = subparsers.add_parser("run-job", help="Process a specific job by UUID")
    job_parser.add_argument("job_id", help="UUID of the processing job")
    job_parser.add_argument(
        "--transcript-file",
        help="Path to transcript file (JSON, SRT, WebVTT) if not fetching dynamically",
    )
    job_parser.add_argument(
        "--confirm-youtube-video-id",
        help="Explicit operator confirmation of the expected YouTube video ID matching the job and episode (required for local transcript ingestion)",
    )
    job_parser.add_argument(
        "--allow-rerun",
        action="store_true",
        help="Permit replacing unreviewed candidate staging data if rerun",
    )

    # Subcommand: run-next
    next_parser = subparsers.add_parser("run-next", help="Process the next pending job from the queue")
    next_parser.add_argument(
        "--transcript-file",
        help="Path to transcript file (JSON, SRT, WebVTT) if not fetching dynamically",
    )
    next_parser.add_argument(
        "--confirm-youtube-video-id",
        help="Explicit operator confirmation of the expected YouTube video ID matching the job and episode (required for local transcript ingestion)",
    )
    next_parser.add_argument(
        "--allow-rerun",
        action="store_true",
        help="Permit replacing unreviewed candidate staging data if rerun",
    )

    # Subcommand: check-env
    subparsers.add_parser("check-env", help="Check database driver and environment configuration")

    # Subcommand: check-db
    db_check_parser = subparsers.add_parser(
        "check-db",
        help="Perform a read-only database connectivity and schema health check",
    )
    db_check_parser.add_argument(
        "--db-url",
        help="Optional PostgreSQL connection URI (defaults to DATABASE_URL environment variable)",
    )

    # Subcommand: validate-extraction
    val_parser = subparsers.add_parser(
        "validate-extraction",
        help="Safely validate transcript extraction, schema, and evidence rules in isolation without database persistence",
    )
    val_parser.add_argument(
        "--transcript-file",
        required=True,
        help="Path to transcript file (JSON, SRT, WebVTT) to validate",
    )
    val_parser.add_argument(
        "--provider",
        choices=["fake", "gemini"],
        default="fake",
        help="Extraction provider to use: 'fake' (deterministic offline test provider, default) or 'gemini' (live API)",
    )
    val_parser.add_argument(
        "--allow-network",
        action="store_true",
        default=False,
        help="Explicit network opt-in flag required when using '--provider gemini'. Never used for fake provider.",
    )
    val_parser.add_argument(
        "--model-id",
        default="gemini-2.0-flash",
        help="Gemini model identifier (default: gemini-2.0-flash)",
    )
    val_parser.add_argument(
        "--output-file",
        help="Optional local file path to write the redacted JSON validation report",
    )
    val_parser.add_argument(
        "--format-hint",
        choices=["json", "srt", "vtt"],
        help="Optional format hint for transcript parser",
    )
    val_parser.add_argument(
        "--request-timeout",
        type=float,
        default=None,
        help="Timeout in seconds for provider requests (defaults to GEMINI_TIMEOUT_SECONDS or 60.0s)",
    )
    val_parser.add_argument(
        "--reconstruct-rolling",
        action="store_true",
        default=False,
        help="Enable provenance-preserving reconstruction for rolling-caption transcripts (e.g. YouTube auto-captions)",
    )
    val_parser.add_argument(
        "--chunk-index",
        type=int,
        default=None,
        help="Optional zero-based chunk index to validate in isolation (default: validate all chunks)",
    )
    val_parser.add_argument(
        "--include-raw-responses",
        "--include-raw-response",
        action="store_true",
        dest="include_raw_responses",
        default=False,
        help="Include redacted raw provider responses in the report (default: False to protect transcript-derived data)",
    )

    # Subcommand: prepare-editorial-review
    review_parser = subparsers.add_parser(
        "prepare-editorial-review",
        help="Prepare a local, human-reviewable editorial package from staged candidate JSON and transcript evidence",
    )
    review_parser.add_argument(
        "--transcript-file",
        required=True,
        help="Path to transcript file (JSON, SRT, WebVTT)",
    )
    review_parser.add_argument(
        "--candidate-file",
        required=True,
        help="Path to candidate staging JSON file",
    )
    review_parser.add_argument(
        "--output-file",
        required=True,
        help="Path to write the human-reviewable editorial package JSON",
    )
    review_parser.add_argument(
        "--reconstruct-rolling",
        action="store_true",
        default=False,
        help="Enable provenance-preserving reconstruction for rolling-caption transcripts",
    )
    review_parser.add_argument(
        "--format-hint",
        choices=["json", "srt", "vtt"],
        help="Optional format hint for transcript parser",
    )
    review_parser.add_argument(
        "--sponsor-start",
        type=int,
        default=15,
        help="Start segment index for sponsor-advertisement heuristic range (default: 15)",
    )
    review_parser.add_argument(
        "--sponsor-end",
        type=int,
        default=44,
        help="End segment index for sponsor-advertisement heuristic range (default: 44)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-env":
        driver = get_db_driver()
        print(f"PostgreSQL Driver: {driver or 'NOT INSTALLED'}")
        db_url = os.environ.get("DATABASE_URL")
        print(f"DATABASE_URL: {_redact_secrets(db_url) if db_url else 'NOT SET'}")
        has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
        print(f"GEMINI_API_KEY: {'CONFIGURED' if has_gemini else 'NOT SET'}")
        return 0 if driver else 1

    if args.command == "check-db":
        db_url = getattr(args, "db_url", None) or os.environ.get("DATABASE_URL")
        if not db_url:
            logger.error("DATABASE_URL is not set and no --db-url argument provided.")
            print(json.dumps({
                "status": "failed",
                "errors": ["DATABASE_URL is not set and no --db-url argument provided."],
                "resolution": "Provide DATABASE_URL in .env or as environment variable: postgresql://[user]:[password]@[host]:[port]/[database]"
            }, indent=2))
            return 1
        try:
            conn_factory = create_connection_factory(database_url=db_url)
        except RuntimeError as err:
            logger.error("%s", _redact_secrets(str(err)))
            print(json.dumps({
                "status": "failed",
                "errors": [_redact_secrets(str(err))]
            }, indent=2))
            return 1
        report = run_db_health_check(conn_factory)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "healthy" else 1

    if args.command == "validate-extraction":
        return run_validate_extraction(args)

    if args.command == "prepare-editorial-review":
        try:
            from .editorial_review_preparer import EditorialReviewPreparer
        except ImportError:
            from backend.src.editorial_review_preparer import EditorialReviewPreparer

        preparer = EditorialReviewPreparer(
            sponsor_range=(getattr(args, "sponsor_start", 15), getattr(args, "sponsor_end", 44))
        )
        result = preparer.prepare_review(
            transcript_path=args.transcript_file,
            candidate_staging_path=args.candidate_file,
            output_path=args.output_file,
            reconstruct_rolling=bool(getattr(args, "reconstruct_rolling", False)),
            format_hint=getattr(args, "format_hint", None),
        )
        print(json.dumps(result.report, indent=2, ensure_ascii=False))
        return result.exit_code

    raw_confirm = getattr(args, "confirm_youtube_video_id", None)
    confirm_video_id = raw_confirm.strip() if (raw_confirm and isinstance(raw_confirm, str)) else None
    if getattr(args, "transcript_file", None) and not confirm_video_id:
        logger.error(
            "Local transcript ingestion via --transcript-file requires explicit operator confirmation "
            "of the expected YouTube video ID using --confirm-youtube-video-id <video_id>."
        )
        return 1

    try:
        connection_factory = create_connection_factory()
    except RuntimeError as err:
        logger.error("%s", _redact_secrets(str(err)))
        return 1

    try:
        transcript_provider = create_transcript_provider(getattr(args, "transcript_file", None))
    except Exception as err:
        logger.error("Failed to load transcript: %s", err)
        return 1

    worker = JobWorker(
        connection_factory=connection_factory,
        transcript_provider=transcript_provider,
    )

    allow_rerun = bool(getattr(args, "allow_rerun", False))

    if args.command == "run-job":
        logger.info("Executing job %s (allow_rerun=%s)", args.job_id, allow_rerun)
        result = worker.process_job(
            args.job_id,
            allow_candidate_rerun=allow_rerun,
            confirm_youtube_video_id=confirm_video_id,
        )
    elif args.command == "run-next":
        logger.info("Executing next pending job (allow_rerun=%s)", allow_rerun)
        result = worker.process_next_job(
            allow_candidate_rerun=allow_rerun,
            confirm_youtube_video_id=confirm_video_id,
        )
    else:
        logger.error("Unknown command: %s", args.command)
        return 1

    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status in ("completed", "idle") else 1


if __name__ == "__main__":
    sys.exit(main())
