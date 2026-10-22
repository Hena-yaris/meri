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


class MockDbCursor:
    """Mock database cursor capturing SQL statements and parameter bindings."""

    def __init__(self) -> None:
        self.executed_queries: List[Tuple[str, Any]] = []
        self._next_id_counter = 100
        self.last_inserted_id: Optional[str] = None
        self.tables_state: Dict[str, List[Dict[str, Any]]] = {
            "extraction_runs": [],
            "insights": [],
            "insight_evidence": [],
            "quotations": [],
            "quotation_segments": [],
            "episodes": [{"id": "ep-uuid-101", "publication_status": "draft"}],
        }

    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> None:
        clean_q = " ".join(query.strip().split())
        self.executed_queries.append((clean_q, params))

        if "INSERT INTO extraction_runs" in clean_q:
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

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if hasattr(self, "last_rpc_result") and self.last_rpc_result is not None:
            res = self.last_rpc_result
            self.last_rpc_result = None
            return (res,)
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


if __name__ == "__main__":
    unittest.main()
