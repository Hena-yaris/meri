"""
Meri Content Pipeline v1: Ingestion Job Worker Service.

Claims and processes pending ingestion jobs from `processing_jobs` using PostgreSQL
`FOR UPDATE SKIP LOCKED` and executes the `PipelineOrchestrator`.

Key Safety & Concurrency Guarantees:
1. Short atomic claim transaction commits before transcript acquisition or Gemini calls begin.
2. Row locks and write transactions are NEVER held during remote LLM extraction.
3. Multiple workers cannot claim the same pending job concurrently.
4. Non-retryable errors (input, validation, editorial protection) fail immediately without retries.
5. Transient network/extraction errors are retried up to job.max_retries.
6. Error summaries and exception details are strictly redacted before database persistence.
7. Candidate persistence executes via orchestrator's deferred connection factory.
8. Deferral of stale-job reclamation without worker-lease fencing to prevent split-brain commits.
"""

from dataclasses import dataclass, field
import datetime
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Protocol, Union

from .gemini_client import (
    GeminiRateLimitError,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
)
from .pipeline_orchestrator import (
    EditorialProtectionError,
    PipelineExecutionResult,
    PipelineExtractionError,
    PipelineInputError,
    PipelineOrchestrator,
    PipelineOrchestratorError,
    PipelinePersistenceError,
    PipelineValidationError,
    _redact_secrets,
)

logger = logging.getLogger(__name__)


class JobWorkerError(Exception):
    """Base exception for job worker operational failures."""
    pass


class JobClaimError(JobWorkerError):
    """Raised when job claim fails or row is locked/unavailable."""
    pass


@dataclass(frozen=True)
class ProcessingJobRecord:
    """Represents a row from the processing_jobs table."""
    id: str
    episode_id: Optional[str]
    youtube_url: str
    youtube_video_id: str
    status: str
    current_stage: str
    retry_count: int
    max_retries: int
    error_summary: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    stage_timings: Optional[Dict[str, Any]] = None
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None
    completed_at: Optional[Any] = None


@dataclass(frozen=True)
class JobWorkerResult:
    """Structured outcome of a job worker execution cycle."""
    processed: bool
    job_id: Optional[str]
    status: str  # 'completed', 'retry_scheduled', 'failed', 'idle', 'rejected'
    stage: Optional[str]
    retry_count: int
    error: Optional[str] = None
    pipeline_result: Optional[PipelineExecutionResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "processed": self.processed,
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "retry_count": self.retry_count,
            "error": self.error,
            "pipeline_result": self.pipeline_result.to_dict() if self.pipeline_result else None,
        }


class TranscriptProvider(Protocol):
    """Protocol for acquiring source transcript content for a claimed job."""

    def get_transcript(self, job: ProcessingJobRecord) -> Union[str, Dict[str, Any], List[Any]]:
        """
        Retrieves transcript text or structured JSON cues for the given job.

        Raises:
            Exception: If transcript acquisition fails.
        """
        ...


class StaticTranscriptProvider:
    """Simple transcript provider returning pre-configured content or mapping by video_id."""

    def __init__(
        self,
        default_content: Optional[Union[str, Dict[str, Any], List[Any]]] = None,
        video_id_to_content: Optional[Dict[str, Union[str, Dict[str, Any], List[Any]]]] = None,
        requires_confirmation: bool = False,
    ) -> None:
        self.default_content = default_content
        self.video_id_to_content = video_id_to_content or {}
        self.requires_confirmation = requires_confirmation

    def get_transcript(self, job: ProcessingJobRecord) -> Union[str, Dict[str, Any], List[Any]]:
        if job.youtube_video_id in self.video_id_to_content:
            return self.video_id_to_content[job.youtube_video_id]
        if self.default_content is not None:
            return self.default_content
        raise JobWorkerError(f"No transcript found for video_id: {job.youtube_video_id}")


class JobWorker:
    """
    Ingestion Worker Service executing jobs from processing_jobs through PipelineOrchestrator.
    """

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        transcript_provider: Optional[TranscriptProvider] = None,
        orchestrator: Optional[PipelineOrchestrator] = None,
        custom_logger: Optional[logging.Logger] = None,
    ) -> None:
        self.connection_factory = connection_factory
        self.transcript_provider = transcript_provider
        self.orchestrator = orchestrator or PipelineOrchestrator()
        self.logger = custom_logger or logger

    def process_next_job(
        self,
        allow_candidate_rerun: bool = False,
        confirm_youtube_video_id: Optional[str] = None,
        require_confirmation: bool = False,
    ) -> JobWorkerResult:
        """
        Claims and processes the next eligible pending job from the queue.

        Uses PostgreSQL FOR UPDATE SKIP LOCKED to ensure atomic claiming without races.
        Returns JobWorkerResult with processed=False if queue is idle.
        """
        # Step 1: Claim one pending job in a short atomic transaction
        job = self._claim_next_job()
        if job is None:
            return JobWorkerResult(
                processed=False,
                job_id=None,
                status="idle",
                stage=None,
                retry_count=0,
            )

        # Step 2: Execute processing lifecycle on claimed job
        return self._execute_claimed_job(
            job,
            allow_candidate_rerun=allow_candidate_rerun,
            confirm_youtube_video_id=confirm_youtube_video_id,
            require_confirmation=require_confirmation,
        )

    def process_job(
        self,
        job_id: str,
        allow_candidate_rerun: bool = False,
        confirm_youtube_video_id: Optional[str] = None,
        require_confirmation: bool = False,
    ) -> JobWorkerResult:
        """
        Claims and processes a specific eligible job by ID if currently pending.

        Uses atomic conditional UPDATE ... FOR UPDATE SKIP LOCKED to prevent races.
        """
        if not job_id or not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id must be a non-empty string.")

        # Step 1: Claim specific job in short atomic transaction
        job = self._claim_job_by_id(job_id.strip())
        if job is None:
            return JobWorkerResult(
                processed=False,
                job_id=job_id,
                status="rejected",
                stage=None,
                retry_count=0,
                error=f"Job {job_id} is not in 'pending' status or is currently claimed by another worker.",
            )

        # Step 2: Execute processing lifecycle on claimed job
        return self._execute_claimed_job(
            job,
            allow_candidate_rerun=allow_candidate_rerun,
            confirm_youtube_video_id=confirm_youtube_video_id,
            require_confirmation=require_confirmation,
        )

    def _claim_next_job(self) -> Optional[ProcessingJobRecord]:
        """
        Executes a short claim transaction for the next available pending job.
        Commits immediately upon claiming before any external AI or transcript calls.
        """
        conn = self.connection_factory()
        cursor = conn.cursor() if hasattr(conn, "cursor") and callable(conn.cursor) else conn
        try:
            claim_sql = """
            WITH claimable AS (
                SELECT id
                FROM processing_jobs
                WHERE status = 'pending'::processing_job_status
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE processing_jobs
            SET status = 'processing'::processing_job_status,
                current_stage = 'transcript_acquisition'::processing_stage,
                updated_at = now()
            FROM claimable
            WHERE processing_jobs.id = claimable.id
            RETURNING processing_jobs.id, processing_jobs.episode_id, processing_jobs.youtube_url,
                      processing_jobs.youtube_video_id, processing_jobs.status, processing_jobs.current_stage,
                      processing_jobs.retry_count, processing_jobs.max_retries;
            """
            cursor.execute(claim_sql)
            row = cursor.fetchone()
            if hasattr(conn, "commit") and callable(conn.commit):
                conn.commit()

            if not row:
                return None

            return ProcessingJobRecord(
                id=str(row[0]),
                episode_id=str(row[1]) if row[1] else None,
                youtube_url=str(row[2]),
                youtube_video_id=str(row[3]),
                status=str(row[4]),
                current_stage=str(row[5]),
                retry_count=int(row[6]),
                max_retries=int(row[7]),
            )
        except Exception as exc:
            if hasattr(conn, "rollback") and callable(conn.rollback):
                conn.rollback()
            safe_err = _redact_secrets(str(exc))
            self.logger.error("Job claim transaction failed: %s", safe_err)
            raise JobClaimError(f"Failed to claim next pending job: {safe_err}") from exc
        finally:
            self._close_db_resource(cursor, conn)
            self._close_db_resource(conn)

    def _claim_job_by_id(self, job_id: str) -> Optional[ProcessingJobRecord]:
        """
        Executes a short conditional claim transaction for a specific pending job ID.
        Commits immediately upon claiming.
        """
        conn = self.connection_factory()
        cursor = conn.cursor() if hasattr(conn, "cursor") and callable(conn.cursor) else conn
        try:
            claim_sql = """
            WITH claimable AS (
                SELECT id
                FROM processing_jobs
                WHERE id = %s AND status = 'pending'::processing_job_status
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE processing_jobs
            SET status = 'processing'::processing_job_status,
                current_stage = 'transcript_acquisition'::processing_stage,
                updated_at = now()
            FROM claimable
            WHERE processing_jobs.id = claimable.id
            RETURNING processing_jobs.id, processing_jobs.episode_id, processing_jobs.youtube_url,
                      processing_jobs.youtube_video_id, processing_jobs.status, processing_jobs.current_stage,
                      processing_jobs.retry_count, processing_jobs.max_retries;
            """
            cursor.execute(claim_sql, (job_id,))
            row = cursor.fetchone()
            if hasattr(conn, "commit") and callable(conn.commit):
                conn.commit()

            if not row:
                return None

            return ProcessingJobRecord(
                id=str(row[0]),
                episode_id=str(row[1]) if row[1] else None,
                youtube_url=str(row[2]),
                youtube_video_id=str(row[3]),
                status=str(row[4]),
                current_stage=str(row[5]),
                retry_count=int(row[6]),
                max_retries=int(row[7]),
            )
        except Exception as exc:
            if hasattr(conn, "rollback") and callable(conn.rollback):
                conn.rollback()
            safe_err = _redact_secrets(str(exc))
            self.logger.error("Explicit job claim transaction failed for job %s: %s", job_id, safe_err)
            raise JobClaimError(f"Failed to claim job {job_id}: {safe_err}") from exc
        finally:
            self._close_db_resource(cursor, conn)
            self._close_db_resource(conn)

    def _execute_claimed_job(
        self,
        job: ProcessingJobRecord,
        allow_candidate_rerun: bool,
        confirm_youtube_video_id: Optional[str] = None,
        require_confirmation: bool = False,
    ) -> JobWorkerResult:
        """
        Executes transcript acquisition and pipeline orchestration for a claimed job.
        Handles failures and retries in separate short transactions.
        """
        self.logger.info("Processing claimed job %s (episode: %s)", job.id, job.episode_id)

        # 1. Enforce episode_id presence
        if not job.episode_id:
            error_msg = "Missing episode_id: processing_jobs record has no associated episode."
            self._record_job_failure(
                job_id=job.id,
                stage="submission",
                error_message=error_msg,
                retryable=False,
                current_retries=job.retry_count,
                max_retries=job.max_retries,
            )
            return JobWorkerResult(
                processed=True,
                job_id=job.id,
                status="failed",
                stage="submission",
                retry_count=job.retry_count,
                error=error_msg,
            )

        # 1.1 Explicit operator confirmation of YouTube video ID for local transcripts
        if confirm_youtube_video_id is not None:
            raw_stripped = confirm_youtube_video_id.strip() if isinstance(confirm_youtube_video_id, str) else ""
            if not raw_stripped:
                error_msg = (
                    "Operator confirmation of YouTube video ID cannot be empty or whitespace-only."
                )
                self._record_job_failure(
                    job_id=job.id,
                    stage="submission",
                    error_message=error_msg,
                    retryable=False,
                    current_retries=job.retry_count,
                    max_retries=job.max_retries,
                )
                return JobWorkerResult(
                    processed=True,
                    job_id=job.id,
                    status="failed",
                    stage="submission",
                    retry_count=job.retry_count,
                    error=error_msg,
                )
            clean_confirmed_id = raw_stripped
        else:
            clean_confirmed_id = None

        needs_confirmation = require_confirmation or getattr(self.transcript_provider, "requires_confirmation", False)
        if needs_confirmation and not clean_confirmed_id:
            error_msg = (
                "Local transcript ingestion requires explicit operator confirmation of the expected "
                "YouTube video ID (via confirm_youtube_video_id / --confirm-youtube-video-id)."
            )
            self._record_job_failure(
                job_id=job.id,
                stage="submission",
                error_message=error_msg,
                retryable=False,
                current_retries=job.retry_count,
                max_retries=job.max_retries,
            )
            return JobWorkerResult(
                processed=True,
                job_id=job.id,
                status="failed",
                stage="submission",
                retry_count=job.retry_count,
                error=error_msg,
            )

        if clean_confirmed_id is not None:
            if clean_confirmed_id != job.youtube_video_id:
                error_msg = (
                    f"Confirmed YouTube video ID '{clean_confirmed_id}' does not match "
                    f"job's registered YouTube video ID '{job.youtube_video_id}'."
                )
                self._record_job_failure(
                    job_id=job.id,
                    stage="submission",
                    error_message=error_msg,
                    retryable=False,
                    current_retries=job.retry_count,
                    max_retries=job.max_retries,
                )
                return JobWorkerResult(
                    processed=True,
                    job_id=job.id,
                    status="failed",
                    stage="submission",
                    retry_count=job.retry_count,
                    error=error_msg,
                )
        # 1.2 Read-only Pre-Gemini Editorial Preflight Check
        preflight_conn = self.connection_factory()
        preflight_cursor = (
            preflight_conn.cursor()
            if hasattr(preflight_conn, "cursor") and callable(preflight_conn.cursor)
            else preflight_conn
        )
        try:
            self.orchestrator.check_editorial_preflight(
                cursor=preflight_cursor,
                episode_id=job.episode_id,
                allow_candidate_rerun=allow_candidate_rerun,
                expected_youtube_video_id=job.youtube_video_id,
            )
        except Exception as exc:
            safe_err = _redact_secrets(str(exc))
            is_retryable = self._is_retryable_error(exc)
            failure_stage = self._classify_failure_stage(exc)
            new_status = self._record_job_failure(
                job_id=job.id,
                stage=failure_stage,
                error_message=safe_err,
                retryable=is_retryable,
                current_retries=job.retry_count,
                max_retries=job.max_retries,
            )
            return JobWorkerResult(
                processed=True,
                job_id=job.id,
                status=new_status,
                stage=failure_stage,
                retry_count=job.retry_count,
                error=safe_err,
            )
        finally:
            self._close_db_resource(preflight_cursor, preflight_conn)
            self._close_db_resource(preflight_conn)

        # 2. Acquire transcript content via injected provider
        if self.transcript_provider is None:
            error_msg = "No transcript provider configured on worker: cannot acquire transcript."
            self._record_job_failure(
                job_id=job.id,
                stage="transcript_acquisition",
                error_message=error_msg,
                retryable=False,
                current_retries=job.retry_count,
                max_retries=job.max_retries,
            )
            return JobWorkerResult(
                processed=True,
                job_id=job.id,
                status="failed",
                stage="transcript_acquisition",
                retry_count=job.retry_count,
                error=error_msg,
            )

        try:
            transcript_content = self.transcript_provider.get_transcript(job)
        except Exception as exc:
            safe_err = _redact_secrets(str(exc))
            error_msg = f"Transcript acquisition failed: {safe_err}"
            is_retryable = self._is_retryable_error(exc)
            new_status = self._record_job_failure(
                job_id=job.id,
                stage="transcript_acquisition",
                error_message=error_msg,
                retryable=is_retryable,
                current_retries=job.retry_count,
                max_retries=job.max_retries,
            )
            return JobWorkerResult(
                processed=True,
                job_id=job.id,
                status=new_status,
                stage="transcript_acquisition",
                retry_count=job.retry_count + (1 if new_status == "retry_scheduled" else 0),
                error=error_msg,
            )

        if transcript_content is None or (isinstance(transcript_content, str) and not transcript_content.strip()):
            error_msg = "Acquired transcript content is empty or whitespace."
            self._record_job_failure(
                job_id=job.id,
                stage="transcript_acquisition",
                error_message=error_msg,
                retryable=False,
                current_retries=job.retry_count,
                max_retries=job.max_retries,
            )
            return JobWorkerResult(
                processed=True,
                job_id=job.id,
                status="failed",
                stage="transcript_acquisition",
                retry_count=job.retry_count,
                error=error_msg,
            )

        # 3. Transition stage to ai_extraction in short transaction before long-running calls
        self._update_stage(job.id, "ai_extraction")

        # 4. Execute PipelineOrchestrator with deferred connection factory
        try:
            pipeline_res = self.orchestrator.run(
                job_id=job.id,
                episode_id=job.episode_id,
                transcript_content=transcript_content,
                connection_factory=self.connection_factory,
                allow_candidate_rerun=allow_candidate_rerun,
                expected_youtube_video_id=job.youtube_video_id,
            )

            self.logger.info("Job %s completed successfully: %s", job.id, pipeline_res.status)
            return JobWorkerResult(
                processed=True,
                job_id=job.id,
                status="completed",
                stage="human_review",
                retry_count=job.retry_count,
                pipeline_result=pipeline_res,
            )

        except Exception as exc:
            safe_err = _redact_secrets(str(exc))
            is_retryable = self._is_retryable_error(exc)
            failure_stage = self._classify_failure_stage(exc)

            new_status = self._record_job_failure(
                job_id=job.id,
                stage=failure_stage,
                error_message=safe_err,
                retryable=is_retryable,
                current_retries=job.retry_count,
                max_retries=job.max_retries,
            )

            return JobWorkerResult(
                processed=True,
                job_id=job.id,
                status=new_status,
                stage=failure_stage,
                retry_count=job.retry_count + (1 if new_status == "retry_scheduled" else 0),
                error=safe_err,
            )

    def _update_stage(self, job_id: str, stage: str) -> None:
        """Updates current_stage for a job in a short independent transaction."""
        conn = self.connection_factory()
        cursor = conn.cursor() if hasattr(conn, "cursor") and callable(conn.cursor) else conn
        try:
            cursor.execute(
                """
                UPDATE processing_jobs
                SET current_stage = %s::processing_stage,
                    updated_at = now()
                WHERE id = %s;
                """,
                (stage, job_id),
            )
            if hasattr(conn, "commit") and callable(conn.commit):
                conn.commit()
        except Exception as exc:
            self.logger.warning("Stage update to '%s' failed for job %s: %s", stage, job_id, exc)
        finally:
            self._close_db_resource(cursor, conn)
            self._close_db_resource(conn)

    def _record_job_failure(
        self,
        job_id: str,
        stage: str,
        error_message: str,
        retryable: bool,
        current_retries: int,
        max_retries: int,
    ) -> str:
        """
        Records failure or schedules retry in a separate short transaction.

        Returns:
            'retry_scheduled' if job was rescheduled to 'pending', or 'failed' if retries exhausted/non-retryable.
        """
        # Truncate error message safely to fit column without bloating
        clean_error = _redact_secrets(error_message)[:500]

        # Determine whether retry is permitted
        can_retry = retryable and (current_retries < max_retries)
        new_status = "pending" if can_retry else "failed"

        conn = self.connection_factory()
        cursor = conn.cursor() if hasattr(conn, "cursor") and callable(conn.cursor) else conn
        try:
            if can_retry:
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'pending'::processing_job_status,
                        current_stage = %s::processing_stage,
                        retry_count = retry_count + 1,
                        error_summary = %s,
                        updated_at = now()
                    WHERE id = %s;
                    """,
                    (stage, clean_error, job_id),
                )
                outcome = "retry_scheduled"
            else:
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'failed'::processing_job_status,
                        current_stage = %s::processing_stage,
                        error_summary = %s,
                        completed_at = now(),
                        updated_at = now()
                    WHERE id = %s;
                    """,
                    (stage, clean_error, job_id),
                )
                outcome = "failed"

            if hasattr(conn, "commit") and callable(conn.commit):
                conn.commit()
            return outcome
        except Exception as exc:
            if hasattr(conn, "rollback") and callable(conn.rollback):
                conn.rollback()
            safe_err = _redact_secrets(str(exc))
            self.logger.error("Failed to record failure state for job %s: %s", job_id, safe_err)
            return "failed"
        finally:
            self._close_db_resource(cursor, conn)
            self._close_db_resource(conn)

    def _is_retryable_error(self, exc: Exception) -> bool:
        """
        Determines whether a failure is transient and eligible for retry.

        Rules:
        - Non-retryable: PipelineInputError, EditorialProtectionError, PipelineValidationError, ValueError, TypeError.
        - Non-retryable: PipelinePersistenceError (handled conservatively to avoid blind re-extraction).
        - Retryable: Transient Gemini network/service errors (503, timeout, rate limit, socket drops).
        """
        # Explicit non-retryable exception types
        if isinstance(exc, (PipelineInputError, EditorialProtectionError, PipelineValidationError, ValueError, TypeError)):
            return False

        # Conservative persistence policy: do not rerun extraction on database constraint or persistence failure
        if isinstance(exc, PipelinePersistenceError):
            return False

        # Check for transient network/LLM errors
        cause = getattr(exc, "__cause__", None) or exc
        if isinstance(cause, (GeminiTimeoutError, GeminiServiceUnavailableError, GeminiRateLimitError, TimeoutError, ConnectionError, OSError)):
            return True

        msg = str(exc).lower()
        if any(term in msg for term in ["timed out", "timeout", "503", "service unavailable", "connection reset", "broken pipe"]):
            return True

        return False

    def _classify_failure_stage(self, exc: Exception) -> str:
        """Maps an exception to the appropriate processing_stage enum value."""
        if isinstance(exc, PipelineInputError):
            return "submission"
        if isinstance(exc, PipelineValidationError):
            return "validation"
        if isinstance(exc, EditorialProtectionError):
            return "human_review"
        if isinstance(exc, PipelinePersistenceError):
            return "human_review"
        if isinstance(exc, PipelineExtractionError):
            msg = str(exc).lower()
            if "parsing" in msg:
                return "transcript_acquisition"
            if "normalization" in msg:
                return "transcript_normalization"
            if "chunking" in msg:
                return "chunking"
            return "ai_extraction"
        return "ai_extraction"

    @staticmethod
    def _close_db_resource(resource: Any, parent: Any = None) -> None:
        """Safely closes a cursor or connection without raising exceptions."""
        if resource is not None and resource is not parent and hasattr(resource, "close") and callable(resource.close):
            try:
                resource.close()
            except Exception:
                pass
