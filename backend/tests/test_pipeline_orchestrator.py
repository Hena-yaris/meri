"""
Meri Content Pipeline v1: Unit tests for PipelineOrchestrator.

Verifies Milestone 4 Step 4.2 requirements:
1. Successful end-to-end orchestration (JSON and SRT transcript inputs).
2. Transcript parse/normalization failure prevents Gemini calls and candidate persistence.
3. Gemini failure prevents candidate persistence.
4. Invalid extraction payload prevents candidate persistence.
5. Cross-chunk reconciliation occurs before persistence.
6. Gemini is called before the database write transaction begins.
7. Persistence failure triggers rollback when supported.
8. Successful persistence commits exactly once.
9. Existing/published content is protected by the chosen rerun policy.
10. Missing or malformed job/episode identifiers fail before side effects.
11. No successful result is returned if any required chunk fails.
12. The result counts match the actual reconciled and persisted data.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import unittest
import urllib.request

from backend.src.candidate_persistence import (
    CandidatePersistenceService,
    EditorialAuthorizationError,
    SegmentReferenceIntegrityError,
)
from backend.src.candidate_reconciliation import (
    CandidateReconciler,
    PayloadReconciliationResult,
    ReconciliationReport,
)
from backend.src.chunker import TranscriptChunker
from backend.src.extraction_models import (
    CandidateEvidenceReference,
    CandidateExtractionPayload,
    CandidateGuestProfile,
    CandidateInsight,
    CandidateMilestone,
    CandidateQuotation,
    CandidateQuotationSegment,
    CandidateSummary,
    ExtractionRunRecord,
    ValidationErrorCode,
    ValidationErrorItem,
    ValidationSeverity,
    ValidationStatus,
)
from backend.src.extraction_service import ExtractionService
from backend.src.gemini_client import (
    GeminiClient,
    GeminiConfig,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
)
from backend.src.models import (
    NormalizedSegment,
    RawCue,
    TranscriptAcquisitionMethod,
    TranscriptChunk,
)
from backend.src.pipeline_orchestrator import (
    EditorialProtectionError,
    PipelineExecutionResult,
    PipelineExtractionError,
    PipelineInputError,
    PipelineOrchestrator,
    PipelineOrchestratorError,
    PipelinePersistenceError,
    PipelineValidationError,
)
from backend.src.transcript_normalizer import TranscriptNormalizer

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "schemas" / "fixtures"
TEST_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class MockDbCursor:
    """Mock cursor for database interactions during orchestration tests."""

    def __init__(self, connection: "MockDbConnection") -> None:
        self.connection = connection
        self.last_returning_row: Optional[Tuple[Any, ...]] = None

    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> None:
        clean_q = " ".join(query.strip().split())
        self.connection.timeline.append(f"db_execute: {clean_q[:40]}")
        self.connection.executed_queries.append((clean_q, params))

        if self.connection.fail_on_query_substring and self.connection.fail_on_query_substring in clean_q:
            raise RuntimeError(f"Simulated database error on query: {clean_q[:60]}")

        # 1. Episodes publication status query
        if "SELECT publication_status FROM episodes" in clean_q:
            ep_id = params[0] if params else None
            ep_data = self.connection.episodes.get(ep_id, {"publication_status": "draft"})
            self.last_returning_row = (ep_data["publication_status"],)

        # 2. Reviewed items count (verified or rejected)
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

        # 3. Existing unreviewed counts
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

        elif "SELECT count(*) FROM extraction_runs WHERE job_id = %s AND run_number = %s" in clean_q:
            job_id = params[0] if params else None
            run_num = params[1] if params and len(params) > 1 else 1
            count = sum(
                1 for r in self.connection.extraction_runs
                if r.get("job_id") == job_id and r.get("run_number") == run_num
            )
            self.last_returning_row = (count,)

        elif "SELECT COALESCE(MAX(run_number), 0) + 1 FROM extraction_runs" in clean_q:
            job_id = params[0] if params else None
            existing_runs = [
                r.get("run_number", 0) for r in self.connection.extraction_runs
                if r.get("job_id") == job_id
            ]
            next_num = max(existing_runs, default=0) + 1
            self.last_returning_row = (next_num,)

        # 4. Deletions for rerun cleanup
        elif "DELETE FROM insights WHERE episode_id = %s AND review_status = 'candidate'" in clean_q:
            ep_id = params[0] if params else None
            self.connection.insights = [
                ins for ins in self.connection.insights
                if not (ins["episode_id"] == ep_id and ins.get("review_status") == "candidate")
            ]
        elif "DELETE FROM quotations WHERE episode_id = %s AND review_status = 'candidate'" in clean_q:
            ep_id = params[0] if params else None
            self.connection.quotations = [
                q for q in self.connection.quotations
                if not (q["episode_id"] == ep_id and q.get("review_status") == "candidate")
            ]
        elif "DELETE FROM transcript_chunks WHERE episode_id = %s" in clean_q:
            ep_id = params[0] if params else None
            self.connection.transcript_chunks = [
                chk for chk in self.connection.transcript_chunks if chk["episode_id"] != ep_id
            ]
        elif "DELETE FROM transcript_segments WHERE episode_id = %s" in clean_q:
            ep_id = params[0] if params else None
            self.connection.transcript_segments = [
                seg for seg in self.connection.transcript_segments if seg["episode_id"] != ep_id
            ]
        elif "DELETE FROM extraction_runs" in clean_q:
            ep_id = params[0] if params else None
            self.connection.extraction_runs = [
                r for r in self.connection.extraction_runs if r.get("episode_id") != ep_id
            ]

        # 5. Insert transcript segments
        elif "INSERT INTO transcript_segments" in clean_q:
            seg_id = f"seg-uuid-{self.connection.next_id_counter}"
            self.connection.next_id_counter += 1
            seg_idx = params[1] if params and len(params) > 1 else 0
            self.last_returning_row = (seg_idx, seg_id)
            if params:
                self.connection.transcript_segments.append({
                    "id": seg_id,
                    "episode_id": params[0],
                    "segment_index": params[1],
                    "start_ms": params[2],
                    "end_ms": params[3],
                    "speaker_label": params[4],
                    "language_code": params[5],
                    "acquisition_method": params[6],
                    "text": params[7],
                    "confidence": params[8],
                })

        # 6. Insert transcript chunks
        elif "INSERT INTO transcript_chunks" in clean_q:
            chk_id = f"chunk-uuid-{self.connection.next_id_counter}"
            self.connection.next_id_counter += 1
            self.last_returning_row = (chk_id,)
            if params:
                self.connection.transcript_chunks.append({
                    "id": chk_id,
                    "episode_id": params[0],
                    "chunk_index": params[1],
                    "start_segment_index": params[2],
                    "end_segment_index": params[3],
                    "start_ms": params[4],
                    "end_ms": params[5],
                    "token_count_estimate": params[6],
                    "chunk_text": params[7],
                })

        # 7. Insert extraction runs
        elif "INSERT INTO extraction_runs" in clean_q:
            run_id = f"run-uuid-{self.connection.next_id_counter}"
            self.connection.next_id_counter += 1
            self.last_returning_row = (run_id,)
            if params:
                self.connection.extraction_runs.append({
                    "id": run_id,
                    "job_id": params[0],
                    "episode_id": params[1],
                    "run_number": params[2],
                    "model_id": params[3],
                    "prompt_version": params[4],
                    "raw_response_json": params[5],
                    "validation_status": params[6],
                    "validation_errors": params[7],
                    "tokens_prompt": params[8],
                    "tokens_completion": params[9],
                })

        # 8. Insert insights
        elif "INSERT INTO insights" in clean_q:
            ins_id = f"insight-uuid-{self.connection.next_id_counter}"
            self.connection.next_id_counter += 1
            self.last_returning_row = (ins_id,)
            if params:
                self.connection.insights.append({
                    "id": ins_id,
                    "episode_id": params[0],
                    "extraction_run_id": params[1],
                    "category": params[2],
                    "title": params[3],
                    "summary": params[4],
                    "takeaways": params[5],
                    "practical_action": params[6],
                    "display_order": params[7],
                    "review_status": "candidate",
                })

        # 9. Insert insight evidence
        elif "INSERT INTO insight_evidence" in clean_q:
            if params:
                self.connection.insight_evidence.append({
                    "insight_id": params[0],
                    "segment_id": params[1],
                    "relevance_score": params[2],
                    "claim_quote_snippet": params[3],
                    "notes": params[4] if len(params) > 4 else None,
                })

        # 10. Insert quotations
        elif "INSERT INTO quotations" in clean_q:
            q_id = f"quotation-uuid-{self.connection.next_id_counter}"
            self.connection.next_id_counter += 1
            self.last_returning_row = (q_id,)
            if params:
                self.connection.quotations.append({
                    "id": q_id,
                    "episode_id": params[0],
                    "extraction_run_id": params[1],
                    "segment_id": params[2],
                    "amharic_quote": params[3],
                    "english_translation": params[4],
                    "speaker": params[5],
                    "timestamp_seconds": params[6],
                    "context": params[7],
                    "display_order": params[8],
                    "review_status": "candidate",
                })

        # 11. Insert quotation segments
        elif "INSERT INTO quotation_segments" in clean_q:
            if params:
                self.connection.quotation_segments.append({
                    "quotation_id": params[0],
                    "segment_id": params[1],
                    "sequence_order": params[2],
                })

        # 12. Update processing jobs
        elif "UPDATE processing_jobs" in clean_q:
            if params:
                self.connection.processing_jobs_updates.append({
                    "status": params[0] if len(params) > 0 else None,
                    "stage": params[1] if len(params) > 1 else None,
                    "error_summary": params[2] if len(params) > 2 else None,
                    "job_id": params[3] if len(params) > 3 else (params[2] if len(params) == 3 else None),
                })

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        row = self.last_returning_row
        self.last_returning_row = None
        return row

    def close(self) -> None:
        self.connection.timeline.append("cursor_close")


class MockDbConnection:
    """Mock database connection providing PEP 249 commit and rollback semantics."""

    def __init__(self) -> None:
        self.timeline: List[str] = []
        self.executed_queries: List[Tuple[str, Any]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.next_id_counter = 100
        self.fail_on_query_substring: Optional[str] = None
        self.fail_on_commit = False
        self.transaction_status = 0  # 0: IDLE, 2: INTRANS

        self.episodes: Dict[str, Dict[str, Any]] = {
            "ep-uuid-test": {"id": "ep-uuid-test", "publication_status": "draft"}
        }
        self.transcript_segments: List[Dict[str, Any]] = []
        self.transcript_chunks: List[Dict[str, Any]] = []
        self.extraction_runs: List[Dict[str, Any]] = []
        self.insights: List[Dict[str, Any]] = []
        self.insight_evidence: List[Dict[str, Any]] = []
        self.quotations: List[Dict[str, Any]] = []
        self.quotation_segments: List[Dict[str, Any]] = []
        self.processing_jobs_updates: List[Dict[str, Any]] = []

    def cursor(self) -> MockDbCursor:
        self.timeline.append("db_cursor_opened")
        return MockDbCursor(self)

    def commit(self) -> None:
        self.timeline.append("db_commit")
        if self.fail_on_commit:
            raise RuntimeError("Database commit error simulated.")
        self.commit_count += 1

    def rollback(self) -> None:
        self.timeline.append("db_rollback")
        self.rollback_count += 1

    def get_transaction_status(self) -> int:
        return self.transaction_status


def create_sample_gemini_response_payload(
    evidence_segment_indices: List[int] = [1],
    source_segment_index: int = 1,
    amharic_quote: str = "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
    quote_timestamp: int = 14,
    insight_title: str = "የሎጂስቲክስ ስራ እና የመንገድ ላይ ብክነት",
    insight_category: str = "Operations",
) -> Dict[str, Any]:
    """Builds a valid candidate extraction response payload matching fixture segments."""
    return {
        "schema_version": "1.0.0",
        "episode_summary": {
            "brief": "ውይይት ስለ ኢትዮጵያ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ እና የገበሬዎች ምርት አያያዝ።",
            "comprehensive": "ዳዊት ታደሰ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ በኢትዮጵያ ያለውን ተግዳሮት እና መፍትሄዎች በሰፊው ያብራራል። በመንገድ ላይ የሚባክነውን የገበሬዎች ምርት ለመቀነስ የተከተሏቸውን ዘዴዎች እና የቴክኖሎጂ አጠቃቀም ይተነትናል።",
            "primary_themes": ["Logistics", "Cold Chain", "Agriculture"],
        },
        "guest_profile": {
            "name": "Dawit Tadesse",
            "title": "Founder & Managing Director",
            "company": "Nile Cold Chain Logistics",
            "bio": "Mechanical engineer turned logistics entrepreneur who spent 8 years designing modular refrigerated containers.",
            "industry": "Agricultural Logistics & Cold Storage",
            "journey_summary": "Pivoted from pure engineering consultancy into logistics after witnessing harvest spoilage.",
        },
        "journey_milestones": [
            {
                "phase_or_year": "2020",
                "milestone_description": "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ።",
                "strategic_decision": "የነባር መኪናዎችን ማሻሻል ተመረጠ።",
                "evidence_segment_indices": evidence_segment_indices,
            }
        ],
        "insights": [
            {
                "title": insight_title,
                "category": insight_category,
                "summary": "መኪና ከመግዛት ይልቅ በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ዋናው ቁልፍ ነው።",
                "takeaways": [
                    "የምርት ብክነትን በሰከንድ መለካት ወሳኝ ነው።",
                    "የነባር ተሽከርካሪዎችን አቅም ማሳደግ ካፒታልን ይቆጥባል።",
                ],
                "practical_action": "በመጓጓዣ መስመሮች ላይ ያለውን የሙቀት መጠን እና ብክነት በየጊዜው መመዝገብ።",
                "evidence_segment_indices": evidence_segment_indices,
                "confidence_score": 0.95,
            }
        ],
        "quotations": [
            {
                "amharic_quote": amharic_quote,
                "english_translation": "The greatest test in logistics isn't buying trucks; it's calculating the value of wasted produce.",
                "speaker": "Dawit Tadesse",
                "source_segment_index": source_segment_index,
                "timestamp_seconds": quote_timestamp,
                "context": "ስለ ሎጂስቲክስ ስራ ፈተናዎች ሲያብራራ የተናገረው።",
                "importance_rationale": "የንግዱን ዋና ፍልስፍና ያሳያል።",
            }
        ],
        "suggested_tags": ["Logistics", "Ethiopia", "Supply Chain"],
    }


class TestPipelineOrchestrator(unittest.TestCase):
    """Exhaustive test suite for PipelineOrchestrator."""

    def setUp(self) -> None:
        self.job_id = "job-uuid-001"
        self.episode_id = "ep-uuid-test"
        with open(TEST_FIXTURES_DIR / "sample_transcript.json", "r", encoding="utf-8") as f:
            self.transcript_json_str = f.read()

        with open(TEST_FIXTURES_DIR / "sample_transcript.srt", "r", encoding="utf-8") as f:
            self.transcript_srt_str = f.read()

        self.db_conn = MockDbConnection()
        self.timeline: List[str] = []

    def _build_mock_gemini_client(
        self,
        response_data: Optional[Dict[str, Any]] = None,
        exception_to_raise: Optional[Exception] = None,
        timeline_hook: Optional[List[str]] = None,
    ) -> GeminiClient:
        """Constructs a mock GeminiClient with deterministic response or error."""
        if response_data is None:
            response_data = create_sample_gemini_response_payload()

        api_response_body = json.dumps({
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(response_data)}]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 500,
                "candidatesTokenCount": 250,
            },
        })

        def mock_transport(req: urllib.request.Request, timeout: float):
            if timeline_hook is not None:
                timeline_hook.append("gemini_call")
            if exception_to_raise:
                raise exception_to_raise
            return 200, {}, api_response_body

        return GeminiClient(
            config=GeminiConfig(model_id="gemini-2.0-flash", api_key="test-key-mock"),
            transport=mock_transport,
        )

    # =========================================================================
    # Test 1: Successful end-to-end orchestration
    # =========================================================================
    def test_successful_end_to_end_orchestration_json(self) -> None:
        """Tests complete pipeline run from JSON transcript to committed database persistence."""
        gemini_client = self._build_mock_gemini_client(timeline_hook=self.timeline)
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        result = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_json_str,
            connection=self.db_conn,
            format_hint="json",
        )

        self.assertIsInstance(result, PipelineExecutionResult)
        self.assertEqual(result.job_id, self.job_id)
        self.assertEqual(result.episode_id, self.episode_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.validation_status, "passed")
        self.assertEqual(result.segments_count, 4)
        self.assertGreaterEqual(result.chunks_count, 1)
        self.assertEqual(result.insights_count, 1)
        self.assertEqual(result.quotations_count, 1)
        self.assertEqual(result.evidence_count, 1)
        self.assertEqual(result.quotation_segments_count, 1)
        self.assertEqual(result.validation_errors_count, 0)
        self.assertIsNotNone(result.run_id)

        # Diagnostics check
        self.assertEqual(result.diagnostics["tokens_prompt"], 500)
        self.assertEqual(result.diagnostics["tokens_completion"], 250)
        self.assertIn("reconciliation", result.diagnostics)

        # Transaction check: committed exactly once, zero rollbacks
        self.assertEqual(self.db_conn.commit_count, 1)
        self.assertEqual(self.db_conn.rollback_count, 0)

        # Database state verification
        self.assertEqual(len(self.db_conn.transcript_segments), 4)
        self.assertEqual(len(self.db_conn.extraction_runs), 1)
        self.assertEqual(len(self.db_conn.insights), 1)
        self.assertEqual(len(self.db_conn.quotations), 1)
        self.assertEqual(len(self.db_conn.insight_evidence), 1)
        self.assertEqual(len(self.db_conn.quotation_segments), 1)

    def test_successful_end_to_end_orchestration_srt(self) -> None:
        """Tests complete pipeline run from SRT transcript input."""
        # SRT sample has segments: 0 ("እንኳን ደህና መጣችሁ"), 1 ("የሎጂስቲክስ ስራ ትልቁ ፈተና...")
        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        result = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_srt_str,
            connection=self.db_conn,
            format_hint="srt",
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.segments_count, 4)
        self.assertEqual(self.db_conn.commit_count, 1)
        self.assertEqual(self.db_conn.rollback_count, 0)

    # =========================================================================
    # Test 2: Transcript parse/normalization failure prevents Gemini & DB
    # =========================================================================
    def test_transcript_parse_failure_prevents_gemini_and_persistence(self) -> None:
        """Parse error must immediately halt pipeline before Gemini call or DB interaction."""
        gemini_client = self._build_mock_gemini_client(timeline_hook=self.timeline)
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(PipelineExtractionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content="INVALID NOT A TRANSCRIPT FORMAT",
                connection=self.db_conn,
                format_hint="json",
            )

        self.assertIn("Transcript parsing failed", str(ctx.exception))
        # Ensure Gemini was never invoked
        self.assertEqual(len(self.timeline), 0)
        # Ensure database was never touched
        self.assertEqual(len(self.db_conn.executed_queries), 0)
        self.assertEqual(self.db_conn.commit_count, 0)
        self.assertEqual(self.db_conn.rollback_count, 0)

    def test_transcript_empty_cues_fails_before_gemini_and_db(self) -> None:
        """Empty transcript structure producing zero cues fails before Gemini or DB."""
        gemini_client = self._build_mock_gemini_client(timeline_hook=self.timeline)
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(PipelineExtractionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content={"format": "segments_json", "segments": []},
                connection=self.db_conn,
            )

        self.assertEqual(len(self.timeline), 0)
        self.assertEqual(len(self.db_conn.executed_queries), 0)

    # =========================================================================
    # Test 3: Gemini failure prevents candidate persistence
    # =========================================================================
    def test_gemini_failure_prevents_candidate_persistence(self) -> None:
        """Remote LLM failure raises PipelineExtractionError and executes zero DB writes."""
        gemini_client = self._build_mock_gemini_client(
            exception_to_raise=GeminiServiceUnavailableError("Gemini service unavailable 503"),
            timeline_hook=self.timeline,
        )
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(PipelineExtractionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
            )

        self.assertIn("Gemini candidate extraction failed", str(ctx.exception))
        self.assertIn("gemini_call", self.timeline)
        # Database was never accessed
        self.assertEqual(len(self.db_conn.executed_queries), 0)
        self.assertEqual(self.db_conn.commit_count, 0)
        self.assertEqual(self.db_conn.rollback_count, 0)

    # =========================================================================
    # Test 4: Invalid extraction payload prevents candidate persistence
    # =========================================================================
    def test_invalid_extraction_payload_prevents_persistence(self) -> None:
        """Extraction payload failing validation raises PipelineValidationError and touches zero DB."""
        # Referencing non-existent segment index 999 produces a critical semantic error
        invalid_payload = create_sample_gemini_response_payload(
            evidence_segment_indices=[999],
            source_segment_index=999,
        )
        gemini_client = self._build_mock_gemini_client(
            response_data=invalid_payload,
            timeline_hook=self.timeline,
        )
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(PipelineValidationError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
            )

        self.assertIn("Validation failed", str(ctx.exception))
        # Ensure database was never touched
        self.assertEqual(len(self.db_conn.executed_queries), 0)
        self.assertEqual(self.db_conn.commit_count, 0)
        self.assertEqual(self.db_conn.rollback_count, 0)

    # =========================================================================
    # Test 5: Cross-chunk reconciliation occurs before persistence
    # =========================================================================
    def test_cross_chunk_reconciliation_occurs_before_persistence(self) -> None:
        """Duplicate candidates across overlapping chunks are merged before writing to database."""
        # Create an orchestrator with a small chunk size to force multiple chunks
        small_chunker = TranscriptChunker(target_chunk_words=10, overlap_words=4)
        from backend.src.transcript_parser import parse_transcript
        cues = parse_transcript(self.transcript_json_str)
        segments = TranscriptNormalizer().normalize(cues)
        chunks = small_chunker.chunk(segments)
        self.assertGreaterEqual(len(chunks), 2, "Test prerequisite: must have at least 2 chunks")

        # Mock extraction service to return duplicate insight across both chunks
        timeline_events: List[str] = []

        class MockMultiChunkExtractionService(ExtractionService):
            def __init__(self) -> None:
                super().__init__(gemini_client=GeminiClient(GeminiConfig(api_key="mock")))

            def extract_and_validate(self, segments, chunks, job_id, episode_id, run_number):
                chunk = chunks[0]
                timeline_events.append(f"extract_chunk_{chunk.chunk_index}")
                # Both chunks extract duplicate insight and quote
                return ExtractionRunRecord(
                    model_id="gemini-2.0-flash",
                    prompt_version="1.0.0",
                    schema_version="1.0.0",
                    validation_status=ValidationStatus.PASSED,
                    validation_errors=[],
                    candidate_payload=CandidateExtractionPayload(
                        schema_version="1.0.0",
                        episode_summary=CandidateSummary(brief="B", comprehensive="C", primary_themes=[]),
                        guest_profile=CandidateGuestProfile(name="N", title="T", company="C", bio="B", industry="I"),
                        journey_milestones=[],
                        insights=[
                            CandidateInsight(
                                title="የሎጂስቲክስ ስራ እና የመንገድ ላይ ብክነት",
                                category="Operations",
                                summary="መኪና ከመግዛት ይልቅ በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት።",
                                takeaways=["ብክነትን በሰከንድ መለካት"],
                                practical_action="በየጊዜው መመዝገብ",
                                evidence_segment_indices=[1] if chunk.chunk_index == 0 else [1, 3],
                                confidence_score=0.95,
                            )
                        ],
                        quotations=[
                            CandidateQuotation(
                                amharic_quote="የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
                                english_translation="Logistics quote",
                                speaker="Dawit Tadesse",
                                source_segment_indices=[1],
                                canonical_start_ms=14201,
                                canonical_timestamp_seconds=14,
                                context="Context",
                            )
                        ],
                        suggested_tags=["Logistics"],
                        evidence_references=[
                            CandidateEvidenceReference(
                                insight_index=0,
                                segment_index=1 if chunk.chunk_index == 0 else 3,
                                relevance_score=0.9,
                                claim_quote_snippet="snippet",
                                notes=f"from_chunk_{chunk.chunk_index}",
                            )
                        ],
                        quotation_segments=[
                            CandidateQuotationSegment(quotation_index=0, segment_index=1, sequence_order=0)
                        ],
                    ),
                    tokens_prompt=300,
                    tokens_completion=150,
                )

        orchestrator = PipelineOrchestrator(
            extraction_service=MockMultiChunkExtractionService(),
            chunker=small_chunker,
        )

        result = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_json_str,
            connection=self.db_conn,
        )

        # 2 chunks were processed
        self.assertGreaterEqual(result.chunks_count, 2)
        # Duplicate insight was reconciled into 1
        self.assertEqual(result.insights_count, 1)
        # Duplicate quotation was reconciled into 1
        self.assertEqual(result.quotations_count, 1)
        # Evidence was merged: 2 evidence links from the two chunks
        self.assertEqual(result.evidence_count, 2)
        # Database only contains 1 reconciled insight
        self.assertEqual(len(self.db_conn.insights), 1)
        self.assertEqual(len(self.db_conn.quotations), 1)
        self.assertEqual(len(self.db_conn.insight_evidence), 2)

    # =========================================================================
    # Test 6: Gemini is called before database write transaction begins
    # =========================================================================
    def test_gemini_called_before_db_write_transaction_begins(self) -> None:
        """Strict temporal check: all Gemini calls must finish before opening DB cursor or writing."""
        shared_timeline: List[str] = []

        gemini_client = self._build_mock_gemini_client(timeline_hook=shared_timeline)
        # Link connection timeline to shared timeline
        self.db_conn.timeline = shared_timeline

        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)
        result = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_json_str,
            connection=self.db_conn,
        )

        self.assertEqual(result.status, "completed")
        self.assertIn("gemini_call", shared_timeline)
        self.assertIn("db_cursor_opened", shared_timeline)

        first_gemini_idx = shared_timeline.index("gemini_call")
        first_cursor_idx = shared_timeline.index("db_cursor_opened")

        # Invariant: Gemini MUST execute strictly before database cursor is opened
        self.assertLess(
            first_gemini_idx,
            first_cursor_idx,
            f"Gemini was called after or during database transaction! Timeline: {shared_timeline}",
        )

    # =========================================================================
    # Test 7: Persistence failure triggers rollback when supported
    # =========================================================================
    def test_persistence_failure_triggers_rollback(self) -> None:
        """Database error during candidate insert triggers rollback and raises PipelinePersistenceError."""
        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        # Inject error when inserting insights
        self.db_conn.fail_on_query_substring = "INSERT INTO insights"

        with self.assertRaises(PipelinePersistenceError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
            )

        self.assertIn("Database persistence failed", str(ctx.exception))
        self.assertEqual(self.db_conn.rollback_count, 1)
        self.assertEqual(self.db_conn.commit_count, 0)

    # =========================================================================
    # Test 8: Successful persistence commits exactly once
    # =========================================================================
    def test_successful_persistence_commits_exactly_once(self) -> None:
        """A successful execution calls connection.commit() exactly once."""
        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        result = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_json_str,
            connection=self.db_conn,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(self.db_conn.commit_count, 1)
        self.assertEqual(self.db_conn.rollback_count, 0)

    # =========================================================================
    # Test 9: Rerun policy and editorial protection
    # =========================================================================
    def test_rerun_policy_protects_published_episode(self) -> None:
        """Episodes with publication_status='published' cannot be modified by the pipeline."""
        self.db_conn.episodes[self.episode_id] = {"id": self.episode_id, "publication_status": "published"}

        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(EditorialProtectionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
                allow_candidate_rerun=True,
            )

        self.assertIn("already published", str(ctx.exception))
        self.assertEqual(self.db_conn.rollback_count, 1)
        self.assertEqual(self.db_conn.commit_count, 0)
        self.assertEqual(len(self.db_conn.transcript_segments), 0)

    def test_rerun_policy_protects_verified_content(self) -> None:
        """Episodes with human-verified insights or quotations cannot be overwritten."""
        self.db_conn.insights.append({
            "id": "ins-verified-01",
            "episode_id": self.episode_id,
            "title": "Human Verified Insight",
            "review_status": "verified",
        })

        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(EditorialProtectionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
                allow_candidate_rerun=True,
            )

        self.assertIn("contains 1 verified/reviewed insight(s)", str(ctx.exception))
        self.assertEqual(self.db_conn.rollback_count, 1)
        self.assertEqual(self.db_conn.commit_count, 0)

    def test_rerun_policy_protects_rejected_content(self) -> None:
        """Episodes with human-rejected insights or quotations cannot be overwritten or deleted."""
        self.db_conn.insights.append({
            "id": "ins-rejected-01",
            "episode_id": self.episode_id,
            "title": "Human Rejected Insight",
            "review_status": "rejected",
        })

        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(EditorialProtectionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
                allow_candidate_rerun=True,
            )

        self.assertIn("contains 1 verified/reviewed insight(s)", str(ctx.exception))
        self.assertEqual(self.db_conn.rollback_count, 1)
        self.assertEqual(self.db_conn.commit_count, 0)

    def test_connection_factory_deferred_execution(self) -> None:
        """Connection factory is invoked only after Gemini extraction and validation succeed."""
        timeline: List[str] = []
        gemini_client = self._build_mock_gemini_client(timeline_hook=timeline)

        def test_factory() -> MockDbConnection:
            timeline.append("factory_invoked")
            self.db_conn.timeline = timeline
            return self.db_conn

        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)
        result = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_json_str,
            connection_factory=test_factory,
        )

        self.assertEqual(result.status, "completed")
        self.assertIn("gemini_call", timeline)
        self.assertIn("factory_invoked", timeline)
        gemini_idx = timeline.index("gemini_call")
        factory_idx = timeline.index("factory_invoked")
        self.assertLess(gemini_idx, factory_idx, "Connection factory must be called after Gemini finishes.")

    def test_active_transaction_rejected(self) -> None:
        """Connections in an active transaction state (INTRANS) fail preflight check."""
        self.db_conn.transaction_status = 2  # 2: INTRANS

        orchestrator = PipelineOrchestrator(gemini_client=self._build_mock_gemini_client())
        with self.assertRaises(PipelineInputError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
            )

        self.assertIn("active, uncommitted transaction", str(ctx.exception))

    def test_run_number_auto_increment(self) -> None:
        """When run_number is None, next available run_number is queried automatically."""
        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        result1 = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_json_str,
            connection=self.db_conn,
            run_number=None,
        )
        self.assertEqual(result1.diagnostics["effective_run_number"], 1)

    def test_run_number_conflict_rejected_when_rerun_false(self) -> None:
        """Fixed run_number already existing raises PipelinePersistenceError when rerun=False."""
        self.db_conn.extraction_runs.append({
            "id": "run-existing-1",
            "job_id": self.job_id,
            "run_number": 1,
            "episode_id": self.episode_id,
        })

        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(PipelinePersistenceError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
                run_number=1,
                allow_candidate_rerun=False,
            )

        self.assertIn("already exists for job", str(ctx.exception))

    def test_rerun_policy_rejects_unreviewed_data_when_flag_false(self) -> None:
        """Existing candidate data is protected if allow_candidate_rerun=False."""
        self.db_conn.transcript_segments.append({
            "id": "old-seg-01",
            "episode_id": self.episode_id,
            "segment_index": 0,
        })
        self.db_conn.insights.append({
            "id": "old-cand-01",
            "episode_id": self.episode_id,
            "title": "Prior Candidate",
            "review_status": "candidate",
        })

        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(EditorialProtectionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
                allow_candidate_rerun=False,
            )

        self.assertIn("Reruns must explicitly enable allow_candidate_rerun", str(ctx.exception))
        self.assertEqual(self.db_conn.rollback_count, 1)
        self.assertEqual(self.db_conn.commit_count, 0)

    def test_rerun_policy_replaces_unreviewed_data_when_flag_true(self) -> None:
        """When allow_candidate_rerun=True, unreviewed candidate data is cleanly replaced."""
        self.db_conn.transcript_segments.append({
            "id": "old-seg-01",
            "episode_id": self.episode_id,
            "segment_index": 0,
        })
        self.db_conn.insights.append({
            "id": "old-cand-01",
            "episode_id": self.episode_id,
            "title": "Prior Candidate",
            "review_status": "candidate",
        })

        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        result = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_json_str,
            connection=self.db_conn,
            allow_candidate_rerun=True,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(self.db_conn.commit_count, 1)
        self.assertEqual(self.db_conn.rollback_count, 0)
        # Old items were replaced
        self.assertEqual(len(self.db_conn.insights), 1)
        self.assertNotEqual(self.db_conn.insights[0]["title"], "Prior Candidate")

    # =========================================================================
    # Test 10: Missing or malformed identifiers fail before side effects
    # =========================================================================
    def test_missing_or_malformed_identifiers_fail_before_side_effects(self) -> None:
        """Validates all input parameter constraints before calling Gemini or DB."""
        orchestrator = PipelineOrchestrator(gemini_client=self._build_mock_gemini_client())

        invalid_inputs = [
            ("", self.episode_id, self.transcript_json_str, self.db_conn),
            ("   ", self.episode_id, self.transcript_json_str, self.db_conn),
            (None, self.episode_id, self.transcript_json_str, self.db_conn),
            (self.job_id, "", self.transcript_json_str, self.db_conn),
            (self.job_id, "   ", self.transcript_json_str, self.db_conn),
            (self.job_id, None, self.transcript_json_str, self.db_conn),
            (self.job_id, self.episode_id, "", self.db_conn),
            (self.job_id, self.episode_id, "   ", self.db_conn),
            (self.job_id, self.episode_id, None, self.db_conn),
            (self.job_id, self.episode_id, self.transcript_json_str, None),
        ]

        for j_id, ep_id, content, conn in invalid_inputs:
            with self.subTest(j_id=j_id, ep_id=ep_id, content=type(content), conn=type(conn)):
                with self.assertRaises(PipelineInputError):
                    orchestrator.run(
                        job_id=j_id,
                        episode_id=ep_id,
                        transcript_content=content,
                        connection=conn,
                    )

        # Zero DB calls, zero commits
        self.assertEqual(len(self.db_conn.executed_queries), 0)
        self.assertEqual(self.db_conn.commit_count, 0)

    # =========================================================================
    # Test 11: No successful result is returned if any required chunk fails
    # =========================================================================
    def test_no_successful_result_if_any_required_chunk_fails(self) -> None:
        """In a multi-chunk run, failure on any chunk fails the pipeline without partial persistence."""
        small_chunker = TranscriptChunker(target_chunk_words=10, overlap_words=4)

        call_count = 0

        class MockFailingSecondChunkService(ExtractionService):
            def __init__(self) -> None:
                super().__init__(gemini_client=GeminiClient(GeminiConfig(api_key="mock")))

            def extract_and_validate(self, segments, chunks, job_id, episode_id, run_number):
                nonlocal call_count
                call_count += 1
                chunk = chunks[0]
                if chunk.chunk_index == 1:
                    # Second chunk fails extraction
                    raise GeminiTimeoutError("Gemini timed out on chunk 1")
                # First chunk succeeds
                return ExtractionRunRecord(
                    model_id="gemini-2.0-flash",
                    prompt_version="1.0.0",
                    schema_version="1.0.0",
                    validation_status=ValidationStatus.PASSED,
                    validation_errors=[],
                    candidate_payload=CandidateExtractionPayload(
                        schema_version="1.0.0",
                        episode_summary=CandidateSummary(brief="B", comprehensive="C", primary_themes=[]),
                        guest_profile=CandidateGuestProfile(name="N", title="T", company="C", bio="B", industry="I"),
                        journey_milestones=[],
                        insights=[],
                        quotations=[],
                        suggested_tags=["Logistics"],
                    ),
                )

        orchestrator = PipelineOrchestrator(
            extraction_service=MockFailingSecondChunkService(),
            chunker=small_chunker,
        )

        with self.assertRaises(PipelineExtractionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
            )

        self.assertIn("chunk 1", str(ctx.exception))
        # Ensure zero DB writes committed
        self.assertEqual(self.db_conn.commit_count, 0)
        self.assertEqual(len(self.db_conn.transcript_segments), 0)

    # =========================================================================
    # Test 12: Result counts match actual persisted data
    # =========================================================================
    def test_result_counts_match_actual_persisted_data(self) -> None:
        """Execution result counts strictly equal rows inserted into each table."""
        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        result = orchestrator.run(
            job_id=self.job_id,
            episode_id=self.episode_id,
            transcript_content=self.transcript_json_str,
            connection=self.db_conn,
        )

        self.assertEqual(result.segments_count, len(self.db_conn.transcript_segments))
        self.assertEqual(result.chunks_count, len(self.db_conn.transcript_chunks))
        self.assertEqual(result.insights_count, len(self.db_conn.insights))
        self.assertEqual(result.quotations_count, len(self.db_conn.quotations))
        self.assertEqual(result.evidence_count, len(self.db_conn.insight_evidence))
        self.assertEqual(result.quotation_segments_count, len(self.db_conn.quotation_segments))

    # =========================================================================
    # Test 13: Redaction of secrets in pipeline exception messages
    # =========================================================================
    def test_secret_redaction_in_exceptions(self) -> None:
        """Ensures API keys and credentials in URLs are redacted in exception messages."""
        fake_api_key = "AIzaSySecretApiKey1234567890"
        gemini_client = self._build_mock_gemini_client(
            exception_to_raise=RuntimeError(
                f"Failed connecting to https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={fake_api_key}"
            )
        )
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(PipelineExtractionError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=self.db_conn,
            )

        self.assertNotIn(fake_api_key, str(ctx.exception))
        self.assertIn("[REDACTED]", str(ctx.exception))

    def test_secret_redaction_db_uri(self) -> None:
        """Ensures database credentials embedded in URIs are redacted in persistence exceptions."""
        db_conn = MockDbConnection()
        db_conn.fail_on_query_substring = "SELECT publication_status"
        # Inject an exception with an embedded database connection string
        def failing_cursor():
            raise RuntimeError("Connection failed to postgres://service_admin:p@ssw0rd123!@db.supabase.co:5432/postgres")
        db_conn.cursor = failing_cursor

        gemini_client = self._build_mock_gemini_client()
        orchestrator = PipelineOrchestrator(gemini_client=gemini_client)

        with self.assertRaises(PipelinePersistenceError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=db_conn,
            )

        self.assertNotIn("p@ssw0rd123!", str(ctx.exception))
        self.assertIn("service_admin:[REDACTED]@", str(ctx.exception))

    def test_invalid_run_number_rejected(self) -> None:
        """Validates that non-positive or non-integer run_numbers are rejected before execution."""
        orchestrator = PipelineOrchestrator(gemini_client=self._build_mock_gemini_client())

        for invalid_run in [0, -1, -99, "first", 1.5, True]:
            with self.subTest(run_number=invalid_run):
                with self.assertRaises(PipelineInputError) as ctx:
                    orchestrator.run(
                        job_id=self.job_id,
                        episode_id=self.episode_id,
                        transcript_content=self.transcript_json_str,
                        connection=self.db_conn,
                        run_number=invalid_run,  # type: ignore[arg-type]
                    )
                self.assertIn("run_number must be a positive integer", str(ctx.exception))

    def test_connection_in_transaction_property_rejected(self) -> None:
        """Connection objects exposing in_transaction=True fail preflight check."""
        class MockTxConn:
            in_transaction = True
            def cursor(self):
                return self
            def execute(self, *args, **kwargs):
                pass

        orchestrator = PipelineOrchestrator(gemini_client=self._build_mock_gemini_client())
        with self.assertRaises(PipelineInputError) as ctx:
            orchestrator.run(
                job_id=self.job_id,
                episode_id=self.episode_id,
                transcript_content=self.transcript_json_str,
                connection=MockTxConn(),
            )
        self.assertIn("active, uncommitted transaction", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
