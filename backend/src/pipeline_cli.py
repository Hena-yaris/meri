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
import sys
from typing import Any, Callable, Optional, Union

from .job_worker import (
    JobWorker,
    JobWorkerResult,
    StaticTranscriptProvider,
    TranscriptProvider,
)
from .pipeline_orchestrator import _redact_secrets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("meri.pipeline_cli")


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
    return parser


def main(argv: Optional[list] = None) -> int:
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
        logger.error(str(err))
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
