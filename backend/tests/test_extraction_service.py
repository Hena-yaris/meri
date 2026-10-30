"""
Meri Content Pipeline v1: Unit tests for Extraction Orchestration Service.
Tests end-to-end extraction from transcript chunks with mock Gemini client,
syntactic and semantic dual-layer validation, metadata segregation, and database-ready packaging.
"""

import json
from pathlib import Path
import unittest
import urllib.request

from backend.src.extraction_models import (
    CandidateEvidenceReference,
    CandidateInsight,
    CandidateQuotation,
    ExtractionRunRecord,
    ValidationErrorCode,
    ValidationStatus,
)
from backend.src.extraction_service import ExtractionService
from backend.src.gemini_client import GeminiClient, GeminiConfig
from backend.src.models import NormalizedSegment, TranscriptAcquisitionMethod, TranscriptChunk

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "schemas" / "fixtures"


class TestExtractionService(unittest.TestCase):
    """Test suite for integrated ExtractionService."""

    def setUp(self) -> None:
        self.segments = [
            NormalizedSegment(
                segment_index=0,
                start_ms=0,
                end_ms=5000,
                start_seconds=0.0,
                speaker_label="Host",
                language_code="am",
                acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
                text="ሰላም እንኳን ደህና መጣችሁ ወደ መሪ ፖድካስት።",
            ),
            NormalizedSegment(
                segment_index=1,
                start_ms=5500,
                end_ms=12000,
                start_seconds=5.5,
                speaker_label="Dawit Tadesse",
                language_code="am",
                acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
                text="የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
            ),
        ]

        self.chunk = TranscriptChunk(
            chunk_index=0,
            start_segment_index=0,
            end_segment_index=1,
            start_ms=0,
            end_ms=12000,
            token_count_estimate=22,
            chunk_text="[00:00:00 - 00:00:12] Dawit Tadesse: የሎጂስቲክስ ስራ ትልቁ ፈተና...",
        )

        with open(FIXTURES_DIR / "sample_candidate_gemini_response.json", "r", encoding="utf-8") as f:
            self.sample_gemini_response = json.load(f)

    def test_end_to_end_extraction_success_packaging(self) -> None:
        """Verifies full flow: mock Gemini response -> Layer 1 -> Layer 2 -> ExtractionRunRecord."""
        # Align candidate payload with self.segments
        response_data = json.loads(json.dumps(self.sample_gemini_response))
        for m in response_data.get("journey_milestones", []):
            m["evidence_segment_indices"] = [1]
        response_data["insights"][0]["evidence_segment_indices"] = [1]
        response_data["insights"][1]["evidence_segment_indices"] = [1]
        response_data["quotations"][0]["source_segment_indices"] = [1]
        response_data["quotations"][0]["timestamp_seconds"] = 5
        response_data["quotations"] = [response_data["quotations"][0]]  # Keep 1 quote matching segment 1

        api_response_body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": json.dumps(response_data)}]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 850,
                    "candidatesTokenCount": 420,
                },
            }
        )

        def mock_transport(req: urllib.request.Request, timeout: float):
            return 200, {}, api_response_body

        client = GeminiClient(
            config=GeminiConfig(model_id="gemini-2.0-flash", api_key="test-key"),
            transport=mock_transport,
        )

        service = ExtractionService(
            gemini_client=client,
            prompt_version="1.2.0",
            schema_version="1.0.0",
        )

        record = service.extract_and_validate(
            segments=self.segments,
            chunks=[self.chunk],
            job_id="job-uuid-1234",
            episode_id="ep-uuid-5678",
            run_number=1,
        )

        self.assertIsInstance(record, ExtractionRunRecord)
        self.assertEqual(record.validation_status, ValidationStatus.PASSED)
        self.assertEqual(record.model_id, "gemini-2.0-flash")
        self.assertEqual(record.prompt_version, "1.2.0")
        self.assertEqual(record.schema_version, "1.0.0")
        self.assertNotEqual(record.prompt_version, record.schema_version)  # Must remain distinct!
        self.assertEqual(record.tokens_prompt, 850)
        self.assertEqual(record.tokens_completion, 420)
        self.assertEqual(record.job_id, "job-uuid-1234")
        self.assertEqual(record.episode_id, "ep-uuid-5678")

        # Candidate summary preserves both brief and comprehensive
        self.assertIsNotNone(record.candidate_payload)
        summary = record.candidate_payload.episode_summary
        self.assertTrue(len(summary.brief) > 0)
        self.assertTrue(len(summary.comprehensive) > 0)
        self.assertNotEqual(summary.brief, summary.comprehensive)

        # Database mapping test for extraction_runs
        db_dict = record.to_db_dict()
        self.assertEqual(db_dict["model_id"], "gemini-2.0-flash")
        self.assertEqual(db_dict["prompt_version"], "1.2.0")
        self.assertEqual(db_dict["validation_status"], "passed")
        self.assertEqual(db_dict["tokens_prompt"], 850)
        self.assertEqual(db_dict["tokens_completion"], 420)
        self.assertEqual(db_dict["job_id"], "job-uuid-1234")
        self.assertEqual(db_dict["episode_id"], "ep-uuid-5678")

    def test_malformed_json_response_fails_gracefully(self) -> None:
        """Verifies malformed JSON produces a FAILED ExtractionRunRecord with actionable error."""
        api_response_body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "BROKEN_JSON_NOT_VALID{"}]
                        }
                    }
                ]
            }
        )

        def mock_transport(req: urllib.request.Request, timeout: float):
            return 200, {}, api_response_body

        client = GeminiClient(
            config=GeminiConfig(api_key="test-key"),
            transport=mock_transport,
        )
        service = ExtractionService(gemini_client=client)

        record = service.extract_and_validate(segments=self.segments, chunks=[self.chunk])
        self.assertEqual(record.validation_status, ValidationStatus.FAILED)
        self.assertIsNone(record.candidate_payload)
        self.assertTrue(any(e.error_code == ValidationErrorCode.MALFORMED_JSON for e in record.validation_errors))

    def test_staged_models_persistence_dictionaries(self) -> None:
        """Verifies in-memory candidate models generate valid dictionaries matching Supabase tables."""
        insight = CandidateInsight(
            title="Decoupling Logistics",
            category="Operations",
            summary="This is a summary of operational mechanics.",
            takeaways=["Takeaway 1", "Takeaway 2"],
            practical_action="Audit fleet maintenance costs.",
            evidence_segment_indices=[1],
            confidence_score=0.95,
            display_order=0,
            review_status="candidate",
        )
        insight_dict = insight.to_db_dict(episode_id="ep-1", extraction_run_id="run-1")
        self.assertEqual(insight_dict["category"], "Operations")
        self.assertEqual(insight_dict["review_status"], "candidate")
        self.assertEqual(insight_dict["episode_id"], "ep-1")
        self.assertEqual(insight_dict["extraction_run_id"], "run-1")

        quote = CandidateQuotation(
            amharic_quote="የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
            english_translation="The real test in logistics is calculating perishable cargo by the second.",
            speaker="Dawit Tadesse",
            source_segment_indices=[1],
            canonical_start_ms=5500,
            canonical_timestamp_seconds=5,
            context="Discussing freight metrics.",
            display_order=0,
            review_status="candidate",
        )
        quote_dict = quote.to_db_dict(episode_id="ep-1", extraction_run_id="run-1", segment_id="seg-1")
        self.assertEqual(quote_dict["timestamp_seconds"], 5)
        self.assertEqual(quote_dict["review_status"], "candidate")
        self.assertEqual(quote_dict["segment_id"], "seg-1")

        ev_ref = CandidateEvidenceReference(
            insight_index=0,
            segment_index=1,
            relevance_score=0.95,
        )
        ev_dict = ev_ref.to_db_dict(insight_id="ins-1", segment_id="seg-1")
        self.assertEqual(ev_dict["insight_id"], "ins-1")
        self.assertEqual(ev_dict["segment_id"], "seg-1")
        self.assertEqual(ev_dict["relevance_score"], 0.95)

    def test_cross_segment_quotation_provenance_preservation_and_db_mapping(self) -> None:
        """
        Tests in-memory representation of cross-segment quotations and documents
        the persistence decision required for Milestone 3 under current Supabase migration.

        ARCHITECTURAL CONTEXT:
        - Current schema (20261020000001_content_pipeline_foundation.sql) defines:
            quotations.segment_id UUID REFERENCES transcript_segments(id) ON DELETE SET NULL
        - A cross-segment quotation spans multiple contiguous segments (e.g. indices [3, 4]).
        - In-memory representation: CandidateQuotation preserves the complete provenance
          in `source_segment_indices = [3, 4]`.
        - Current DB serialization: maps `segment_id` to the starting segment anchor (index 3),
          while full provenance is retained in memory and extraction_runs.raw_response_json.
        - Future approval options for Milestone 3:
            1. Dedicated quotation_segments join table (analogous to insight_evidence).
            2. An array column `segment_ids UUID[]` on quotations.
            3. Segment provenance array stored in audit metadata JSON.
        """
        cross_quote = CandidateQuotation(
            amharic_quote="የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
            english_translation="The real test in logistics is calculating perishable cargo by the second.",
            speaker="Dawit Tadesse",
            source_segment_indices=[3, 4],  # Spans segments 3 and 4
            canonical_start_ms=16000,
            canonical_timestamp_seconds=16,
            context="Explaining why telemetry monitoring matters more than fleet volume.",
            display_order=1,
            review_status="candidate",
        )

        # 1. In-memory representation preserves complete multi-segment provenance
        self.assertEqual(cross_quote.source_segment_indices, [3, 4])
        self.assertEqual(len(cross_quote.source_segment_indices), 2)
        self.assertEqual(cross_quote.canonical_timestamp_seconds, 16)
        self.assertEqual(cross_quote.review_status, "candidate")

        # 2. Database mapping targets primary starting anchor under current schema
        primary_anchor_segment_id = "00000000-0000-0000-0000-000000000003"
        db_payload = cross_quote.to_db_dict(
            episode_id="00000000-0000-0000-0000-000000000001",
            extraction_run_id="00000000-0000-0000-0000-000000000002",
            segment_id=primary_anchor_segment_id,
        )

        self.assertEqual(db_payload["segment_id"], primary_anchor_segment_id)
        self.assertEqual(db_payload["timestamp_seconds"], 16)
        self.assertEqual(db_payload["review_status"], "candidate")
        self.assertNotIn("source_segment_indices", db_payload, "Current DB table does not have source_segment_indices column")


if __name__ == "__main__":
    unittest.main()
