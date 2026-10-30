"""
Meri Content Pipeline v1: Unit tests for JobWorker.

Verifies Milestone 4 Step 4.3 requirements:
1. Claiming one pending job.
2. No pending job available.
3. Two workers cannot claim the same job (concurrency / SKIP LOCKED simulation).
4. Claim transaction ends before Gemini / orchestrator is called.
5. Successful completion.
6. Retryable failure and retry-count limits.
7. Non-retryable validation or editorial failure.
8. Persistence failure and conservative failure handling.
9. Missing episode or transcript input.
10. Safe error-summary redaction in database updates.
11. Invalid state transitions / non-pending job claim rejection.
12. Stale-job policy: no premature reclamation without ownership fencing.
"""

import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import unittest

from backend.src.extraction_models import ValidationStatus
from backend.src.gemini_client import (
    GeminiRateLimitError,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
)
from backend.src.job_worker import (
    JobClaimError,
    JobWorker,
    JobWorkerResult,
    ProcessingJobRecord,
    StaticTranscriptProvider,
)
from backend.src.pipeline_orchestrator import (
    EditorialProtectionError,
    PipelineExecutionResult,
    PipelineExtractionError,
    PipelineInputError,
    PipelineOrchestrator,
    PipelinePersistenceError,
    PipelineValidationError,
)


class MockWorkerCursor:
    """Mock database cursor for job worker tests."""

    def __init__(self, connection: "MockWorkerDbConnection") -> None:
        self.connection = connection
        self.last_returning_row: Optional[Tuple[Any, ...]] = None
        self.last_returning_rows: List[Tuple[Any, ...]] = []

    def __enter__(self) -> "MockWorkerCursor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def execute(self, query: str, params: Optional[Union[Tuple[Any, ...], List[Any]]] = None) -> None:
        clean_q = " ".join(query.strip().split())
        self.connection.timeline.append(f"db_execute: {clean_q[:40]}")
        self.connection.executed_queries.append((clean_q, params))

        if self.connection.fail_on_query_substring and self.connection.fail_on_query_substring in clean_q:
            raise RuntimeError(f"Simulated database failure on query: {clean_q[:60]}")

        # 0. Episodes preflight query
        if "FROM episodes" in clean_q:
            ep_id = params[0] if params else None
            if ep_id not in self.connection.episodes:
                self.last_returning_row = None
            else:
                ep_data = self.connection.episodes[ep_id]
                self.last_returning_row = (
                    ep_data.get("publication_status", "draft"),
                    ep_data.get("youtube_video_id", "sample101"),
                )

        # Locked child items (FOR UPDATE)
        elif "FROM insights WHERE episode_id = %s FOR UPDATE" in clean_q:
            ep_id = params[0] if params else None
            self.last_returning_rows = [
                (ins["id"], ins.get("review_status", "candidate"))
                for ins in self.connection.insights
                if ins["episode_id"] == ep_id
            ]

        elif "FROM quotations WHERE episode_id = %s FOR UPDATE" in clean_q:
            ep_id = params[0] if params else None
            self.last_returning_rows = [
                (q["id"], q.get("review_status", "candidate"))
                for q in self.connection.quotations
                if q["episode_id"] == ep_id
            ]

        # Reviewed items count (verified or rejected)
        elif "SELECT count(*) FROM insights WHERE episode_id = %s AND review_status !=" in clean_q:
            ep_id = params[0] if params else None
            count = sum(
                1 for ins in self.connection.insights
                if ins["episode_id"] == ep_id and ins.get("review_status") != "candidate"
            )
            self.last_returning_row = (count,)

        elif "SELECT count(*) FROM quotations WHERE episode_id = %s AND review_status !=" in clean_q:
            ep_id = params[0] if params else None
            count = sum(
                1 for q in self.connection.quotations
                if q["episode_id"] == ep_id and q.get("review_status") != "candidate"
            )
            self.last_returning_row = (count,)

        # Existing unreviewed counts
        elif "SELECT count(*) FROM transcript_segments WHERE episode_id = %s" in clean_q:
            ep_id = params[0] if params else None
            count = sum(1 for seg in self.connection.transcript_segments if seg["episode_id"] == ep_id)
            self.last_returning_row = (count,)

        elif "SELECT count(*) FROM transcript_chunks WHERE episode_id = %s" in clean_q:
            ep_id = params[0] if params else None
            count = sum(1 for chk in self.connection.transcript_chunks if chk["episode_id"] == ep_id)
            self.last_returning_row = (count,)

        elif "SELECT count(*) FROM insights WHERE episode_id = %s AND review_status = 'candidate'" in clean_q:
            ep_id = params[0] if params else None
            count = sum(
                1 for ins in self.connection.insights
                if ins["episode_id"] == ep_id and ins.get("review_status") == "candidate"
            )
            self.last_returning_row = (count,)

        elif "SELECT count(*) FROM quotations WHERE episode_id = %s AND review_status = 'candidate'" in clean_q:
            ep_id = params[0] if params else None
            count = sum(
                1 for q in self.connection.quotations
                if q["episode_id"] == ep_id and q.get("review_status") == "candidate"
            )
            self.last_returning_row = (count,)

        # 1. Claim next pending job query (WITH claimable AS ... FOR UPDATE SKIP LOCKED)
        elif "ORDER BY created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1" in clean_q:
            # Find first job with status == 'pending' that is not currently locked
            claimed_job = None
            for job in self.connection.jobs:
                if job["status"] == "pending" and job["id"] not in self.connection.locked_job_ids:
                    claimed_job = job
                    # Lock row during claim transaction
                    self.connection.locked_job_ids.add(job["id"])
                    job["status"] = "processing"
                    job["current_stage"] = "transcript_acquisition"
                    job["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
                    break

            if claimed_job:
                self.last_returning_row = (
                    claimed_job["id"],
                    claimed_job.get("episode_id"),
                    claimed_job["youtube_url"],
                    claimed_job["youtube_video_id"],
                    claimed_job["status"],
                    claimed_job["current_stage"],
                    claimed_job["retry_count"],
                    claimed_job["max_retries"],
                )
            else:
                self.last_returning_row = None

        # 2. Claim specific job by ID (WHERE id = %s AND status = 'pending' ... SKIP LOCKED)
        elif "WHERE id = %s AND status = 'pending'" in clean_q or "WHERE processing_jobs.id = %s AND status = 'pending'" in clean_q or "WHERE id = %s AND status = 'pending'::processing_job_status" in clean_q:
            target_id = params[0] if params else None
            claimed_job = None
            for job in self.connection.jobs:
                if job["id"] == target_id and job["status"] == "pending" and job["id"] not in self.connection.locked_job_ids:
                    claimed_job = job
                    self.connection.locked_job_ids.add(job["id"])
                    job["status"] = "processing"
                    job["current_stage"] = "transcript_acquisition"
                    job["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
                    break

            if claimed_job:
                self.last_returning_row = (
                    claimed_job["id"],
                    claimed_job.get("episode_id"),
                    claimed_job["youtube_url"],
                    claimed_job["youtube_video_id"],
                    claimed_job["status"],
                    claimed_job["current_stage"],
                    claimed_job["retry_count"],
                    claimed_job["max_retries"],
                )
            else:
                self.last_returning_row = None

        # 3. Stage update query (UPDATE processing_jobs SET current_stage = ...)
        elif "SET current_stage = %s::processing_stage" in clean_q:
            stage = params[0] if params else None
            job_id = params[1] if params and len(params) > 1 else None
            for job in self.connection.jobs:
                if job["id"] == job_id:
                    job["current_stage"] = stage
                    job["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
                    break

        # 4. Retry scheduling query (SET status = 'pending' ... retry_count = retry_count + 1)
        elif "SET status = 'pending'::processing_job_status" in clean_q and "retry_count = retry_count + 1" in clean_q:
            stage = params[0] if params else None
            error_summary = params[1] if params and len(params) > 1 else None
            job_id = params[2] if params and len(params) > 2 else None
            for job in self.connection.jobs:
                if job["id"] == job_id:
                    job["status"] = "pending"
                    job["current_stage"] = stage
                    job["retry_count"] += 1
                    job["error_summary"] = error_summary
                    job["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
                    break

        # 5. Job failure recording query (SET status = 'failed')
        elif "SET status = 'failed'::processing_job_status" in clean_q:
            stage = params[0] if params else None
            error_summary = params[1] if params and len(params) > 1 else None
            job_id = params[2] if params and len(params) > 2 else None
            for job in self.connection.jobs:
                if job["id"] == job_id:
                    job["status"] = "failed"
                    job["current_stage"] = stage
                    job["error_summary"] = error_summary
                    job["completed_at"] = datetime.datetime.now(datetime.timezone.utc)
                    job["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
                    break

        # 6. Job completion query (SET status = 'completed')
        elif "SET status = %s::processing_job_status" in clean_q or "SET status = 'completed'" in clean_q:
            status = params[0] if params else "completed"
            stage = params[1] if params and len(params) > 1 else "human_review"
            error_summary = params[2] if params and len(params) > 2 else None
            job_id = params[3] if params and len(params) > 3 else None
            for job in self.connection.jobs:
                if job["id"] == job_id:
                    job["status"] = status
                    job["current_stage"] = stage
                    job["error_summary"] = error_summary
                    job["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
                    if status == "completed":
                        job["completed_at"] = datetime.datetime.now(datetime.timezone.utc)
                    break

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if self.last_returning_rows:
            return self.last_returning_rows.pop(0)
        row = self.last_returning_row
        self.last_returning_row = None
        return row

    def fetchall(self) -> List[Tuple[Any, ...]]:
        rows = list(self.last_returning_rows)
        self.last_returning_rows = []
        return rows

    def close(self) -> None:
        pass


class MockWorkerDbConnection:
    """Mock connection maintaining state across worker operations."""

    def __init__(
        self,
        jobs: Optional[List[Dict[str, Any]]] = None,
        shared_state: Optional[Dict[str, Any]] = None,
        episodes: Optional[Dict[str, Dict[str, Any]]] = None,
        insights: Optional[List[Dict[str, Any]]] = None,
        quotations: Optional[List[Dict[str, Any]]] = None,
        transcript_segments: Optional[List[Dict[str, Any]]] = None,
        transcript_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.jobs = jobs if jobs is not None else []
        self.shared_state = shared_state or {
            "timeline": [],
            "locked_job_ids": set(),
            "episodes": {"ep-uuid-101": {"publication_status": "draft", "youtube_video_id": "sample101"}},
            "insights": [],
            "quotations": [],
            "transcript_segments": [],
            "transcript_chunks": [],
        }
        self.timeline: List[str] = self.shared_state["timeline"]
        self.locked_job_ids = self.shared_state["locked_job_ids"]

        if episodes is not None:
            self.shared_state["episodes"] = episodes
        elif "episodes" not in self.shared_state:
            self.shared_state["episodes"] = {"ep-uuid-101": {"publication_status": "draft", "youtube_video_id": "sample101"}}
        self.episodes = self.shared_state["episodes"]

        if insights is not None:
            self.shared_state["insights"] = insights
        elif "insights" not in self.shared_state:
            self.shared_state["insights"] = []
        self.insights = self.shared_state["insights"]

        if quotations is not None:
            self.shared_state["quotations"] = quotations
        elif "quotations" not in self.shared_state:
            self.shared_state["quotations"] = []
        self.quotations = self.shared_state["quotations"]

        if transcript_segments is not None:
            self.shared_state["transcript_segments"] = transcript_segments
        elif "transcript_segments" not in self.shared_state:
            self.shared_state["transcript_segments"] = []
        self.transcript_segments = self.shared_state["transcript_segments"]

        if transcript_chunks is not None:
            self.shared_state["transcript_chunks"] = transcript_chunks
        elif "transcript_chunks" not in self.shared_state:
            self.shared_state["transcript_chunks"] = []
        self.transcript_chunks = self.shared_state["transcript_chunks"]

        self.executed_queries: List[Tuple[str, Optional[Tuple[Any, ...]]]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_on_query_substring: Optional[str] = None

    def cursor(self) -> MockWorkerCursor:
        return MockWorkerCursor(self)

    def commit(self) -> None:
        self.commit_count += 1
        self.timeline.append("conn_commit")
        # Row locks released on commit
        self.locked_job_ids.clear()

    def rollback(self) -> None:
        self.rollback_count += 1
        self.timeline.append("conn_rollback")
        self.locked_job_ids.clear()

    def close(self) -> None:
        pass


class MockWorkerOrchestrator:
    """Mock orchestrator simulating PipelineOrchestrator executions."""

    def __init__(
        self,
        timeline: Optional[List[str]] = None,
        exception_to_raise: Optional[Exception] = None,
        return_result: Optional[PipelineExecutionResult] = None,
        preflight_exception: Optional[Exception] = None,
    ) -> None:
        self.timeline = timeline if timeline is not None else []
        self.exception_to_raise = exception_to_raise
        self.return_result = return_result
        self.preflight_exception = preflight_exception

    def check_editorial_preflight(
        self,
        cursor: Any,
        episode_id: str,
        allow_candidate_rerun: bool = False,
        expected_youtube_video_id: Optional[str] = None,
    ) -> None:
        self.timeline.append(f"check_editorial_preflight: {episode_id}")
        if self.preflight_exception:
            raise self.preflight_exception
        PipelineOrchestrator.check_editorial_preflight(
            cursor,
            episode_id=episode_id,
            allow_candidate_rerun=allow_candidate_rerun,
            expected_youtube_video_id=expected_youtube_video_id,
        )

    def run(
        self,
        job_id: str,
        episode_id: str,
        transcript_content: Any,
        connection_factory: Optional[Any] = None,
        allow_candidate_rerun: bool = False,
        expected_youtube_video_id: Optional[str] = None,
        **kwargs: Any,
    ) -> PipelineExecutionResult:
        self.timeline.append(f"orchestrator_run: {job_id}")

        if self.exception_to_raise:
            raise self.exception_to_raise

        # Simulate orchestrator's persistence transaction updating processing_jobs to completed
        if connection_factory:
            conn = connection_factory()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE processing_jobs
                SET status = 'completed'::processing_job_status,
                    current_stage = 'human_review'::processing_stage,
                    error_summary = NULL,
                    updated_at = now()
                WHERE id = %s;
                """,
                ("completed", "human_review", None, job_id),
            )
            conn.commit()

        if self.return_result:
            return self.return_result

        return PipelineExecutionResult(
            job_id=job_id,
            episode_id=episode_id,
            run_id="run-mock-1",
            status="completed",
            validation_status="passed",
            segments_count=5,
            chunks_count=1,
            insights_count=2,
            quotations_count=1,
            evidence_count=2,
            quotation_segments_count=1,
            validation_errors_count=0,
        )


class TestJobWorker(unittest.TestCase):
    """Test suite verifying JobWorker claims, lifecycle, retries, and errors."""

    def setUp(self) -> None:
        self.shared_state: Dict[str, Any] = {
            "timeline": [],
            "locked_job_ids": set(),
            "episodes": {
                "ep-uuid-101": {
                    "id": "ep-uuid-101",
                    "publication_status": "draft",
                    "youtube_video_id": "sample101",
                }
            },
            "insights": [],
            "quotations": [],
            "transcript_segments": [],
            "transcript_chunks": [],
        }
        self.sample_jobs: List[Dict[str, Any]] = [
            {
                "id": "job-uuid-101",
                "episode_id": "ep-uuid-101",
                "youtube_url": "https://www.youtube.com/watch?v=sample101",
                "youtube_video_id": "sample101",
                "status": "pending",
                "current_stage": "submission",
                "retry_count": 0,
                "max_retries": 3,
                "error_summary": None,
            }
        ]
        self.transcript_provider = StaticTranscriptProvider(default_content="1\n00:00:00,000 --> 00:00:05,000\nሙከራ ጽሑፍ።\n")

    def _make_connection_factory(self) -> Any:
        def factory():
            return MockWorkerDbConnection(jobs=self.sample_jobs, shared_state=self.shared_state)
        return factory

    # =========================================================================
    # Test 1: Claiming one pending job
    # =========================================================================
    def test_claim_one_pending_job(self) -> None:
        """Worker successfully claims an eligible pending job and starts processing."""
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job()

        self.assertTrue(result.processed)
        self.assertEqual(result.job_id, "job-uuid-101")
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.sample_jobs[0]["status"], "completed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "human_review")

    # =========================================================================
    # Test 2: No pending job available (queue idle)
    # =========================================================================
    def test_no_pending_job_available(self) -> None:
        """When queue contains no pending jobs, worker returns idle result cleanly."""
        self.sample_jobs[0]["status"] = "completed"
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job()

        self.assertFalse(result.processed)
        self.assertEqual(result.status, "idle")
        self.assertIsNone(result.job_id)
        # Ensure orchestrator was never invoked
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    # =========================================================================
    # Test 3: Two workers cannot claim the same job (SKIP LOCKED simulation)
    # =========================================================================
    def test_two_workers_cannot_claim_same_job(self) -> None:
        """Demonstrates that concurrent workers cannot claim the same pending row."""
        # Worker 1 claims the job
        orchestrator1 = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker1 = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator1,
        )

        # Worker 2 attempts to claim while job is being processed
        orchestrator2 = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker2 = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator2,
        )

        res1 = worker1.process_next_job()
        self.assertTrue(res1.processed)
        self.assertEqual(res1.job_id, "job-uuid-101")

        # Now second worker tries: job is no longer pending
        res2 = worker2.process_next_job()
        self.assertFalse(res2.processed)
        self.assertEqual(res2.status, "idle")

    # =========================================================================
    # Test 4: Claim transaction ends before Gemini / orchestrator is called
    # =========================================================================
    def test_claim_transaction_ends_before_gemini_called(self) -> None:
        """Temporal proof: claim transaction commits strictly before orchestrator runs."""
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        worker.process_next_job()

        # In timeline, conn_commit for the claim MUST precede orchestrator_run
        claim_commit_idx = -1
        orch_run_idx = -1
        for idx, event in enumerate(self.shared_state["timeline"]):
            if event == "conn_commit" and claim_commit_idx == -1:
                claim_commit_idx = idx
            if "orchestrator_run" in event and orch_run_idx == -1:
                orch_run_idx = idx

        self.assertNotEqual(claim_commit_idx, -1)
        self.assertNotEqual(orch_run_idx, -1)
        self.assertLess(claim_commit_idx, orch_run_idx, "Claim transaction MUST commit before orchestrator runs!")

    # =========================================================================
    # Test 5: Successful completion lifecycle
    # =========================================================================
    def test_successful_completion_lifecycle(self) -> None:
        """Verifies full lifecycle transitions from submission -> acquisition -> ai_extraction -> completed."""
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_job("job-uuid-101")

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.sample_jobs[0]["status"], "completed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "human_review")
        self.assertIsNotNone(self.sample_jobs[0]["completed_at"])

    # =========================================================================
    # Test 6: Retryable failure and retry-count limits
    # =========================================================================
    def test_retryable_failure_and_limits(self) -> None:
        """Transient network errors schedule retry until max_retries is reached."""
        # Scenario A: First transient failure (retry_count 0 -> 1, status pending)
        gemini_503 = PipelineExtractionError("Gemini candidate extraction failed: Gemini service unavailable 503")
        gemini_503.__cause__ = GeminiServiceUnavailableError("Service unavailable 503")

        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=MockWorkerOrchestrator(exception_to_raise=gemini_503),
        )

        result = worker.process_job("job-uuid-101")

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "retry_scheduled")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(self.sample_jobs[0]["status"], "pending")
        self.assertEqual(self.sample_jobs[0]["retry_count"], 1)

        # Scenario B: Exhausting retries (job at max_retries=3)
        self.sample_jobs[0]["retry_count"] = 3
        result_exhausted = worker.process_job("job-uuid-101")

        self.assertTrue(result_exhausted.processed)
        self.assertEqual(result_exhausted.status, "failed")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertIsNotNone(self.sample_jobs[0]["completed_at"])

    # =========================================================================
    # Test 7: Non-retryable validation or editorial failure
    # =========================================================================
    def test_non_retryable_validation_or_editorial_failure(self) -> None:
        """Deterministic validation or editorial protection errors fail immediately without retries."""
        # Validation error
        val_err = PipelineValidationError("Validation failed for chunk 0: Business category invalid")
        worker_val = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=MockWorkerOrchestrator(exception_to_raise=val_err),
        )

        res_val = worker_val.process_job("job-uuid-101")
        self.assertEqual(res_val.status, "failed")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["retry_count"], 0)  # Did not increment retry_count

        # Editorial protection error
        self.sample_jobs[0]["status"] = "pending"
        ed_err = EditorialProtectionError("Episode contains verified insights; cannot rerun.")
        worker_ed = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=MockWorkerOrchestrator(exception_to_raise=ed_err),
        )

        res_ed = worker_ed.process_job("job-uuid-101")
        self.assertEqual(res_ed.status, "failed")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["retry_count"], 0)

    # =========================================================================
    # Test 8: Persistence failure and uncertain commit behavior
    # =========================================================================
    def test_persistence_failure_and_uncertain_commit_behavior(self) -> None:
        """Database persistence errors are treated conservatively as non-retryable."""
        persist_err = PipelinePersistenceError("Database persistence failed: unique constraint violation")
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=MockWorkerOrchestrator(exception_to_raise=persist_err),
        )

        result = worker.process_job("job-uuid-101")

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["retry_count"], 0)

    # =========================================================================
    # Test 9: Missing episode or transcript input
    # =========================================================================
    def test_missing_episode_or_transcript_input(self) -> None:
        """Jobs with missing episode_id or missing transcript fail cleanly before calling orchestrator."""
        # 1. Missing episode_id
        self.sample_jobs[0]["episode_id"] = None
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        res_ep = worker.process_job("job-uuid-101")
        self.assertEqual(res_ep.status, "failed")
        self.assertIn("Missing episode_id", res_ep.error or "")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

        # 2. Empty transcript input
        self.sample_jobs[0]["episode_id"] = "ep-uuid-101"
        self.sample_jobs[0]["status"] = "pending"
        empty_provider = StaticTranscriptProvider(default_content="   \n  ")
        worker_empty = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=empty_provider,
            orchestrator=orchestrator,
        )

        res_empty = worker_empty.process_job("job-uuid-101")
        self.assertEqual(res_empty.status, "failed")
        self.assertIn("transcript content is empty", res_empty.error or "")
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    # =========================================================================
    # Test 10: Safe error-summary redaction in database updates
    # =========================================================================
    def test_safe_error_summary_redaction(self) -> None:
        """Secrets (Google API keys, DB passwords) in exception messages are redacted in processing_jobs."""
        leaky_key = "AIzaSySecretLeakKey1234567890123"
        leaky_err = PipelineExtractionError(
            f"Failed to call https://generativelanguage.googleapis.com/v1beta/models?key={leaky_key} with URI postgres://admin:super_secret_db_pass@db.local:5432/meri"
        )
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=MockWorkerOrchestrator(exception_to_raise=leaky_err),
        )

        result = worker.process_job("job-uuid-101")

        self.assertEqual(result.status, "failed")
        persisted_summary = self.sample_jobs[0]["error_summary"]
        self.assertNotIn(leaky_key, persisted_summary)
        self.assertNotIn("super_secret_db_pass", persisted_summary)
        self.assertIn("[REDACTED]", persisted_summary)

    # =========================================================================
    # Test 11: Invalid state transitions / non-pending job claim rejection
    # =========================================================================
    def test_invalid_state_transitions_are_rejected(self) -> None:
        """Attempting to claim an already processing or completed job by ID is rejected."""
        self.sample_jobs[0]["status"] = "completed"
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=MockWorkerOrchestrator(),
        )

        result = worker.process_job("job-uuid-101")

        self.assertFalse(result.processed)
        self.assertEqual(result.status, "rejected")
        self.assertIn("not in 'pending' status", result.error or "")

    # =========================================================================
    # Test 12: Stale-job policy: no premature reclamation without ownership fencing
    # =========================================================================
    def test_no_stale_job_reclamation_without_fencing(self) -> None:
        """Verifies policy: a job in 'processing' status is NOT reclaimed solely due to old updated_at."""
        old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        self.sample_jobs[0]["status"] = "processing"
        self.sample_jobs[0]["updated_at"] = old_time

        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=MockWorkerOrchestrator(),
        )

        result = worker.process_next_job()

        # Job must NOT be stolen/reclaimed
        self.assertFalse(result.processed)
        self.assertEqual(result.status, "idle")
        self.assertEqual(self.sample_jobs[0]["status"], "processing")

    # =========================================================================
    # Test 13: Milestone 5.2 Pre-Gemini Editorial Preflight Protections
    # =========================================================================
    def test_worker_preflight_published_episode_rejected_before_gemini(self) -> None:
        """Published episode is rejected during preflight before Gemini or orchestrator.run."""
        self.shared_state["episodes"]["ep-uuid-101"] = {
            "publication_status": "published",
            "youtube_video_id": "sample101",
        }
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job()

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertIn("already published", result.error or "")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "human_review")
        # Strict temporal proof: orchestrator.run was NEVER called
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    def test_worker_preflight_reviewed_content_rejected_before_gemini(self) -> None:
        """Episodes with verified or rejected items fail preflight before Gemini."""
        for review_status in ["verified", "rejected"]:
            with self.subTest(review_status=review_status):
                self.sample_jobs[0]["status"] = "pending"
                self.sample_jobs[0]["current_stage"] = "submission"
                self.shared_state["timeline"].clear()
                self.shared_state["insights"] = [{
                    "id": f"ins-{review_status}-01",
                    "episode_id": "ep-uuid-101",
                    "title": f"Reviewed {review_status} insight",
                    "review_status": review_status,
                }]

                orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
                worker = JobWorker(
                    connection_factory=self._make_connection_factory(),
                    transcript_provider=self.transcript_provider,
                    orchestrator=orchestrator,
                )

                result = worker.process_next_job()

                self.assertTrue(result.processed)
                self.assertEqual(result.status, "failed")
                self.assertIn("verified/reviewed", result.error or "")
                self.assertEqual(self.sample_jobs[0]["status"], "failed")
                self.assertEqual(self.sample_jobs[0]["current_stage"], "human_review")
                self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    def test_worker_preflight_staging_data_rejected_when_rerun_false(self) -> None:
        """Existing candidate data is rejected before Gemini when allow_candidate_rerun=False."""
        self.shared_state["transcript_segments"] = [{
            "id": "seg-101",
            "episode_id": "ep-uuid-101",
        }]

        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job(allow_candidate_rerun=False)

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertIn("Reruns must explicitly enable allow_candidate_rerun", result.error or "")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "human_review")
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    def test_worker_preflight_allow_rerun_cannot_bypass_editorial_protection(self) -> None:
        """--allow-rerun cannot bypass preflight protections for published or reviewed content."""
        self.shared_state["episodes"]["ep-uuid-101"] = {
            "publication_status": "published",
            "youtube_video_id": "sample101",
        }
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job(allow_candidate_rerun=True)

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertIn("already published", result.error or "")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "human_review")
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    def test_worker_persistence_protection_active_if_state_changes_after_preflight(self) -> None:
        """Persistence-time protection inside transaction remains active if state changes after preflight."""
        # Preflight passes normally, but orchestrator persistence triggers an EditorialProtectionError
        # (simulating database state being modified concurrently between preflight and persistence)
        orchestrator = MockWorkerOrchestrator(
            timeline=self.shared_state["timeline"],
            exception_to_raise=EditorialProtectionError("Concurrent edit: episode became published"),
        )
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job()

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertIn("episode became published", result.error or "")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "human_review")

    # =========================================================================
    # Test 14: Milestone 5.2 Transcript Identity & Operator Confirmation
    # =========================================================================
    def test_worker_transcript_confirmation_required_for_local_provider(self) -> None:
        """Static transcript provider with requires_confirmation=True rejects invocation without confirmation."""
        local_provider = StaticTranscriptProvider(
            default_content="1\n00:00:00,000 --> 00:00:05,000\nሙከራ\n",
            requires_confirmation=True,
        )
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=local_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job(confirm_youtube_video_id=None)

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertIn("--confirm-youtube-video-id", result.error or "")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "submission")
        self.assertIsNotNone(self.sample_jobs[0].get("completed_at"))
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    def test_worker_transcript_confirmation_whitespace_only_rejected_before_gemini(self) -> None:
        """Whitespace-only operator confirmation is strictly rejected before Gemini."""
        local_provider = StaticTranscriptProvider(
            default_content="1\n00:00:00,000 --> 00:00:05,000\nሙከራ\n",
            requires_confirmation=True,
        )
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=local_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job(confirm_youtube_video_id="   ")

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertIn("empty or whitespace-only", result.error or "")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "submission")
        self.assertIsNotNone(self.sample_jobs[0].get("completed_at"))
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    def test_worker_transcript_confirmation_padded_whitespace_matching_passes(self) -> None:
        """Operator confirmation with leading/trailing whitespace is stripped cleanly and succeeds."""
        local_provider = StaticTranscriptProvider(
            default_content="1\n00:00:00,000 --> 00:00:05,000\nሙከራ\n",
            requires_confirmation=True,
        )
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=local_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job(confirm_youtube_video_id="  sample101  ")

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "completed")
        self.assertIn("orchestrator_run: job-uuid-101", self.shared_state["timeline"])

    def test_worker_transcript_confirmation_matching_passes(self) -> None:
        """Matching operator confirmation, job video ID, and episode video ID passes successfully."""
        local_provider = StaticTranscriptProvider(
            default_content="1\n00:00:00,000 --> 00:00:05,000\nሙከራ\n",
            requires_confirmation=True,
        )
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=local_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job(confirm_youtube_video_id="sample101")

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "completed")
        self.assertIn("orchestrator_run: job-uuid-101", self.shared_state["timeline"])

    def test_worker_transcript_confirmation_mismatch_rejected_before_gemini(self) -> None:
        """Mismatched confirmation ID is rejected before preflight and before Gemini."""
        local_provider = StaticTranscriptProvider(
            default_content="1\n00:00:00,000 --> 00:00:05,000\nሙከራ\n",
            requires_confirmation=True,
        )
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=local_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job(confirm_youtube_video_id="WRONG_ID_999")

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertIn("Confirmed YouTube video ID", result.error or "")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "submission")
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))

    def test_worker_transcript_job_episode_id_mismatch_rejected_before_gemini(self) -> None:
        """Job video ID mismatch with database episode video ID is rejected before Gemini."""
        self.shared_state["episodes"]["ep-uuid-101"] = {
            "publication_status": "draft",
            "youtube_video_id": "EPISODE_DIFF_VID",
        }
        orchestrator = MockWorkerOrchestrator(timeline=self.shared_state["timeline"])
        worker = JobWorker(
            connection_factory=self._make_connection_factory(),
            transcript_provider=self.transcript_provider,
            orchestrator=orchestrator,
        )

        result = worker.process_next_job(confirm_youtube_video_id="sample101")

        self.assertTrue(result.processed)
        self.assertEqual(result.status, "failed")
        self.assertIn("does not match episode YouTube video ID", result.error or "")
        self.assertEqual(self.sample_jobs[0]["status"], "failed")
        self.assertEqual(self.sample_jobs[0]["current_stage"], "submission")
        self.assertNotIn("orchestrator_run", "".join(self.shared_state["timeline"]))


if __name__ == "__main__":
    unittest.main()
