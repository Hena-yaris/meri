"""
Meri Content Pipeline v1: Unit Tests for DeterministicFakeExtractor.

Verifies Phase C and Phase F requirements:
1. Fake extractor operates completely offline without network requests or API keys.
2. Returns deterministic, schema-valid results grounded in synthetic transcript segments.
3. Produces accurate evidence references and quotation timestamps.
4. Correctly exercises simulated failure modes for network errors, invalid JSON, and semantic errors.
"""

import json
from pathlib import Path
import unittest

from backend.src.extraction_models import ValidationStatus
from backend.src.gemini_client import GeminiTimeoutError
from backend.src.models import NormalizedSegment, TranscriptChunk
from backend.tests.fake_extraction_provider import (
    SYNTHETIC_MODEL_ID,
    SYNTHETIC_PROMPT_VERSION,
    SYNTHETIC_SCHEMA_VERSION,
    DeterministicFakeExtractor,
    create_deterministic_synthetic_payload,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_transcript.json"


class TestFakeExtractionProvider(unittest.TestCase):
    """Unit tests verifying the test-only DeterministicFakeExtractor."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)

        from backend.src.chunker import TranscriptChunker
        from backend.src.transcript_normalizer import TranscriptNormalizer
        from backend.src.transcript_parser import parse_transcript

        cues = parse_transcript(raw, format_hint="json")
        cls.segments = TranscriptNormalizer().normalize(cues)
        cls.chunks = TranscriptChunker().chunk(cls.segments)

    def test_deterministic_payload_structure(self) -> None:
        """Verifies that the synthetic payload has valid schema and explicit test values."""
        payload = create_deterministic_synthetic_payload()
        self.assertEqual(payload["schema_version"], "1.0.0")
        self.assertEqual(len(payload["insights"]), 2)
        self.assertEqual(len(payload["quotations"]), 2)
        self.assertEqual(payload["insights"][0]["category"], "Operations")
        self.assertEqual(payload["insights"][1]["category"], "Finance & Capital")
        self.assertEqual(payload["quotations"][0]["timestamp_seconds"], 14)
        self.assertEqual(payload["quotations"][1]["timestamp_seconds"], 58)

    def test_fake_extractor_success_mode(self) -> None:
        """Verifies end-to-end extraction and validation with PASSED status."""
        extractor = DeterministicFakeExtractor()
        run_record = extractor.extract_and_validate(
            segments=self.segments,
            chunks=self.chunks,
            job_id="test-job-001",
            episode_id="test-ep-001",
            run_number=1,
        )

        self.assertEqual(extractor.call_count, 1)
        self.assertEqual(run_record.validation_status, ValidationStatus.PASSED)
        self.assertEqual(run_record.model_id, SYNTHETIC_MODEL_ID)
        self.assertEqual(run_record.prompt_version, SYNTHETIC_PROMPT_VERSION)
        self.assertEqual(run_record.schema_version, SYNTHETIC_SCHEMA_VERSION)
        self.assertEqual(run_record.tokens_prompt, 500)
        self.assertEqual(run_record.tokens_completion, 250)

        payload = run_record.candidate_payload
        self.assertIsNotNone(payload)
        self.assertEqual(len(payload.insights), 2)
        self.assertEqual(len(payload.quotations), 2)

        # Quotation 0: anchored in segment 1 with timestamp 14
        self.assertEqual(payload.quotations[0].source_segment_indices, [1])
        self.assertEqual(payload.quotations[0].canonical_timestamp_seconds, 14)

        # Quotation 1: anchored in segment 3 with timestamp 58
        self.assertEqual(payload.quotations[1].source_segment_indices, [3])
        self.assertEqual(payload.quotations[1].canonical_timestamp_seconds, 58)

    def test_fake_extractor_network_error_mode(self) -> None:
        """Verifies simulated network timeout raises GeminiRetryExhaustedError / GeminiTimeoutError."""
        from backend.src.gemini_client import GeminiClientError
        extractor = DeterministicFakeExtractor(failure_mode="network_error")
        client = extractor.create_gemini_client()

        with self.assertRaises(GeminiClientError):
            client.generate_candidate_json(self.chunks)

        self.assertEqual(extractor.call_count, 3)

    def test_fake_extractor_invalid_json_mode(self) -> None:
        """Verifies simulated malformed JSON returns FAILED validation status."""
        extractor = DeterministicFakeExtractor(failure_mode="invalid_json")
        run_record = extractor.extract_and_validate(
            segments=self.segments,
            chunks=self.chunks,
            job_id="test-job-002",
            episode_id="test-ep-002",
        )

        self.assertEqual(extractor.call_count, 1)
        self.assertEqual(run_record.validation_status, ValidationStatus.FAILED)
        self.assertIsNone(run_record.candidate_payload)
        self.assertGreaterEqual(len(run_record.validation_errors), 1)

    def test_fake_extractor_semantic_error_mode(self) -> None:
        """Verifies simulated hallucinated quote triggers validation error."""
        extractor = DeterministicFakeExtractor(failure_mode="semantic_error")
        run_record = extractor.extract_and_validate(
            segments=self.segments,
            chunks=self.chunks,
            job_id="test-job-003",
            episode_id="test-ep-003",
        )

        self.assertEqual(extractor.call_count, 1)
        # One valid quote and one invalid quote yields PARTIAL status
        self.assertEqual(run_record.validation_status, ValidationStatus.PARTIAL)
        error_msgs = [e.message for e in run_record.validation_errors]
        self.assertTrue(any("not found verbatim" in msg for msg in error_msgs))

    def test_fake_extractor_empty_payload_mode(self) -> None:
        """Verifies empty payload is rejected by syntactic validator."""
        extractor = DeterministicFakeExtractor(failure_mode="empty_payload")
        run_record = extractor.extract_and_validate(
            segments=self.segments,
            chunks=self.chunks,
            job_id="test-job-004",
            episode_id="test-ep-004",
        )

        self.assertEqual(extractor.call_count, 1)
        self.assertEqual(run_record.validation_status, ValidationStatus.FAILED)
        self.assertIsNone(run_record.candidate_payload)
        error_msgs = [e.message for e in run_record.validation_errors]
        self.assertTrue(any("at least 1 insight" in msg for msg in error_msgs))


if __name__ == "__main__":
    unittest.main()
