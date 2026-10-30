"""
Meri Content Pipeline: Milestone 7.5D Regression Test Suite
Safe Quotation-Grounding Contract Tests.

Tests:
1. Valid verbatim quotation spanning contiguous segments, such as indices [10, 11].
2. Verbatim quotation contained entirely in one segment.
3. Paraphrased or fabricated quotation failing with QUOTE_NOT_IN_SOURCE.
4. Non-contiguous references such as [10, 15], duplicated [10, 10], or reversed [11, 10] failing safely.
5. Missing, nonexistent, or invalid indices failing safely.
6. Correct timestamp derivation from the first referenced segment.
7. Schema/prompt consistency: model contract uses source_segment_indices, not singular obsolete field.
8. Semantic failure remaining distinct from syntactic schema error.
9. Failed candidates remaining ineligible for publication (review_status strictly 'candidate').
10. Punctuation and quotation-mark differences documenting current strict behavior.
"""

import io
import json
from pathlib import Path
from typing import Any, Dict, List
import unittest
from unittest.mock import MagicMock, patch

from backend.src.extraction_models import (
    CandidateExtractionPayload,
    CandidateQuotation,
    CandidateQuotationSegment,
    ValidationErrorCode,
    ValidationErrorItem,
    ValidationSeverity,
    ValidationStatus,
)
from backend.src.extraction_service import ExtractionService
from backend.src.gemini_client import GeminiClient, GeminiConfig
from backend.src.models import (
    NormalizedSegment,
    TranscriptAcquisitionMethod,
    TranscriptChunk,
)
from backend.src.pipeline_cli import build_parser, run_validate_extraction
from backend.src.semantic_validator import SemanticEvidenceValidator
from backend.src.syntactic_validator import SyntacticValidator
from backend.src.transcript_normalizer import clean_amharic_text

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "gemini_extraction_schema.v1.json"


def _build_synthetic_segments() -> List[NormalizedSegment]:
    """Generates synthetic segments for quotation grounding tests."""
    return [
        NormalizedSegment(
            segment_index=10,
            start_ms=45000,
            end_ms=50000,
            start_seconds=45.0,
            text="የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ",
            speaker_label="Dawit Tadesse",
            language_code="am",
            acquisition_method="manual_upload",
        ),
        NormalizedSegment(
            segment_index=11,
            start_ms=50000,
            end_ms=56000,
            start_seconds=50.0,
            text="እና ውጤቱ በጣም አበረታች ነበር።",
            speaker_label="Dawit Tadesse",
            language_code="am",
            acquisition_method="manual_upload",
        ),
        NormalizedSegment(
            segment_index=12,
            start_ms=56000,
            end_ms=62000,
            start_seconds=56.0,
            text="በዚህም ምክንያት ተጨማሪ መዋዕለ ንዋይ ፈሰስ ተደረገ።",
            speaker_label="Dawit Tadesse",
            language_code="am",
            acquisition_method="manual_upload",
        ),
        NormalizedSegment(
            segment_index=15,
            start_ms=80000,
            end_ms=88000,
            start_seconds=80.0,
            text="የገበሬዎችን ተጠቃሚነት ማረጋገጥ የረጅም ጊዜ ግባችን ነው።",
            speaker_label="Dawit Tadesse",
            language_code="am",
            acquisition_method="manual_upload",
        ),
    ]


def _build_base_payload() -> Dict[str, Any]:
    """Builds valid baseline payload conforming strictly to schema 1.0.0."""
    return {
        "schema_version": "1.0.0",
        "episode_summary": {
            "brief": "ውይይት ስለ ኢትዮጵያ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ እና የገበሬዎች ምርት አያያዝ።",
            "comprehensive": (
                "ዳዊት ታደሰ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ በኢትዮጵያ ያለውን ተግዳሮት እና መፍትሄዎች በሰፊው ያብራራል። "
                "በመንገድ ላይ የሚባክነውን የገበሬዎች ምርት ለመቀነስ የተከተሏቸውን ዘዴዎች እና የቴክኖሎጂ አጠቃቀም ይተነትናል።"
            ),
            "primary_themes": ["Logistics", "Cold Chain", "Operations"],
        },
        "guest_profile": {
            "name": "Dawit Tadesse",
            "title": "Founder & Managing Director",
            "company": "Nile Cold Chain Logistics",
            "bio": "Mechanical engineer turned logistics entrepreneur who spent 8 years designing modular refrigerated containers.",
            "industry": "Agricultural Logistics & Cold Storage",
        },
        "journey_milestones": [],
        "insights": [
            {
                "title": "የቀዝቃዛ ሰንሰለት ሎጂስቲክስ መስፋፋት",
                "category": "Operations",
                "summary": "መኪና ከመግዛት ይልቅ በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ዋናው ቁልፍ ነው።",
                "takeaways": ["የምርት ብክነትን በሰከንድ መለካት ወሳኝ ነው።"],
                "practical_action": "በመጓጓዣ መስመሮች ላይ ያለውን የሙቀት መጠን እና ብክነት መመዝገብ።",
                "evidence_segment_indices": [10],
                "confidence_score": 0.95,
            }
        ],
        "quotations": [],
        "suggested_tags": ["Logistics", "Ethiopia", "Operations"],
    }


class TestQuotationGroundingContract(unittest.TestCase):
    """Exhaustive test suite for Milestone 7.5D quotation-grounding contract."""

    def setUp(self) -> None:
        self.segments = _build_synthetic_segments()
        self.semantic_validator = SemanticEvidenceValidator()
        self.syntactic_validator = SyntacticValidator()

    # -------------------------------------------------------------------------
    # 1. Valid verbatim quotation spanning contiguous segments [10, 11]
    # -------------------------------------------------------------------------
    def test_1_valid_verbatim_quotation_spanning_contiguous_segments(self) -> None:
        payload_data = _build_base_payload()
        # Seg 10: "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ"
        # Seg 11: "እና ውጤቱ በጣም አበረታች ነበር።"
        # Combined: "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ እና ውጤቱ በጣም አበረታች ነበር።"
        cross_quote = "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ እና ውጤቱ በጣም አበረታች ነበር።"
        payload_data["quotations"] = [
            {
                "amharic_quote": cross_quote,
                "english_translation": "The first refrigerated truck trial commenced and the results were highly encouraging.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10, 11],
                "timestamp_seconds": 45,
                "context": "Explaining the initial operational testing phase of the refrigerated transport fleet.",
                "importance_rationale": "Represents the pivotal proof-of-concept milestone.",
            }
        ]

        payload, errors, status = self.semantic_validator.validate_and_assemble(payload_data, self.segments)
        self.assertEqual(status, ValidationStatus.PASSED)
        self.assertEqual(len([e for e in errors if e.severity == ValidationSeverity.ERROR]), 0)
        self.assertIsNotNone(payload)
        self.assertEqual(len(payload.quotations), 1)

        q = payload.quotations[0]
        self.assertEqual(q.amharic_quote, cross_quote)
        self.assertEqual(q.source_segment_indices, [10, 11])
        self.assertEqual(q.canonical_start_ms, 45000)
        self.assertEqual(q.canonical_timestamp_seconds, 45)
        self.assertEqual(q.review_status, "candidate")

        # Relational quotation segments
        self.assertEqual(len(payload.quotation_segments), 2)
        self.assertEqual(payload.quotation_segments[0].segment_index, 10)
        self.assertEqual(payload.quotation_segments[0].sequence_order, 0)
        self.assertEqual(payload.quotation_segments[1].segment_index, 11)
        self.assertEqual(payload.quotation_segments[1].sequence_order, 1)

    # -------------------------------------------------------------------------
    # 2. Verbatim quotation contained entirely in one segment
    # -------------------------------------------------------------------------
    def test_2_verbatim_quotation_contained_entirely_in_one_segment(self) -> None:
        payload_data = _build_base_payload()
        single_quote = "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ"
        payload_data["quotations"] = [
            {
                "amharic_quote": single_quote,
                "english_translation": "The initial trial of the refrigerated truck commenced.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10],
                "timestamp_seconds": 45,
                "context": "Describing the very beginning of the pilot testing.",
            }
        ]

        payload, errors, status = self.semantic_validator.validate_and_assemble(payload_data, self.segments)
        self.assertEqual(status, ValidationStatus.PASSED)
        self.assertEqual(len([e for e in errors if e.severity == ValidationSeverity.ERROR]), 0)
        self.assertEqual(payload.quotations[0].source_segment_indices, [10])
        self.assertEqual(payload.quotations[0].canonical_timestamp_seconds, 45)
        self.assertEqual(len(payload.quotation_segments), 1)
        self.assertEqual(payload.quotation_segments[0].segment_index, 10)

    # -------------------------------------------------------------------------
    # 3. Paraphrased or fabricated quotation failing with QUOTE_NOT_IN_SOURCE
    # -------------------------------------------------------------------------
    def test_3_paraphrased_or_fabricated_quotation_fails_with_quote_not_in_source(self) -> None:
        # Case A: Paraphrased
        payload_paraphrase = _build_base_payload()
        paraphrase_quote = "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ በሚገባ ተጀምሯል"  # Altered ending
        payload_paraphrase["quotations"] = [
            {
                "amharic_quote": paraphrase_quote,
                "english_translation": "The trial was properly commenced.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10],
                "timestamp_seconds": 45,
                "context": "Context description for paraphrase test.",
            }
        ]
        _, errors_para, status_para = self.semantic_validator.validate_and_assemble(payload_paraphrase, self.segments)
        self.assertEqual(status_para, ValidationStatus.FAILED)
        codes_para = [e.error_code for e in errors_para]
        self.assertIn(ValidationErrorCode.QUOTE_NOT_IN_SOURCE, codes_para)

        # Case B: Fabricated
        payload_fabricated = _build_base_payload()
        fabricated_quote = "በኢትዮጵያ ውስጥ ቢዝነስ ለመስራት ትልቁ ሚስጥር የመንግስት ድጋፍ ማግኘት ብቻ ነው።"
        payload_fabricated["quotations"] = [
            {
                "amharic_quote": fabricated_quote,
                "english_translation": "The only secret to business is government support.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10, 11],
                "timestamp_seconds": 45,
                "context": "Context description for fabricated test.",
            }
        ]
        payload, errors_fab, status_fab = self.semantic_validator.validate_and_assemble(payload_fabricated, self.segments)
        self.assertEqual(status_fab, ValidationStatus.FAILED)
        codes_fab = [e.error_code for e in errors_fab]
        self.assertIn(ValidationErrorCode.QUOTE_NOT_IN_SOURCE, codes_fab)
        # Verify candidate quote is preserved as-is for audit without automatic rewriting
        self.assertEqual(payload.quotations[0].amharic_quote, fabricated_quote)

    # -------------------------------------------------------------------------
    # 4. Non-contiguous references failing safely
    # -------------------------------------------------------------------------
    def test_4_non_contiguous_duplicated_and_reversed_references_fail_safely(self) -> None:
        quote_text = "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ"

        # Case A: Non-contiguous [10, 15]
        payload_gap = _build_base_payload()
        payload_gap["quotations"] = [
            {
                "amharic_quote": quote_text,
                "english_translation": "Non-contiguous reference test.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10, 15],
                "timestamp_seconds": 45,
                "context": "Context testing non-contiguous range.",
            }
        ]
        _, errors_gap, status_gap = self.semantic_validator.validate_and_assemble(payload_gap, self.segments)
        self.assertEqual(status_gap, ValidationStatus.FAILED)
        self.assertIn(ValidationErrorCode.NON_CONTIGUOUS_SEGMENTS, [e.error_code for e in errors_gap])

        # Case B: Reversed [11, 10]
        payload_rev = _build_base_payload()
        payload_rev["quotations"] = [
            {
                "amharic_quote": quote_text,
                "english_translation": "Reversed reference test.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [11, 10],
                "timestamp_seconds": 50,
                "context": "Context testing reversed range.",
            }
        ]
        _, errors_rev, status_rev = self.semantic_validator.validate_and_assemble(payload_rev, self.segments)
        self.assertEqual(status_rev, ValidationStatus.FAILED)
        self.assertIn(ValidationErrorCode.NON_CONTIGUOUS_SEGMENTS, [e.error_code for e in errors_rev])

        # Case C: Duplicated [10, 10]
        payload_dup = _build_base_payload()
        payload_dup["quotations"] = [
            {
                "amharic_quote": quote_text,
                "english_translation": "Duplicated reference test.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10, 10],
                "timestamp_seconds": 45,
                "context": "Context testing duplicated index.",
            }
        ]
        _, errors_dup, status_dup = self.semantic_validator.validate_and_assemble(payload_dup, self.segments)
        self.assertEqual(status_dup, ValidationStatus.FAILED)
        self.assertIn(ValidationErrorCode.NON_CONTIGUOUS_SEGMENTS, [e.error_code for e in errors_dup])

    # -------------------------------------------------------------------------
    # 5. Missing or nonexistent or invalid indices
    # -------------------------------------------------------------------------
    def test_5_missing_nonexistent_and_invalid_indices_fail_safely(self) -> None:
        quote_text = "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ"

        # Case A: Missing / empty array []
        payload_empty = _build_base_payload()
        payload_empty["quotations"] = [
            {
                "amharic_quote": quote_text,
                "english_translation": "Empty indices test.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [],
                "timestamp_seconds": 45,
                "context": "Context testing empty segment array.",
            }
        ]
        _, errors_empty, status_empty = self.semantic_validator.validate_and_assemble(payload_empty, self.segments)
        self.assertEqual(status_empty, ValidationStatus.FAILED)
        self.assertIn(ValidationErrorCode.EMPTY_EVIDENCE, [e.error_code for e in errors_empty])

        # Case B: Non-existent index [999]
        payload_missing = _build_base_payload()
        payload_missing["quotations"] = [
            {
                "amharic_quote": quote_text,
                "english_translation": "Non-existent index test.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [999],
                "timestamp_seconds": 45,
                "context": "Context testing non-existent segment index.",
            }
        ]
        _, errors_missing, status_missing = self.semantic_validator.validate_and_assemble(payload_missing, self.segments)
        self.assertEqual(status_missing, ValidationStatus.FAILED)
        self.assertIn(ValidationErrorCode.SEGMENT_NOT_FOUND, [e.error_code for e in errors_missing])

        # Case C: Invalid / negative index [-1]
        payload_invalid = _build_base_payload()
        payload_invalid["quotations"] = [
            {
                "amharic_quote": quote_text,
                "english_translation": "Negative index test.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [-1],
                "timestamp_seconds": 45,
                "context": "Context testing negative segment index.",
            }
        ]
        _, errors_inv, status_inv = self.semantic_validator.validate_and_assemble(payload_invalid, self.segments)
        self.assertEqual(status_inv, ValidationStatus.FAILED)
        self.assertIn(ValidationErrorCode.SEGMENT_NOT_FOUND, [e.error_code for e in errors_inv])

    # -------------------------------------------------------------------------
    # 6. Correct timestamp derivation from the first referenced segment
    # -------------------------------------------------------------------------
    def test_6_correct_timestamp_derivation_from_first_referenced_segment(self) -> None:
        payload_data = _build_base_payload()
        cross_quote = "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ እና ውጤቱ በጣም አበረታች ነበር።"
        # Segment 10 start_ms = 45000 -> 45s
        # Segment 11 start_ms = 50000 -> 50s
        # Intentionally report 99 to test that canonical derivation overrides and preserves 45s
        payload_data["quotations"] = [
            {
                "amharic_quote": cross_quote,
                "english_translation": "Timestamp derivation verification.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10, 11],
                "timestamp_seconds": 99,
                "context": "Context testing canonical timestamp calculation.",
            }
        ]

        payload, errors, _ = self.semantic_validator.validate_and_assemble(payload_data, self.segments)
        q = payload.quotations[0]
        # Must derive from FIRST segment (segment 10: 45000ms / 45s)
        self.assertEqual(q.canonical_start_ms, 45000)
        self.assertEqual(q.canonical_timestamp_seconds, 45)
        self.assertEqual(q.reported_timestamp_seconds, 99)
        self.assertTrue(q.has_timestamp_discrepancy)

        # Discrepancy logged as WARNING, not fatal error
        discrepancies = [e for e in errors if e.error_code == ValidationErrorCode.DISCREPANT_TIMESTAMP]
        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(discrepancies[0].severity, ValidationSeverity.WARNING)

    # -------------------------------------------------------------------------
    # 7. Schema/prompt consistency: model contract uses source_segment_indices
    # -------------------------------------------------------------------------
    def test_7_schema_and_prompt_consistency_uses_source_segment_indices(self) -> None:
        # Check canonical schema
        self.assertTrue(SCHEMA_PATH.is_file(), f"Schema file not found at {SCHEMA_PATH}")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)

        quote_def = schema["properties"]["quotations"]["items"]
        required_fields = quote_def["required"]

        # Required fields check
        self.assertIn("source_segment_indices", required_fields)
        self.assertNotIn("source_segment_index", required_fields)
        self.assertIn("amharic_quote", required_fields)
        self.assertIn("timestamp_seconds", required_fields)

        # Property definition check
        props = quote_def["properties"]
        self.assertIn("source_segment_indices", props)
        self.assertNotIn("source_segment_index", props)

        seg_indices_prop = props["source_segment_indices"]
        self.assertEqual(seg_indices_prop["type"], "array")
        self.assertEqual(seg_indices_prop["minItems"], 1)
        self.assertEqual(seg_indices_prop["items"]["type"], "integer")
        self.assertEqual(seg_indices_prop["items"]["minimum"], 0)

        # amharic_quote description check
        amharic_quote_desc = props["amharic_quote"]["description"]
        self.assertIn("Verbatim", amharic_quote_desc)
        self.assertIn("without paraphrasing", amharic_quote_desc)

        # Check prompt generation in GeminiClient
        client = GeminiClient(config=GeminiConfig(api_key="test-key"))
        dummy_chunk = TranscriptChunk(
            chunk_index=0,
            start_segment_index=10,
            end_segment_index=12,
            start_ms=45000,
            end_ms=62000,
            token_count_estimate=100,
            chunk_text="[Seg 10 | 00:45] Sample chunk text",
        )
        prompt_payload = client.build_prompt_payload([dummy_chunk])
        prompt_text = prompt_payload["contents"][0]["parts"][0]["text"]

        self.assertIn("source_segment_indices", prompt_text)
        # Ensure singular source_segment_index is not referenced in prompt
        self.assertNotIn("'source_segment_index'", prompt_text)
        self.assertNotIn("source_segment_index (integer)", prompt_text)
        self.assertIn("chronological order", prompt_text)
        self.assertIn("without paraphrasing or editorial additions", prompt_text)

    # -------------------------------------------------------------------------
    # 8. Semantic failure remains distinct from syntactic schema error
    # -------------------------------------------------------------------------
    def test_8_semantic_failure_remains_distinct_from_syntactic_schema_error(self) -> None:
        parser = build_parser()
        synthetic_payload = _build_base_payload()
        synthetic_payload["insights"][0]["evidence_segment_indices"] = [1]
        # Create a syntactically perfect quote that fails semantic verification (fabricated quote for segment 1)
        synthetic_payload["quotations"] = [
            {
                "amharic_quote": "ይህ በቪዲዮው ውስጥ ያልተነገረ ፈጽሞ የተፈበረከ ጽሑፍ ነው።",
                "english_translation": "This is completely fabricated quote text.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [1],
                "timestamp_seconds": 14,
                "context": "Context testing syntactic vs semantic separation.",
            }
        ]

        # Syntactic validator passes with 0 errors
        syntactic_errors = self.syntactic_validator.validate_dict(synthetic_payload)
        self.assertEqual(len(syntactic_errors), 0, "Payload must be syntactically valid against schema 1.0.0")

        # Mock GeminiClient to return this syntactically valid but semantically grounded-failing JSON
        fake_client = MagicMock()
        fake_client.generate_candidate_json.return_value = (json.dumps(synthetic_payload), 500, 200)
        fake_client.config = GeminiConfig(model_id="gemini-2.0-flash", api_key="synthetic-test-key")
        service = ExtractionService(gemini_client=fake_client)

        args = parser.parse_args([
            "validate-extraction",
            "--transcript-file", "backend/tests/fixtures/sample_transcript.json",
            "--provider", "fake",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=service)

        self.assertEqual(exit_code, 1, "Semantic validation failure must yield exit code 1")
        report = json.loads(stdout_buf.getvalue())

        self.assertEqual(report["status"], "validation_failed")
        validation = report["validation"]
        # CRITICAL ASSERTIONS:
        # Schema validity MUST be True because the JSON structure adheres strictly to the schema
        self.assertTrue(validation["schema_valid"], "Syntactically valid JSON must have schema_valid=True")
        # Evidence grounded MUST be False due to semantic failure
        self.assertFalse(validation["evidence_grounded"], "Semantic quote failure must set evidence_grounded=False")

        error_codes = [e["error_code"] for e in validation["errors"]]
        self.assertIn(ValidationErrorCode.QUOTE_NOT_IN_SOURCE.value, error_codes)
        # Ensure no syntactic schema error was spuriously recorded
        self.assertNotIn(ValidationErrorCode.SCHEMA_VIOLATION.value, error_codes)
        self.assertNotIn(ValidationErrorCode.MALFORMED_JSON.value, error_codes)

    # -------------------------------------------------------------------------
    # 9. Failed candidates remain ineligible for publication
    # -------------------------------------------------------------------------
    def test_9_failed_candidates_remain_ineligible_for_publication(self) -> None:
        payload_data = _build_base_payload()
        fabricated_quote = "ይህ በቪዲዮው ውስጥ ፈጽሞ ያልተነገረ ፈጠራ ነው።"
        payload_data["quotations"] = [
            {
                "amharic_quote": fabricated_quote,
                "english_translation": "Fabricated candidate quotation.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10],
                "timestamp_seconds": 45,
                "context": "Testing publication lock on failed candidate.",
            }
        ]

        payload, errors, status = self.semantic_validator.validate_and_assemble(payload_data, self.segments)
        self.assertEqual(status, ValidationStatus.FAILED)
        self.assertIsNotNone(payload)
        self.assertEqual(len(payload.quotations), 1)

        candidate_quote = payload.quotations[0]
        # Status MUST be strictly 'candidate', NEVER 'verified' or 'approved'
        self.assertEqual(candidate_quote.review_status, "candidate")
        self.assertNotEqual(candidate_quote.review_status, "verified")
        self.assertNotEqual(candidate_quote.review_status, "approved")

        db_dict = candidate_quote.to_db_dict(episode_id="test-ep", extraction_run_id="test-run")
        self.assertEqual(db_dict["review_status"], "candidate")

    # -------------------------------------------------------------------------
    # 10. Punctuation and quotation-mark differences document strict behavior
    # -------------------------------------------------------------------------
    def test_10_punctuation_and_quotation_mark_differences_document_strict_behavior(self) -> None:
        """
        Documents current strict verbatim verification behavior.
        Under clean_amharic_text normalization, Ethiopic punctuation ('።', '፣') and
        surrounding quotation marks are preserved exactly.
        Demonstrates that quotes with differing punctuation or added quotation marks
        fail verbatim comparison without unjustified heuristic stripping.
        """
        payload_data = _build_base_payload()
        # Source Segment 10 is: "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ" (no quotation marks, no exclamation)
        # Model returns candidate with quotation marks « » and exclamation mark !
        modified_punct_quote = "«የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ!»"
        payload_data["quotations"] = [
            {
                "amharic_quote": modified_punct_quote,
                "english_translation": "The first cold truck trial commenced!",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [10],
                "timestamp_seconds": 45,
                "context": "Testing punctuation strictness.",
            }
        ]

        payload, errors, status = self.semantic_validator.validate_and_assemble(payload_data, self.segments)
        self.assertEqual(status, ValidationStatus.FAILED)
        quote_errors = [e for e in errors if e.error_code == ValidationErrorCode.QUOTE_NOT_IN_SOURCE]
        self.assertEqual(len(quote_errors), 1, "Punctuation mismatch strictly triggers QUOTE_NOT_IN_SOURCE")
        # Document that candidate text is preserved as emitted
        self.assertEqual(payload.quotations[0].amharic_quote, modified_punct_quote)


if __name__ == "__main__":
    unittest.main()
