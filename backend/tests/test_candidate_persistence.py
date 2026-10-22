"""
Meri Content Pipeline v1: Unit tests for CandidatePersistenceService and Editorial Boundaries.
Verifies Milestone 3 requirements:
1. Relational persistence of candidate insights and quotations with review_status='candidate'.
2. Multi-segment relational provenance mapping to quotation_segments with deterministic sequence ordering.
3. Preservation of quotations.segment_id starting segment anchor and canonical timestamps.
4. Server-side authorized editorial review boundary (rejection of unauthorized calls).
5. Editorial approval boundary: approval does NOT mutate parent episode publication_status.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
import unittest

from backend.src.candidate_persistence import (
    CandidatePersistenceService,
    EditorialAuthorizationError,
    SegmentReferenceIntegrityError,
    persist_transcript_chunks,
    persist_transcript_segments,
)
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
    ValidationStatus,
)
from backend.src.models import NormalizedSegment, TranscriptChunk


class MockDbCursor:
    """Mock database cursor capturing SQL statements and parameter bindings."""

    def __init__(self) -> None:
        self.executed_queries: List[Tuple[str, Any]] = []
        self._next_id_counter = 100
        self.last_inserted_id: Optional[str] = None
        self.last_returning_row: Optional[Tuple[Any, ...]] = None
        self.commit_count = 0
        self.rollback_count = 0
        self.tables_state: Dict[str, List[Dict[str, Any]]] = {
            "extraction_runs": [],
            "insights": [],
            "insight_evidence": [],
            "quotations": [],
            "quotation_segments": [],
            "transcript_segments": [],
            "transcript_chunks": [],
            "episodes": [{"id": "ep-uuid-101", "publication_status": "draft"}],
        }

    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> None:
        clean_q = " ".join(query.strip().split())
        self.executed_queries.append((clean_q, params))

        if "INSERT INTO transcript_segments" in clean_q:
            self.last_inserted_id = f"seg-uuid-{self._next_id_counter}"
            self._next_id_counter += 1
            seg_idx = params[1] if params and len(params) > 1 else 0
            self.last_returning_row = (seg_idx, self.last_inserted_id)
            if params:
                self.tables_state["transcript_segments"].append({
                    "id": self.last_inserted_id,
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
        elif "INSERT INTO transcript_chunks" in clean_q:
            self.last_inserted_id = f"chunk-uuid-{self._next_id_counter}"
            self._next_id_counter += 1
            if params:
                self.tables_state["transcript_chunks"].append({
                    "id": self.last_inserted_id,
                    "episode_id": params[0],
                    "chunk_index": params[1],
                    "start_segment_index": params[2],
                    "end_segment_index": params[3],
                    "start_ms": params[4],
                    "end_ms": params[5],
                    "token_count_estimate": params[6],
                    "chunk_text": params[7],
                })
        elif "INSERT INTO extraction_runs" in clean_q:
            self.last_inserted_id = f"run-uuid-{self._next_id_counter}"
            self._next_id_counter += 1
        elif "INSERT INTO insights" in clean_q:
            self.last_inserted_id = f"insight-uuid-{self._next_id_counter}"
            self._next_id_counter += 1
            if params:
                self.tables_state["insights"].append({
                    "id": self.last_inserted_id,
                    "episode_id": params[0],
                    "title": params[3],
                    "review_status": params[8] if len(params) > 8 else "candidate",
                })
        elif "INSERT INTO quotations" in clean_q:
            self.last_inserted_id = f"quote-uuid-{self._next_id_counter}"
            self._next_id_counter += 1
            if params:
                self.tables_state["quotations"].append({
                    "id": self.last_inserted_id,
                    "episode_id": params[0],
                    "segment_id": params[2],
                    "timestamp_seconds": params[6],
                    "review_status": params[9] if len(params) > 9 else "candidate",
                })
        elif "INSERT INTO quotation_segments" in clean_q:
            if params:
                self.tables_state["quotation_segments"].append({
                    "quotation_id": params[0],
                    "segment_id": params[1],
                    "sequence_order": params[2],
                })
        elif "INSERT INTO insight_evidence" in clean_q:
            if params:
                self.tables_state["insight_evidence"].append({
                    "insight_id": params[0],
                    "segment_id": params[1],
                    "relevance_score": params[2] if len(params) > 2 else None,
                    "claim_quote_snippet": params[3] if len(params) > 3 else None,
                    "notes": params[4] if len(params) > 4 else None,
                })
        elif "SELECT review_candidate_item" in clean_q:
            # Simulate database review RPC
            item_type, item_id, decision, reviewer_id = params
            target_status = "verified" if decision in ("approved", "verified") else decision
            self.last_rpc_result = {
                "success": True,
                "item_type": item_type,
                "item_id": item_id,
                "review_status": target_status,
                "reviewed_by": reviewer_id,
            }

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if hasattr(self, "last_rpc_result") and self.last_rpc_result is not None:
            res = self.last_rpc_result
            self.last_rpc_result = None
            return (res,)
        if hasattr(self, "last_returning_row") and self.last_returning_row is not None:
            row = self.last_returning_row
            self.last_returning_row = None
            self.last_inserted_id = None
            return row
        if self.last_inserted_id:
            val = self.last_inserted_id
            self.last_inserted_id = None
            return (val,)
        return None



class TestCandidatePersistence(unittest.TestCase):
    """Test suite for CandidatePersistenceService."""

    def setUp(self) -> None:
        self.cursor = MockDbCursor()
        self.episode_id = "ep-uuid-101"
        self.segment_map = {
            0: "seg-uuid-000",
            1: "seg-uuid-001",
            2: "seg-uuid-002",
        }

        # Build candidate extraction payload with multi-segment quote
        self.insight = CandidateInsight(
            title="Supply Chain Decoupling",
            category="Operations",
            summary="Decoupling logistics operations from asset ownership.",
            takeaways=["Asset-light models scale faster"],
            practical_action="Audit subcontracting models",
            evidence_segment_indices=[1],
            confidence_score=0.95,
            display_order=0,
            review_status="candidate",
        )

        self.quote = CandidateQuotation(
            amharic_quote="ትልቁ ፈተና ቴክኖሎጂ ሳይሆን የባንኮች መተሳሰር ነው።",
            english_translation="The biggest test is not technology but banking interconnectivity.",
            speaker="Samuel Alemu",
            source_segment_indices=[1, 2],  # Spanning segments 1 and 2
            canonical_start_ms=8000,
            canonical_timestamp_seconds=8,
            context="Interoperability discussion",
            display_order=0,
            review_status="candidate",
        )

        self.evidence_ref = CandidateEvidenceReference(
            insight_index=0,
            segment_index=1,
            relevance_score=0.95,
            claim_quote_snippet="Snippet from transcript",
        )

        self.quote_segment_0 = CandidateQuotationSegment(
            quotation_index=0,
            segment_index=1,
            sequence_order=0,
        )
        self.quote_segment_1 = CandidateQuotationSegment(
            quotation_index=0,
            segment_index=2,
            sequence_order=1,
        )

        self.payload = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=CandidateSummary(
                brief="Brief",
                comprehensive="Comprehensive",
                primary_themes=["Theme"],
            ),
            guest_profile=CandidateGuestProfile(
                name="Samuel Alemu",
                title="Founder",
                company="Fintech Ethiopia",
                bio="Bio",
                industry="Fintech",
            ),
            journey_milestones=[],
            insights=[self.insight],
            quotations=[self.quote],
            suggested_tags=["Fintech"],
            evidence_references=[self.evidence_ref],
            quotation_segments=[self.quote_segment_0, self.quote_segment_1],
        )

        self.run_record = ExtractionRunRecord(
            model_id="gemini-2.0-flash",
            prompt_version="1.2.0",
            schema_version="1.0.0",
            validation_status=ValidationStatus.PASSED,
            validation_errors=[],
            candidate_payload=self.payload,
            tokens_prompt=500,
            tokens_completion=200,
        )

    def test_persist_candidate_extraction_preserves_candidate_review_status(self) -> None:
        """Verifies candidate insights and quotations are strictly inserted as review_status='candidate'."""
        result = CandidatePersistenceService.persist_candidate_extraction(
            cursor=self.cursor,
            episode_id=self.episode_id,
            extraction_run=self.run_record,
            segment_index_to_id=self.segment_map,
        )

        self.assertEqual(result["insights_inserted"], 1)
        self.assertEqual(result["quotations_inserted"], 1)
        self.assertEqual(result["evidence_inserted"], 1)
        self.assertEqual(result["quotation_segments_inserted"], 2)

        # Assert insights review_status is 'candidate'
        saved_insights = self.cursor.tables_state["insights"]
        self.assertEqual(len(saved_insights), 1)
        self.assertEqual(saved_insights[0]["review_status"], "candidate")

        # Assert quotations review_status is 'candidate'
        saved_quotes = self.cursor.tables_state["quotations"]
        self.assertEqual(len(saved_quotes), 1)
        self.assertEqual(saved_quotes[0]["review_status"], "candidate")

    def test_persist_multi_segment_quotation_provenance_and_anchor(self) -> None:
        """Verifies multi-segment quote stores starting anchor in segment_id and sequence in quotation_segments."""
        CandidatePersistenceService.persist_candidate_extraction(
            cursor=self.cursor,
            episode_id=self.episode_id,
            extraction_run=self.run_record,
            segment_index_to_id=self.segment_map,
        )

        saved_quotes = self.cursor.tables_state["quotations"]
        self.assertEqual(len(saved_quotes), 1)
        # Starting segment anchor is segment 1 -> 'seg-uuid-001'
        self.assertEqual(saved_quotes[0]["segment_id"], "seg-uuid-001")
        # Canonical timestamp is 8 seconds
        self.assertEqual(saved_quotes[0]["timestamp_seconds"], 8)

        # Relational quotation_segments join table
        saved_qs = self.cursor.tables_state["quotation_segments"]
        self.assertEqual(len(saved_qs), 2)
        # Sequence order 0 -> segment 1 ('seg-uuid-001')
        self.assertEqual(saved_qs[0]["sequence_order"], 0)
        self.assertEqual(saved_qs[0]["segment_id"], "seg-uuid-001")
        # Sequence order 1 -> segment 2 ('seg-uuid-002')
        self.assertEqual(saved_qs[1]["sequence_order"], 1)
        self.assertEqual(saved_qs[1]["segment_id"], "seg-uuid-002")

    def test_editorial_review_boundary_unauthorized_rejection(self) -> None:
        """Verifies unauthorized callers are strictly rejected before attempting review."""
        with self.assertRaises(EditorialAuthorizationError):
            CandidatePersistenceService.execute_editorial_review(
                cursor=self.cursor,
                item_type="insight",
                item_id="insight-uuid-101",
                decision="approved",
                is_authorized_actor=False,  # Unprivileged caller
            )

    def test_editorial_review_boundary_authorized_approval(self) -> None:
        """Verifies authorized editor can approve item, mapping 'approved' to 'verified'."""
        result = CandidatePersistenceService.execute_editorial_review(
            cursor=self.cursor,
            item_type="insight",
            item_id="insight-uuid-101",
            decision="approved",
            reviewer_id="editor-uuid-999",
            is_authorized_actor=True,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["review_status"], "verified")
        self.assertEqual(result["reviewed_by"], "editor-uuid-999")

    def test_approval_does_not_mutate_episode_publication_status(self) -> None:
        """Verifies that reviewing or approving candidates never alters episodes.publication_status."""
        CandidatePersistenceService.execute_editorial_review(
            cursor=self.cursor,
            item_type="quotation",
            item_id="quote-uuid-101",
            decision="approved",
            reviewer_id="editor-uuid-999",
            is_authorized_actor=True,
        )

        ep = self.cursor.tables_state["episodes"][0]
        # Episode must remain strictly in 'draft'
        self.assertEqual(ep["publication_status"], "draft")

    def test_unknown_segment_index_in_insight_evidence_raises_descriptive_error(self) -> None:
        """Verifies unknown segment in insight evidence reference raises SegmentReferenceIntegrityError identifying type, candidate index, and missing segment."""
        invalid_evidence = CandidateEvidenceReference(
            insight_index=0,
            segment_index=99,  # Unknown segment (segment_map only has 0, 1, 2)
            relevance_score=0.9,
            claim_quote_snippet="Quote snippet",
        )
        invalid_payload = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=self.payload.episode_summary,
            guest_profile=self.payload.guest_profile,
            journey_milestones=[],
            insights=[self.insight],
            quotations=[],
            suggested_tags=[],
            evidence_references=[invalid_evidence],
            quotation_segments=[],
        )
        invalid_run = ExtractionRunRecord(
            model_id="gemini-2.0-flash",
            prompt_version="1.2.0",
            schema_version="1.0.0",
            validation_status=ValidationStatus.PASSED,
            validation_errors=[],
            candidate_payload=invalid_payload,
        )

        with self.assertRaises(SegmentReferenceIntegrityError) as ctx:
            CandidatePersistenceService.persist_candidate_extraction(
                cursor=self.cursor,
                episode_id=self.episode_id,
                extraction_run=invalid_run,
                segment_index_to_id=self.segment_map,
            )

        err_msg = str(ctx.exception)
        self.assertIn("insight_evidence", err_msg)
        self.assertIn("insight_index 0", err_msg)
        self.assertIn("99", err_msg)

    def test_unknown_segment_index_in_quotation_segment_raises_descriptive_error(self) -> None:
        """Verifies unknown segment in quotation segment reference raises SegmentReferenceIntegrityError identifying type, candidate index, and missing segment."""
        invalid_quote_seg = CandidateQuotationSegment(
            quotation_index=0,
            segment_index=88,  # Unknown segment
            sequence_order=0,
        )
        invalid_quote = CandidateQuotation(
            amharic_quote="ትልቁ ፈተና ቴክኖሎጂ ሳይሆን የባንኮች መተሳሰር ነው።",
            english_translation="The biggest test is not technology but banking interconnectivity.",
            speaker="Samuel Alemu",
            source_segment_indices=[88],
            canonical_start_ms=8000,
            canonical_timestamp_seconds=8,
            context="Interoperability discussion",
            display_order=0,
            review_status="candidate",
        )
        invalid_payload = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=self.payload.episode_summary,
            guest_profile=self.payload.guest_profile,
            journey_milestones=[],
            insights=[],
            quotations=[invalid_quote],
            suggested_tags=[],
            evidence_references=[],
            quotation_segments=[invalid_quote_seg],
        )
        invalid_run = ExtractionRunRecord(
            model_id="gemini-2.0-flash",
            prompt_version="1.2.0",
            schema_version="1.0.0",
            validation_status=ValidationStatus.PASSED,
            validation_errors=[],
            candidate_payload=invalid_payload,
        )

        with self.assertRaises(SegmentReferenceIntegrityError) as ctx:
            CandidatePersistenceService.persist_candidate_extraction(
                cursor=self.cursor,
                episode_id=self.episode_id,
                extraction_run=invalid_run,
                segment_index_to_id=self.segment_map,
            )

        err_msg = str(ctx.exception)
        self.assertIn("quotation_segment", err_msg)
        self.assertIn("quotation_index 0", err_msg)
        self.assertIn("88", err_msg)

    def test_validation_occurs_before_candidate_rows_are_inserted(self) -> None:
        """Verifies that when evidence validation fails, no candidate rows (insights, quotations, evidence) are inserted."""
        invalid_evidence = CandidateEvidenceReference(
            insight_index=0,
            segment_index=999,  # Unknown segment
        )
        payload_with_multiple_items = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=self.payload.episode_summary,
            guest_profile=self.payload.guest_profile,
            journey_milestones=[],
            insights=[self.insight],
            quotations=[self.quote],
            suggested_tags=[],
            evidence_references=[invalid_evidence],
            quotation_segments=[self.quote_segment_0, self.quote_segment_1],
        )
        run_record = ExtractionRunRecord(
            model_id="gemini-2.0-flash",
            prompt_version="1.2.0",
            schema_version="1.0.0",
            validation_status=ValidationStatus.PASSED,
            validation_errors=[],
            candidate_payload=payload_with_multiple_items,
        )

        with self.assertRaises(SegmentReferenceIntegrityError):
            CandidatePersistenceService.persist_candidate_extraction(
                cursor=self.cursor,
                episode_id=self.episode_id,
                extraction_run=run_record,
                segment_index_to_id=self.segment_map,
            )

        # Assert no candidate tables were populated
        self.assertEqual(len(self.cursor.tables_state["insights"]), 0)
        self.assertEqual(len(self.cursor.tables_state["quotations"]), 0)
        self.assertEqual(len(self.cursor.tables_state["insight_evidence"]), 0)
        self.assertEqual(len(self.cursor.tables_state["quotation_segments"]), 0)

        # Assert no candidate INSERT queries were executed
        candidate_queries = [
            q for q, _ in self.cursor.executed_queries
            if any(tbl in q for tbl in ("insights", "quotations", "insight_evidence", "quotation_segments"))
        ]
        self.assertEqual(candidate_queries, [])

    def test_evidence_notes_persisted_in_insert_sql(self) -> None:
        """Verifies that CandidateEvidenceReference.notes is included in the INSERT parameters and table state."""
        evidence_with_notes = CandidateEvidenceReference(
            insight_index=0,
            segment_index=1,
            relevance_score=0.88,
            claim_quote_snippet="Verbatim snippet",
            notes="Derived from multi-chunk candidate merge",
        )
        payload = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=self.payload.episode_summary,
            guest_profile=self.payload.guest_profile,
            journey_milestones=[],
            insights=[self.insight],
            quotations=[],
            suggested_tags=[],
            evidence_references=[evidence_with_notes],
            quotation_segments=[],
        )
        run_record = ExtractionRunRecord(
            model_id="gemini-2.0-flash",
            prompt_version="1.2.0",
            schema_version="1.0.0",
            validation_status=ValidationStatus.PASSED,
            validation_errors=[],
            candidate_payload=payload,
        )

        result = CandidatePersistenceService.persist_candidate_extraction(
            cursor=self.cursor,
            episode_id=self.episode_id,
            extraction_run=run_record,
            segment_index_to_id=self.segment_map,
        )
        self.assertEqual(result["evidence_inserted"], 1)

        # Inspect executed query and params
        evidence_inserts = [
            (q, params) for q, params in self.cursor.executed_queries
            if "INSERT INTO insight_evidence" in q
        ]
        self.assertEqual(len(evidence_inserts), 1)
        query_sql, params = evidence_inserts[0]

        # Verify SQL column list includes notes
        self.assertIn("notes", query_sql)
        self.assertIn("relevance_score, claim_quote_snippet, notes", query_sql)

        # Verify parameter values
        self.assertEqual(len(params), 5)
        self.assertEqual(params[2], 0.88)
        self.assertEqual(params[3], "Verbatim snippet")
        self.assertEqual(params[4], "Derived from multi-chunk candidate merge")

        # Verify state in mock table
        stored_evidence = self.cursor.tables_state["insight_evidence"]
        self.assertEqual(len(stored_evidence), 1)
        self.assertEqual(stored_evidence[0]["notes"], "Derived from multi-chunk candidate merge")

    def test_evidence_notes_none_persisted_safely(self) -> None:
        """Verifies that CandidateEvidenceReference with notes=None correctly passes None as 5th parameter."""
        evidence_no_notes = CandidateEvidenceReference(
            insight_index=0,
            segment_index=1,
            relevance_score=0.92,
            claim_quote_snippet="Snippet without notes",
            notes=None,
        )
        payload = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=self.payload.episode_summary,
            guest_profile=self.payload.guest_profile,
            journey_milestones=[],
            insights=[self.insight],
            quotations=[],
            suggested_tags=[],
            evidence_references=[evidence_no_notes],
            quotation_segments=[],
        )
        run_record = ExtractionRunRecord(
            model_id="gemini-2.0-flash",
            prompt_version="1.2.0",
            schema_version="1.0.0",
            validation_status=ValidationStatus.PASSED,
            validation_errors=[],
            candidate_payload=payload,
        )

        CandidatePersistenceService.persist_candidate_extraction(
            cursor=self.cursor,
            episode_id=self.episode_id,
            extraction_run=run_record,
            segment_index_to_id=self.segment_map,
        )

        evidence_inserts = [
            (q, params) for q, params in self.cursor.executed_queries
            if "INSERT INTO insight_evidence" in q
        ]
        _, params = evidence_inserts[0]
        self.assertIsNone(params[4])

    def test_persistence_helpers_do_not_commit_or_rollback(self) -> None:
        """Verifies candidate, segment, and chunk persistence helpers never call commit or rollback, preserving caller ownership."""
        # 1. persist_candidate_extraction
        self.cursor.commit_count = 0
        self.cursor.rollback_count = 0
        CandidatePersistenceService.persist_candidate_extraction(
            cursor=self.cursor,
            episode_id=self.episode_id,
            extraction_run=self.run_record,
            segment_index_to_id=self.segment_map,
        )
        self.assertEqual(self.cursor.commit_count, 0)
        self.assertEqual(self.cursor.rollback_count, 0)

        # 2. persist_transcript_segments
        persist_transcript_segments(
            self.cursor,
            self.episode_id,
            [
                NormalizedSegment(
                    segment_index=0,
                    start_ms=0,
                    end_ms=1000,
                    start_seconds=0.0,
                    speaker_label="Host",
                    language_code="am",
                    acquisition_method="manual_upload",
                    text="ሰላም።",
                )
            ],
        )
        self.assertEqual(self.cursor.commit_count, 0)
        self.assertEqual(self.cursor.rollback_count, 0)

        # 3. persist_transcript_chunks
        persist_transcript_chunks(
            self.cursor,
            self.episode_id,
            [
                TranscriptChunk(
                    chunk_index=0,
                    start_segment_index=0,
                    end_segment_index=0,
                    start_ms=0,
                    end_ms=1000,
                    token_count_estimate=5,
                    chunk_text="[Seg 0]: ሰላም።",
                )
            ],
        )
        self.assertEqual(self.cursor.commit_count, 0)
        self.assertEqual(self.cursor.rollback_count, 0)

        # 4. Confirm no COMMIT or ROLLBACK SQL was executed across any of the calls
        for q, _ in self.cursor.executed_queries:
            self.assertNotIn("COMMIT", q.upper())
            self.assertNotIn("ROLLBACK", q.upper())


class TestTranscriptSegmentAndChunkPersistence(unittest.TestCase):
    """
    Milestone 4 Step 1: Unit tests for transcript segment and chunk persistence helpers.
    Verifies cursor-based persistence, deterministic mapping, generated column safety,
    boundary validation, and error propagation.
    """

    def setUp(self) -> None:
        self.cursor = MockDbCursor()
        self.episode_id = "ep-uuid-101"

        self.sample_segments = [
            NormalizedSegment(
                segment_index=0,
                start_ms=0,
                end_ms=4500,
                start_seconds=0.0,
                speaker_label="Host A",
                language_code="am",
                acquisition_method="manual_upload",
                text="እንኳን ወደ ሜሪ ፖድካስት በደህና መጡ።",
                confidence=0.98,
            ),
            NormalizedSegment(
                segment_index=1,
                start_ms=4500,
                end_ms=12000,
                start_seconds=4.5,
                speaker_label="Dawit Tadesse",
                language_code="am",
                acquisition_method="manual_upload",
                text="የሎጂስቲክስ ስራ ትልቁ ፈተና የቀዝቃዛ ሰንሰለት መሠረተ ልማት እጥረት ነው።",
                confidence=0.95,
            ),
            NormalizedSegment(
                segment_index=2,
                start_ms=12000,
                end_ms=18500,
                start_seconds=12.0,
                speaker_label="Dawit Tadesse",
                language_code="am",
                acquisition_method="manual_upload",
                text="ይህን ችግር ለመፍታት የሶስተኛ ወገን መጋዘኖችን ተጠቅመናል።",
                confidence=None,
            ),
        ]

        self.sample_chunks = [
            TranscriptChunk(
                chunk_index=0,
                start_segment_index=0,
                end_segment_index=1,
                start_ms=0,
                end_ms=12000,
                token_count_estimate=25,
                chunk_text="[Seg 0 | Host A | 0.0s]: ...\n[Seg 1 | Dawit Tadesse | 4.5s]: ...",
            ),
            TranscriptChunk(
                chunk_index=1,
                start_segment_index=1,
                end_segment_index=2,
                start_ms=4500,
                end_ms=18500,
                token_count_estimate=28,
                chunk_text="[Seg 1 | Dawit Tadesse | 4.5s]: ...\n[Seg 2 | Dawit Tadesse | 12.0s]: ...",
            ),
        ]

    # --- Segment Persistence Tests ---

    def test_persist_transcript_segments_happy_path(self) -> None:
        """Verifies successful persistence of segments returning deterministic index -> UUID mapping."""
        mapping = persist_transcript_segments(self.cursor, self.episode_id, self.sample_segments)

        self.assertEqual(len(mapping), 3)
        self.assertEqual(mapping[0], "seg-uuid-100")
        self.assertEqual(mapping[1], "seg-uuid-101")
        self.assertEqual(mapping[2], "seg-uuid-102")

        # Verify state in mock table
        stored_segs = self.cursor.tables_state["transcript_segments"]
        self.assertEqual(len(stored_segs), 3)
        self.assertEqual(stored_segs[0]["segment_index"], 0)
        self.assertEqual(stored_segs[0]["speaker_label"], "Host A")
        self.assertEqual(stored_segs[0]["start_ms"], 0)
        self.assertEqual(stored_segs[0]["end_ms"], 4500)
        self.assertEqual(stored_segs[0]["text"], "እንኳን ወደ ሜሪ ፖድካስት በደህና መጡ።")
        self.assertEqual(stored_segs[0]["confidence"], 0.98)

        # Verify generated column 'start_seconds' is NOT included in INSERT query
        for q, _ in self.cursor.executed_queries:
            if "INSERT INTO transcript_segments" in q:
                self.assertNotIn("start_seconds", q)
                self.assertIn("RETURNING segment_index, id", q)

    def test_persist_transcript_segments_empty_input(self) -> None:
        """Empty segments collection returns empty mapping without executing queries."""
        mapping = persist_transcript_segments(self.cursor, self.episode_id, [])
        self.assertEqual(mapping, {})
        self.assertEqual(len(self.cursor.executed_queries), 0)

    def test_persist_transcript_segments_duplicate_segment_index_rejection(self) -> None:
        """Duplicate segment_index within input list raises ValueError."""
        duplicate_segs = [
            self.sample_segments[0],
            NormalizedSegment(
                segment_index=0,  # Duplicate
                start_ms=5000,
                end_ms=9000,
                start_seconds=5.0,
                speaker_label="Host A",
                language_code="am",
                acquisition_method="manual_upload",
                text="ተደጋጋሚ ኢንዴክስ።",
            ),
        ]
        with self.assertRaises(ValueError) as ctx:
            persist_transcript_segments(self.cursor, self.episode_id, duplicate_segs)
        self.assertIn("Duplicate segment_index 0", str(ctx.exception))

    def test_persist_transcript_segments_invalid_segment_index(self) -> None:
        """Negative segment_index is rejected with ValueError."""
        # Create a mock or duck-typed segment with negative index
        class BadSegment:
            segment_index = -1
            start_ms = 0
            end_ms = 1000
            speaker_label = "Speaker"
            language_code = "am"
            acquisition_method = "manual_upload"
            text = "invalid"
            confidence = None

        with self.assertRaises(ValueError) as ctx:
            persist_transcript_segments(self.cursor, self.episode_id, [BadSegment()])  # type: ignore
        self.assertIn("segment_index must be >= 0", str(ctx.exception))

    def test_persist_transcript_segments_missing_episode_id(self) -> None:
        """Missing episode_id raises ValueError."""
        with self.assertRaises(ValueError):
            persist_transcript_segments(self.cursor, "", self.sample_segments)

    def test_persist_transcript_segments_database_error_propagates(self) -> None:
        """Database execution errors propagate directly and do not return a partial mapping."""
        class FailingCursor:
            def execute(self, query: str, params: Any = None) -> None:
                raise RuntimeError("PostgreSQL connection severed")
            def fetchone(self) -> Any:
                return None

        with self.assertRaises(RuntimeError) as ctx:
            persist_transcript_segments(FailingCursor(), self.episode_id, self.sample_segments)
        self.assertIn("PostgreSQL connection severed", str(ctx.exception))

    def test_persist_transcript_segments_database_no_id_returned(self) -> None:
        """If database returns an empty row or missing ID on RETURNING, raises RuntimeError."""
        class EmptyRowCursor:
            def execute(self, query: str, params: Any = None) -> None:
                pass
            def fetchone(self) -> Any:
                return None

        with self.assertRaises(RuntimeError) as ctx:
            persist_transcript_segments(EmptyRowCursor(), self.episode_id, self.sample_segments)
        self.assertIn("database returned no ID", str(ctx.exception))

        class NoneIdCursor:
            def execute(self, query: str, params: Any = None) -> None:
                pass
            def fetchone(self) -> Any:
                return (0, None)

        with self.assertRaises(RuntimeError) as ctx:
            persist_transcript_segments(NoneIdCursor(), self.episode_id, self.sample_segments)
        self.assertIn("database returned no ID", str(ctx.exception))

    def test_persist_transcript_segments_non_sequential_indices(self) -> None:
        """
        Change 2 Requirement: Verifies that segments with non-sequential, non-zero indices [14, 25, 42]
        are mapped directly to their corresponding UUIDs and do not use enumeration offsets (0, 1, 2).
        """
        non_seq_segments = [
            NormalizedSegment(
                segment_index=14,
                start_ms=125400,
                end_ms=130000,
                start_seconds=125.4,
                speaker_label="Host A",
                language_code="am",
                acquisition_method="manual_upload",
                text="ክፍል አስራ አራት ነው።",
            ),
            NormalizedSegment(
                segment_index=25,
                start_ms=250000,
                end_ms=255000,
                start_seconds=250.0,
                speaker_label="Guest B",
                language_code="am",
                acquisition_method="manual_upload",
                text="ክፍል ሃያ አምስት ነው።",
            ),
            NormalizedSegment(
                segment_index=42,
                start_ms=420000,
                end_ms=428000,
                start_seconds=420.0,
                speaker_label="Host A",
                language_code="am",
                acquisition_method="manual_upload",
                text="ክፍል አርባ ሁለት ነው።",
            ),
        ]

        mapping = persist_transcript_segments(self.cursor, self.episode_id, non_seq_segments)

        # 1. Exactly the three non-sequential keys must be present
        self.assertEqual(set(mapping.keys()), {14, 25, 42})
        self.assertEqual(len(mapping), 3)

        # 2. Must not use loop enumeration offsets 0, 1, 2
        for offset in (0, 1, 2):
            self.assertNotIn(offset, mapping)

        # 3. Each key must map to the UUID generated for that specific insert
        self.assertEqual(mapping[14], "seg-uuid-100")
        self.assertEqual(mapping[25], "seg-uuid-101")
        self.assertEqual(mapping[42], "seg-uuid-102")

        # 4. Verify SQL query uses RETURNING segment_index, id
        for q, _ in self.cursor.executed_queries:
            if "INSERT INTO transcript_segments" in q:
                self.assertIn("RETURNING segment_index, id", q)

    def test_persist_transcript_segments_mismatched_returned_segment_index(self) -> None:
        """
        Verifies that if the database returns a segment_index inconsistent with the
        requested segment, a descriptive RuntimeError is raised.
        """
        class MismatchedCursor:
            def execute(self, query: str, params: Any = None) -> None:
                pass
            def fetchone(self) -> Any:
                # Return wrong segment_index 999 instead of expected 0
                return (999, "seg-uuid-fake")

        with self.assertRaises(RuntimeError) as ctx:
            persist_transcript_segments(MismatchedCursor(), self.episode_id, self.sample_segments)
        self.assertIn("mismatch", str(ctx.exception).lower())
        self.assertIn("999", str(ctx.exception))


    # --- Chunk Persistence Tests ---

    def test_persist_transcript_chunks_happy_path(self) -> None:
        """Verifies chunks persistence preserves order, segment boundaries, and word count estimates."""
        valid_segments = {0, 1, 2}
        count = persist_transcript_chunks(
            self.cursor,
            self.episode_id,
            self.sample_chunks,
            valid_segment_indices=valid_segments,
        )

        self.assertEqual(count, 2)
        stored_chunks = self.cursor.tables_state["transcript_chunks"]
        self.assertEqual(len(stored_chunks), 2)
        self.assertEqual(stored_chunks[0]["chunk_index"], 0)
        self.assertEqual(stored_chunks[0]["start_segment_index"], 0)
        self.assertEqual(stored_chunks[0]["end_segment_index"], 1)
        self.assertEqual(stored_chunks[0]["start_ms"], 0)
        self.assertEqual(stored_chunks[0]["end_ms"], 12000)
        self.assertEqual(stored_chunks[0]["token_count_estimate"], 25)

        self.assertEqual(stored_chunks[1]["chunk_index"], 1)
        self.assertEqual(stored_chunks[1]["start_segment_index"], 1)
        self.assertEqual(stored_chunks[1]["end_segment_index"], 2)

    def test_persist_transcript_chunks_empty_input(self) -> None:
        """Empty chunks input returns 0 without executing SQL."""
        count = persist_transcript_chunks(self.cursor, self.episode_id, [])
        self.assertEqual(count, 0)
        self.assertEqual(len(self.cursor.executed_queries), 0)

    def test_persist_transcript_chunks_duplicate_chunk_index(self) -> None:
        """Duplicate chunk_index in input raises ValueError."""
        duplicate_chunks = [
            self.sample_chunks[0],
            TranscriptChunk(
                chunk_index=0,  # Duplicate
                start_segment_index=2,
                end_segment_index=2,
                start_ms=12000,
                end_ms=18500,
                token_count_estimate=10,
                chunk_text="...",
            ),
        ]
        with self.assertRaises(ValueError) as ctx:
            persist_transcript_chunks(self.cursor, self.episode_id, duplicate_chunks)
        self.assertIn("Duplicate chunk_index 0", str(ctx.exception))

    def test_persist_transcript_chunks_invalid_boundaries(self) -> None:
        """Invalid boundaries where end_segment_index < start_segment_index are rejected."""
        class InvertedChunk:
            chunk_index = 0
            start_segment_index = 5
            end_segment_index = 2
            start_ms = 5000
            end_ms = 8000
            token_count_estimate = 10
            chunk_text = "..."

        with self.assertRaises(ValueError) as ctx:
            persist_transcript_chunks(self.cursor, self.episode_id, [InvertedChunk()])  # type: ignore
        self.assertIn("cannot be less than", str(ctx.exception))

    def test_persist_transcript_chunks_out_of_bounds_against_valid_segments(self) -> None:
        """Chunk referencing non-existent source segment index is rejected."""
        valid_segments = {0, 1}  # Segment 2 is missing
        with self.assertRaises(ValueError) as ctx:
            persist_transcript_chunks(
                self.cursor,
                self.episode_id,
                self.sample_chunks,
                valid_segment_indices=valid_segments,
            )
        self.assertIn("does not exist in valid source segments", str(ctx.exception))

    def test_persist_transcript_chunks_missing_episode_id(self) -> None:
        """Missing episode_id raises ValueError."""
        with self.assertRaises(ValueError):
            persist_transcript_chunks(self.cursor, "", self.sample_chunks)

    def test_persist_transcript_chunks_database_error_propagates(self) -> None:
        """Database error propagates directly without returning a success count."""
        class FailingCursor:
            def execute(self, query: str, params: Any = None) -> None:
                raise RuntimeError("PostgreSQL lock timeout")
            def fetchone(self) -> Any:
                return None

        with self.assertRaises(RuntimeError) as ctx:
            persist_transcript_chunks(FailingCursor(), self.episode_id, self.sample_chunks)
        self.assertIn("PostgreSQL lock timeout", str(ctx.exception))

    def test_persist_transcript_chunks_database_no_id_returned(self) -> None:
        """If database returns no ID on RETURNING id, raises RuntimeError."""
        class EmptyRowCursor:
            def execute(self, query: str, params: Any = None) -> None:
                pass
            def fetchone(self) -> Any:
                return None

        with self.assertRaises(RuntimeError) as ctx:
            persist_transcript_chunks(EmptyRowCursor(), self.episode_id, self.sample_chunks)
        self.assertIn("database returned no ID", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
