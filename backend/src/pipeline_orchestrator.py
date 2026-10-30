"""
Meri Content Pipeline v1: Pipeline Orchestrator.

Integrates the transcript-ingestion and AI-extraction lifecycle for Meri Podcast episodes:
1. Input validation for job and episode identifiers.
2. Transcript parsing (JSON, SRT, WebVTT) into raw cues.
3. Transcript normalization into monotonic NormalizedSegment records.
4. Synthesizing deterministic TranscriptChunk context windows with explicit segment labels.
5. Invoking Gemini candidate extraction per chunk using structured JSON schema.
6. Syntactic and semantic validation against source segments.
7. Multi-chunk candidate reconciliation (deduplicating insights and quotations while preserving provenance).
8. Atomic database persistence boundary: all remote AI extraction and validation calls execute
   strictly in-memory BEFORE any database write transaction begins.
9. Enforcing editorial protection and foreign-key-safe rerun policies.
10. Persisting segments, chunks, extraction runs, and reconciled candidates atomically.
"""

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

from .candidate_persistence import (
    CandidatePersistenceService,
    EditorialAuthorizationError,
    SegmentReferenceIntegrityError,
    persist_transcript_chunks,
    persist_transcript_segments,
)
from .candidate_reconciliation import (
    CandidateReconciler,
    PayloadReconciliationResult,
    ReconciliationReport,
    reconcile_payloads,
)
from .chunker import TranscriptChunker, format_chunk_text
from .extraction_models import (
    CandidateExtractionPayload,
    ExtractionRunRecord,
    ValidationErrorItem,
    ValidationSeverity,
    ValidationStatus,
)
from .extraction_service import ExtractionService
from .gemini_client import (
    GeminiClient,
    GeminiClientError,
    GeminiConfig,
)
from .models import (
    InvalidTimestampError,
    MalformedCueError,
    NormalizedSegment,
    RawCue,
    TranscriptChunk,
    TranscriptOverlapError,
)
from .transcript_normalizer import TranscriptNormalizer
from .transcript_parser import parse_transcript

logger = logging.getLogger(__name__)


def _redact_secrets(text: str) -> str:
    """Strips API keys, bearer tokens, database credentials, and sensitive parameters from logs and exceptions."""
    if not text:
        return text
    # Strip ?key=... or &key=... query parameters
    scrubbed = re.sub(r"([?&]key=)[^&\s'\"]+", r"\1[REDACTED]", text)
    # Strip Google API Keys (AIzaSy...)
    scrubbed = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_API_KEY]", scrubbed)
    # Strip Bearer tokens
    scrubbed = re.sub(r"(Bearer\s+)[A-Za-z0-9\-_.]{10,}", r"\1[REDACTED_TOKEN]", scrubbed, flags=re.IGNORECASE)
    # Strip database credentials embedded in connection URIs (e.g. postgres://user:pass@host)
    scrubbed = re.sub(r"://([^:]+):([^@]+)@", r"://\1:[REDACTED]@", scrubbed)
    return scrubbed


class PipelineOrchestratorError(Exception):
    """Base exception for all pipeline orchestration failures."""
    pass


class PipelineInputError(PipelineOrchestratorError, ValueError):
    """Raised when job, episode, or transcript input arguments are missing or malformed."""
    pass


class PipelineExtractionError(PipelineOrchestratorError, RuntimeError):
    """Raised when parsing, normalization, chunking, or Gemini LLM extraction fails."""
    pass


class PipelineValidationError(PipelineOrchestratorError, ValueError):
    """Raised when candidate extraction payload fails syntactic or semantic validation."""
    pass


class PipelinePersistenceError(PipelineOrchestratorError, RuntimeError):
    """Raised when database writes or transaction commit fails."""
    pass


class EditorialProtectionError(PipelineOrchestratorError, PermissionError):
    """Raised when pipeline execution is rejected because an episode contains verified or published content."""
    pass


@dataclass(frozen=True)
class PipelineExecutionResult:
    """
    Structured outcome of an end-to-end pipeline orchestration execution.
    Conforms to the Meri Content Pipeline schema and Milestone 4 requirements.
    """
    job_id: str
    episode_id: str
    run_id: Optional[str]
    status: str  # 'completed' or 'failed'
    validation_status: str  # 'passed', 'partial', 'failed'
    segments_count: int
    chunks_count: int
    insights_count: int
    quotations_count: int
    evidence_count: int
    quotation_segments_count: int
    validation_errors_count: int
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "status": self.status,
            "validation_status": self.validation_status,
            "segments_count": self.segments_count,
            "chunks_count": self.chunks_count,
            "insights_count": self.insights_count,
            "quotations_count": self.quotations_count,
            "evidence_count": self.evidence_count,
            "quotation_segments_count": self.quotation_segments_count,
            "validation_errors_count": self.validation_errors_count,
            "diagnostics": self.diagnostics,
        }


class PipelineOrchestrator:
    """
    End-to-end pipeline orchestrator for transcript ingestion, AI extraction, and candidate persistence.

    TRANSACTION & CONCURRENCY CONTRACT:
    - Gemini LLM network calls must NEVER execute inside an open database transaction.
    - All transcript parsing, normalization, chunking, AI extraction, validation, and multi-chunk
      reconciliation execute in-memory first.
    - Only after all AI extraction and validation succeed does the orchestrator open/use the
      database write transaction.
    - If the provided connection supports commit/rollback, successful persistence commits exactly
      once; any persistence error triggers an immediate rollback.
    """

    def __init__(
        self,
        gemini_client: Optional[GeminiClient] = None,
        extraction_service: Optional[ExtractionService] = None,
        reconciler: Optional[CandidateReconciler] = None,
        normalizer: Optional[TranscriptNormalizer] = None,
        chunker: Optional[TranscriptChunker] = None,
    ) -> None:
        self.gemini_client = gemini_client or (extraction_service.gemini_client if extraction_service else GeminiClient())
        self.extraction_service = extraction_service or ExtractionService(gemini_client=self.gemini_client)
        self.reconciler = reconciler or CandidateReconciler()
        self.normalizer = normalizer or TranscriptNormalizer()
        self.chunker = chunker or TranscriptChunker()

    def run(
        self,
        job_id: str,
        episode_id: str,
        transcript_content: Union[str, Dict[str, Any], List[Any]],
        connection: Optional[Any] = None,
        connection_factory: Optional[Callable[[], Any]] = None,
        format_hint: Optional[str] = None,
        run_number: Optional[int] = None,
        allow_candidate_rerun: bool = False,
        expected_youtube_video_id: Optional[str] = None,
    ) -> PipelineExecutionResult:
        """
        Runs the content pipeline end-to-end for one episode and transcript input.

        Args:
            job_id: Unique processing job UUID matching table processing_jobs.
            episode_id: Unique episode UUID matching table episodes.
            transcript_content: Source transcript text (JSON/SRT/WebVTT) or parsed dict/list.
            connection: Database connection or cursor providing PEP 249 commit/rollback semantics.
            connection_factory: Optional zero-arg callable returning a database connection.
                                Preferred over connection to guarantee that no connection or
                                transaction exists while remote Gemini API extraction runs.
            format_hint: Optional format indicator ('json', 'srt', 'vtt').
            run_number: Optional monotonically increasing run attempt number for (job_id, run_number).
                        If omitted (None), the next available run_number is computed automatically.
            allow_candidate_rerun: If True, permits replacing prior unreviewed candidate staging data.
                                   Verified/reviewed content and published episodes are NEVER overwritten.
            expected_youtube_video_id: Optional YouTube video ID to verify against the episode record.

        Returns:
            PipelineExecutionResult describing persisted entities and diagnostics.

        Raises:
            PipelineInputError: If identifiers, connection contract, transcript content, or video ID are missing/invalid.
            PipelineExtractionError: If transcript parsing, chunking, or Gemini LLM extraction fails.
            PipelineValidationError: If candidate extraction payload fails syntactic/semantic validation.
            EditorialProtectionError: If rerun is blocked because episode is published or contains reviewed content.
            PipelinePersistenceError: If database persistence or transaction commit fails.
        """
        # 1. Validate required identifiers and input
        self._validate_input(
            job_id=job_id,
            episode_id=episode_id,
            transcript_content=transcript_content,
            connection=connection,
            connection_factory=connection_factory,
            run_number=run_number,
        )

        current_stage = "submission"
        effective_connection = connection

        # 2. Parse transcript using existing parser
        current_stage = "transcript_acquisition"
        try:
            cues = parse_transcript(transcript_content, format_hint=format_hint)
        except Exception as exc:
            safe_err = _redact_secrets(str(exc))
            raise PipelineExtractionError(f"Transcript parsing failed: {safe_err}") from exc

        if not cues:
            raise PipelineExtractionError("Transcript parsing produced no cues.")

        # 3. Normalize cues using existing normalizer
        current_stage = "transcript_normalization"
        try:
            segments = self.normalizer.normalize(cues)
        except Exception as exc:
            safe_err = _redact_secrets(str(exc))
            raise PipelineExtractionError(f"Transcript normalization failed: {safe_err}") from exc

        if not segments:
            raise PipelineExtractionError("Transcript normalization produced no segments.")

        # 4. Build deterministic chunks using existing chunker
        current_stage = "chunking"
        try:
            chunks = self.chunker.chunk(segments)
        except Exception as exc:
            safe_err = _redact_secrets(str(exc))
            raise PipelineExtractionError(f"Transcript chunking failed: {safe_err}") from exc

        if not chunks:
            raise PipelineExtractionError("Transcript chunking produced no chunks.")

        # 5-8. AI Extraction & Validation per chunk (strictly in-memory, ZERO DB writes)
        current_stage = "ai_extraction"
        chunk_records: List[ExtractionRunRecord] = []
        chunk_payloads: List[CandidateExtractionPayload] = []

        for chunk in chunks:
            try:
                run_record = self.extraction_service.extract_and_validate(
                    segments=segments,
                    chunks=[chunk],
                    job_id=job_id,
                    episode_id=episode_id,
                    run_number=run_number or 1,
                )
            except Exception as exc:
                safe_err = _redact_secrets(str(exc))
                raise PipelineExtractionError(
                    f"Gemini candidate extraction failed for chunk {chunk.chunk_index}: {safe_err}"
                ) from exc

            if run_record.validation_status == ValidationStatus.FAILED:
                current_stage = "validation"
                err_msgs = [e.message for e in run_record.validation_errors]
                raise PipelineValidationError(
                    f"Validation failed for chunk {chunk.chunk_index} with status FAILED: "
                    f"{'; '.join(err_msgs[:5])}"
                )

            if not run_record.candidate_payload:
                current_stage = "validation"
                raise PipelineValidationError(
                    f"Extraction produced no candidate payload for chunk {chunk.chunk_index}."
                )

            chunk_records.append(run_record)
            chunk_payloads.append(run_record.candidate_payload)

        # 9. Multi-chunk candidate reconciliation across overlapping chunks
        current_stage = "validation"
        try:
            reconciliation_res = self.reconciler.reconcile_payloads(chunk_payloads)
            reconciled_payload = reconciliation_res.payload
            reconciliation_report = reconciliation_res.report
        except Exception as exc:
            safe_err = _redact_secrets(str(exc))
            raise PipelineValidationError(f"Candidate reconciliation failed: {safe_err}") from exc

        # Do not silently treat zero candidates as successful replacement
        if len(reconciled_payload.insights) == 0 and len(reconciled_payload.quotations) == 0:
            raise PipelineExtractionError(
                "Extraction produced zero candidate insights and zero candidate quotations across all chunks."
            )

        # 10. Build complete in-memory execution plan and verify segment references
        if any(r.validation_status == ValidationStatus.PARTIAL for r in chunk_records):
            overall_validation_status = ValidationStatus.PARTIAL
        else:
            overall_validation_status = ValidationStatus.PASSED

        all_validation_errors: List[ValidationErrorItem] = [
            err for r in chunk_records for err in r.validation_errors
        ]
        total_tokens_prompt = sum(r.tokens_prompt or 0 for r in chunk_records)
        total_tokens_completion = sum(r.tokens_completion or 0 for r in chunk_records)

        raw_responses = [r.raw_response_json for r in chunk_records if r.raw_response_json]
        combined_raw_json = json.dumps(raw_responses) if len(raw_responses) > 1 else (raw_responses[0] if raw_responses else None)

        # Verify in-memory evidence integrity before opening write transaction
        source_segment_indices = {s.segment_index for s in segments}
        CandidatePersistenceService.validate_candidate_payload_references(
            payload=reconciled_payload,
            segment_index_to_id={idx: f"in-memory-check-{idx}" for idx in source_segment_indices},
        )

        # 11-12. Atomic database writes boundary
        current_stage = "human_review"
        cursor = None
        try:
            if effective_connection is None and connection_factory is not None:
                effective_connection = connection_factory()

            cursor = effective_connection.cursor() if hasattr(effective_connection, "cursor") and callable(effective_connection.cursor) else effective_connection

            # Step A: Enforce rerun policy and editorial protection
            self._enforce_rerun_policy(
                cursor,
                episode_id,
                allow_candidate_rerun=allow_candidate_rerun,
                expected_youtube_video_id=expected_youtube_video_id,
            )

            # Step B: Persist transcript segments
            segment_index_to_id = persist_transcript_segments(cursor, episode_id, segments)

            # Step C: Persist transcript chunks
            chunks_count = persist_transcript_chunks(
                cursor, episode_id, chunks, valid_segment_indices=set(segment_index_to_id.keys())
            )

            # Step D: Determine effective run_number and enforce concurrency uniqueness
            if run_number is None:
                cursor.execute(
                    "SELECT COALESCE(MAX(run_number), 0) + 1 FROM extraction_runs WHERE job_id = %s;",
                    (job_id,),
                )
                max_row = cursor.fetchone()
                effective_run_number = int(max_row[0]) if max_row and max_row[0] is not None else 1
            else:
                cursor.execute(
                    "SELECT count(*) FROM extraction_runs WHERE job_id = %s AND run_number = %s;",
                    (job_id, run_number),
                )
                exist_row = cursor.fetchone()
                exist_count = int(exist_row[0]) if exist_row and exist_row[0] is not None else 0
                if exist_count > 0:
                    if not allow_candidate_rerun:
                        raise PipelinePersistenceError(
                            f"Extraction run {run_number} already exists for job {job_id}. "
                            f"Rerun requires allow_candidate_rerun=True to replace unreviewed extraction data."
                        )
                    cursor.execute(
                        "DELETE FROM extraction_runs WHERE job_id = %s AND run_number = %s;",
                        (job_id, run_number),
                    )
                effective_run_number = run_number

            unified_run_record = ExtractionRunRecord(
                model_id=chunk_records[0].model_id if chunk_records else "gemini-2.0-flash",
                prompt_version=chunk_records[0].prompt_version if chunk_records else "1.0.0",
                schema_version=reconciled_payload.schema_version,
                validation_status=overall_validation_status,
                validation_errors=all_validation_errors,
                raw_response_json=combined_raw_json,
                candidate_payload=reconciled_payload,
                tokens_prompt=total_tokens_prompt,
                tokens_completion=total_tokens_completion,
                run_number=effective_run_number,
                job_id=job_id,
                episode_id=episode_id,
            )

            # Step E: Persist extraction run and candidate items
            persistence_res = CandidatePersistenceService.persist_candidate_extraction(
                cursor=cursor,
                episode_id=episode_id,
                extraction_run=unified_run_record,
                segment_index_to_id=segment_index_to_id,
                job_id=job_id,
            )

            # Step F: Update processing_jobs status/stage
            self._update_processing_job_status(
                cursor=cursor,
                job_id=job_id,
                status="completed",
                stage="human_review",
            )

            # Step G: Commit transaction atomically
            if hasattr(effective_connection, "commit") and callable(effective_connection.commit):
                effective_connection.commit()

        except (EditorialProtectionError, PipelineInputError):
            if hasattr(effective_connection, "rollback") and callable(effective_connection.rollback):
                effective_connection.rollback()
            raise
        except Exception as exc:
            if hasattr(effective_connection, "rollback") and callable(effective_connection.rollback):
                effective_connection.rollback()
            safe_err = _redact_secrets(str(exc))
            raise PipelinePersistenceError(f"Database persistence failed: {safe_err}") from exc
        finally:
            if cursor is not None and cursor is not effective_connection and hasattr(cursor, "close") and callable(cursor.close):
                try:
                    cursor.close()
                except Exception as close_exc:
                    logger.warning("Failed to close database cursor safely: %s", close_exc)

        # 13. Return verified execution result
        return PipelineExecutionResult(
            job_id=job_id,
            episode_id=episode_id,
            run_id=persistence_res.get("run_id"),
            status="completed",
            validation_status=overall_validation_status.value,
            segments_count=len(segments),
            chunks_count=chunks_count,
            insights_count=persistence_res.get("insights_inserted", 0),
            quotations_count=persistence_res.get("quotations_inserted", 0),
            evidence_count=persistence_res.get("evidence_inserted", 0),
            quotation_segments_count=persistence_res.get("quotation_segments_inserted", 0),
            validation_errors_count=len(all_validation_errors),
            diagnostics={
                "tokens_prompt": total_tokens_prompt,
                "tokens_completion": total_tokens_completion,
                "reconciliation": reconciliation_report.to_dict(),
                "chunks_processed": len(chunks),
                "effective_run_number": effective_run_number,
            },
        )

    def _validate_input(
        self,
        job_id: str,
        episode_id: str,
        transcript_content: Any,
        connection: Optional[Any],
        connection_factory: Optional[Callable[[], Any]],
        run_number: Optional[int] = None,
    ) -> None:
        """Validates mandatory identifiers, inputs, run_number, and database connection contract."""
        if not job_id or not isinstance(job_id, str) or not job_id.strip():
            raise PipelineInputError("Missing or invalid job_id: non-empty string is required.")
        if not episode_id or not isinstance(episode_id, str) or not episode_id.strip():
            raise PipelineInputError("Missing or invalid episode_id: non-empty string is required.")
        if run_number is not None:
            if not isinstance(run_number, int) or isinstance(run_number, bool) or run_number <= 0:
                raise PipelineInputError(f"run_number must be a positive integer (>= 1), got: {run_number!r}")
        if connection is None and connection_factory is None:
            raise PipelineInputError("Missing database connection: either connection or connection_factory is required.")
        if connection is not None:
            # Check for active transaction across database driver flavors (psycopg2, psycopg3, sqlite3, etc.)
            in_trans = False
            if hasattr(connection, "get_transaction_status") and callable(connection.get_transaction_status):
                # psycopg2 / psycopg: status 2 is TRANSACTION_STATUS_INTRANS
                in_trans = (connection.get_transaction_status() == 2)
            elif hasattr(connection, "in_transaction"):
                in_trans_val = getattr(connection, "in_transaction")
                in_trans = in_trans_val() if callable(in_trans_val) else bool(in_trans_val)
            elif hasattr(connection, "info") and hasattr(getattr(connection, "info"), "transaction_status"):
                in_trans = (getattr(connection.info, "transaction_status") == 2)

            if in_trans:
                raise PipelineInputError(
                    "Passed connection already has an active, uncommitted transaction. "
                    "Gemini AI extraction requires the connection to be idle."
                )
        if transcript_content is None:
            raise PipelineInputError("Missing transcript_content: content is required.")
        if isinstance(transcript_content, str) and not transcript_content.strip():
            raise PipelineInputError("transcript_content string cannot be empty or whitespace.")
        if isinstance(transcript_content, (dict, list)) and len(transcript_content) == 0:
            raise PipelineInputError("transcript_content collection cannot be empty.")

    @staticmethod
    def check_editorial_preflight(
        cursor: Any,
        episode_id: str,
        allow_candidate_rerun: bool = False,
        expected_youtube_video_id: Optional[str] = None,
        for_update: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes editorial preflight check before extraction or persistence:
        1. Confirms the target episode exists in the database.
        2. Confirms the episode is not published (publication_status != 'published').
        3. If expected_youtube_video_id is provided, verifies that episodes.youtube_video_id matches it.
        4. Confirms no reviewed editorial items (verified or rejected) exist for the episode.
        5. If prior unreviewed candidates or segments exist:
           - If allow_candidate_rerun is False: raises EditorialProtectionError.
           - If allow_candidate_rerun is True: permits rerun (returns has_unreviewed_data=True).

        Concurrency Contract:
            - When for_update=False: Strictly read-only preflight check without row locks. Used
              before Gemini extraction to avoid holding idle transaction locks.
            - When for_update=True: Acquires PostgreSQL row locks (FOR UPDATE) hierarchically:
              First on the parent episode row, then on existing child insights and quotations.
              Serializes candidate replacement against concurrent publication and editorial review.

        Raises:
            PipelineInputError: If episode does not exist or YouTube video ID mismatches.
            EditorialProtectionError: If episode is published, contains reviewed items, or has
                                     unpermitted prior candidate data.
        """
        # 1. Check episode existence, publication status, and YouTube video ID
        # Hierarchical lock level 1: parent episode row
        ep_query = (
            "SELECT publication_status, youtube_video_id FROM episodes WHERE id = %s FOR UPDATE;"
            if for_update
            else "SELECT publication_status, youtube_video_id FROM episodes WHERE id = %s;"
        )
        cursor.execute(ep_query, (episode_id,))
        row = cursor.fetchone()
        if not row:
            raise PipelineInputError(f"Episode {episode_id} does not exist in the database.")

        pub_status = str(row[0]) if row[0] is not None else ""
        ep_video_id = str(row[1]) if row[1] is not None else ""

        if pub_status == "published":
            raise EditorialProtectionError(
                f"Episode {episode_id} is already published; pipeline execution cannot modify published episodes."
            )

        if expected_youtube_video_id is not None:
            clean_expected = expected_youtube_video_id.strip()
            if clean_expected and ep_video_id != clean_expected:
                raise PipelineInputError(
                    f"Job YouTube video ID '{clean_expected}' does not match episode YouTube video ID '{ep_video_id}'."
                )

        # 2. Check for reviewed items (both verified and rejected)
        # Hierarchical lock level 2: child candidate and reviewed items
        if for_update:
            cursor.execute(
                "SELECT id, review_status FROM insights WHERE episode_id = %s FOR UPDATE;",
                (episode_id,),
            )
            insight_rows = cursor.fetchall() or []
            reviewed_ins_count = sum(1 for r in insight_rows if r[1] != "candidate")
            existing_cand_ins = sum(1 for r in insight_rows if r[1] == "candidate")

            cursor.execute(
                "SELECT id, review_status FROM quotations WHERE episode_id = %s FOR UPDATE;",
                (episode_id,),
            )
            quote_rows = cursor.fetchall() or []
            reviewed_q_count = sum(1 for r in quote_rows if r[1] != "candidate")
            existing_cand_q = sum(1 for r in quote_rows if r[1] == "candidate")
        else:
            cursor.execute(
                "SELECT count(*) FROM insights WHERE episode_id = %s AND review_status != 'candidate';",
                (episode_id,),
            )
            reviewed_ins_row = cursor.fetchone()
            reviewed_ins_count = int(reviewed_ins_row[0]) if reviewed_ins_row and reviewed_ins_row[0] is not None else 0

            cursor.execute(
                "SELECT count(*) FROM quotations WHERE episode_id = %s AND review_status != 'candidate';",
                (episode_id,),
            )
            reviewed_q_row = cursor.fetchone()
            reviewed_q_count = int(reviewed_q_row[0]) if reviewed_q_row and reviewed_q_row[0] is not None else 0

        if reviewed_ins_count > 0 or reviewed_q_count > 0:
            raise EditorialProtectionError(
                f"Episode {episode_id} contains {reviewed_ins_count} verified/reviewed insight(s) and "
                f"{reviewed_q_count} verified/reviewed quotation(s). Pipeline rerun is protected to prevent "
                f"overwriting human editorial approvals or rejections."
            )

        # 3. Check for existing prior candidates or segments
        cursor.execute(
            "SELECT count(*) FROM transcript_segments WHERE episode_id = %s;",
            (episode_id,),
        )
        seg_row = cursor.fetchone()
        existing_seg_count = int(seg_row[0]) if seg_row and seg_row[0] is not None else 0

        cursor.execute(
            "SELECT count(*) FROM transcript_chunks WHERE episode_id = %s;",
            (episode_id,),
        )
        chk_row = cursor.fetchone()
        existing_chk_count = int(chk_row[0]) if chk_row and chk_row[0] is not None else 0

        if not for_update:
            cursor.execute(
                "SELECT count(*) FROM insights WHERE episode_id = %s AND review_status = 'candidate';",
                (episode_id,),
            )
            cand_ins_row = cursor.fetchone()
            existing_cand_ins = int(cand_ins_row[0]) if cand_ins_row and cand_ins_row[0] is not None else 0

            cursor.execute(
                "SELECT count(*) FROM quotations WHERE episode_id = %s AND review_status = 'candidate';",
                (episode_id,),
            )
            cand_q_row = cursor.fetchone()
            existing_cand_q = int(cand_q_row[0]) if cand_q_row and cand_q_row[0] is not None else 0

        has_unreviewed_data = (
            existing_seg_count > 0
            or existing_chk_count > 0
            or existing_cand_ins > 0
            or existing_cand_q > 0
        )

        if has_unreviewed_data and not allow_candidate_rerun:
            raise EditorialProtectionError(
                f"Episode {episode_id} already contains persisted pipeline data "
                f"({existing_seg_count} segments, {existing_chk_count} chunks, "
                f"{existing_cand_ins} candidate insights, {existing_cand_q} candidate quotations). "
                f"Reruns must explicitly enable allow_candidate_rerun to replace unreviewed staging data."
            )

        return {
            "episode_id": episode_id,
            "publication_status": pub_status,
            "youtube_video_id": ep_video_id,
            "has_unreviewed_data": has_unreviewed_data,
            "segments_count": existing_seg_count,
            "chunks_count": existing_chk_count,
            "candidate_insights_count": existing_cand_ins,
            "candidate_quotations_count": existing_cand_q,
        }

    def _enforce_rerun_policy(
        self,
        cursor: Any,
        episode_id: str,
        allow_candidate_rerun: bool,
        expected_youtube_video_id: Optional[str] = None,
    ) -> None:
        """
        Enforces editorial protection and safe rerun policies inside the persistence transaction:
        Re-verifies all editorial preflight invariants under strict FOR UPDATE locks and,
        if allow_candidate_rerun is True and unreviewed staging data exists, executes
        foreign-key-safe deletions.
        """
        preflight_info = self.check_editorial_preflight(
            cursor=cursor,
            episode_id=episode_id,
            allow_candidate_rerun=allow_candidate_rerun,
            expected_youtube_video_id=expected_youtube_video_id,
            for_update=True,
        )

        if allow_candidate_rerun and preflight_info.get("has_unreviewed_data"):
            # Foreign-key-safe deletion order for unreviewed staging data:
            # 1. Candidate insights (cascades to insight_evidence)
            cursor.execute(
                "DELETE FROM insights WHERE episode_id = %s AND review_status = 'candidate';",
                (episode_id,),
            )
            # 2. Candidate quotations (cascades to quotation_segments)
            cursor.execute(
                "DELETE FROM quotations WHERE episode_id = %s AND review_status = 'candidate';",
                (episode_id,),
            )
            # 3. Transcript chunks
            cursor.execute("DELETE FROM transcript_chunks WHERE episode_id = %s;", (episode_id,))
            # 4. Transcript segments
            cursor.execute("DELETE FROM transcript_segments WHERE episode_id = %s;", (episode_id,))
            # 5. Unreferenced extraction runs for this episode
            cursor.execute(
                """
                DELETE FROM extraction_runs
                WHERE episode_id = %s
                  AND NOT EXISTS (SELECT 1 FROM insights WHERE extraction_run_id = extraction_runs.id)
                  AND NOT EXISTS (SELECT 1 FROM quotations WHERE extraction_run_id = extraction_runs.id);
                """,
                (episode_id,),
            )

    def _update_processing_job_status(
        self,
        cursor: Any,
        job_id: str,
        status: str = "completed",
        stage: str = "human_review",
        error_summary: Optional[str] = None,
    ) -> None:
        """Updates processing_jobs status and current_stage if the job row exists."""
        try:
            cursor.execute(
                """
                UPDATE processing_jobs
                SET status = %s::processing_job_status,
                    current_stage = %s::processing_stage,
                    error_summary = %s,
                    updated_at = now()
                WHERE id = %s;
                """,
                (status, stage, error_summary, job_id),
            )
        except Exception:
            # Non-fatal if processing_jobs mock does not track or if job record is omitted
            pass

    def _record_job_failure(
        self,
        connection: Any,
        job_id: str,
        stage: str,
        error_summary: str,
    ) -> None:
        """
        Persists a failed job state to processing_jobs in an isolated transaction.
        Non-fatal: failures during recording do not mask primary pipeline exceptions.
        """
        if connection is None or not job_id:
            return
        cursor = None
        try:
            cursor = connection.cursor() if hasattr(connection, "cursor") and callable(connection.cursor) else connection
            cursor.execute(
                """
                UPDATE processing_jobs
                SET status = 'failed'::processing_job_status,
                    current_stage = %s::processing_stage,
                    error_summary = %s,
                    updated_at = now()
                WHERE id = %s;
                """,
                (stage, error_summary[:500], job_id),
            )
            if hasattr(connection, "commit") and callable(connection.commit):
                connection.commit()
        except Exception as exc:
            logger.warning("Failed to record job failure in processing_jobs for job %s: %s", job_id, exc)
        finally:
            if cursor is not None and cursor is not connection and hasattr(cursor, "close") and callable(cursor.close):
                try:
                    cursor.close()
                except Exception:
                    pass
