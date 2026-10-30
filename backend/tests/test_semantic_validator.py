"""
Meri Content Pipeline v1: Unit tests for Layer 2 Semantic and Evidence Validator.
Tests exact Amharic quotation verification, contiguous cross-segment quotations,
canonical timestamp grounding from segment start_ms, timestamp discrepancy flagging,
segment index bounding, adversarial quote fabrication, and confidence score non-override.
"""

import json
from pathlib import Path
import unittest

from backend.src.extraction_models import (
    ValidationErrorCode,
    ValidationSeverity,
    ValidationStatus,
)
from backend.src.models import NormalizedSegment, TranscriptAcquisitionMethod
from backend.src.semantic_validator import SemanticEvidenceValidator

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "schemas" / "fixtures"


class TestSemanticValidator(unittest.TestCase):
    """Test suite for Layer 2 Semantic and Evidence Grounding Validator."""

    def setUp(self) -> None:
        self.validator = SemanticEvidenceValidator()
        # Synthetic realistic normalized segments
        self.segments = [
            NormalizedSegment(
                segment_index=0,
                start_ms=0,
                end_ms=4500,
                start_seconds=0.0,
                speaker_label="Host",
                language_code="am",
                acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
                text="ሰላም ጤና ይስጥልኝ ክቡራትና ክቡራን የመሪ ፖድካስት ተከታታዮች።",
            ),
            NormalizedSegment(
                segment_index=1,
                start_ms=5000,
                end_ms=9500,
                start_seconds=5.0,
                speaker_label="Host",
                language_code="am",
                acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
                text="ዛሬ በስቱዲዮአችን የናይል ኮልድ ቼይን ሎጂስቲክስ መስራች አቶ ዳዊት ታደሰን ይዘን ቀርበናል።",
            ),
            NormalizedSegment(
                segment_index=2,
                start_ms=10000,
                end_ms=15500,
                start_seconds=10.0,
                speaker_label="Host",
                language_code="am",
                acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
                text="እንኳን ደህና መጣህ ዳዊት። ስራውን ስትጀምር ዋናው ተግዳሮት ምን ነበር?",
            ),
            NormalizedSegment(
                segment_index=3,
                start_ms=16000,
                end_ms=22000,
                start_seconds=16.0,
                speaker_label="Dawit Tadesse",
                language_code="am",
                acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
                text="የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን",
            ),
            NormalizedSegment(
                segment_index=4,
                start_ms=22500,
                end_ms=29000,
                start_seconds=22.5,
                speaker_label="Dawit Tadesse",
                language_code="am",
                acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
                text="ምርት ዋጋ በሰከንድ ማስላት ነው። ገበሬው የደከመበትን እህል በክብር ማድረስ አለብን።",
            ),
            NormalizedSegment(
                segment_index=5,
                start_ms=30000,
                end_ms=36000,
                start_seconds=30.0,
                speaker_label="Dawit Tadesse",
                language_code="am",
                acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
                text="የቀዝቃዛ ማከማቻ ቴክኖሎጂ በየቦታው ካልተዘረጋ ሰብሉ በሙቀት ይበላሻል።",
            ),
        ]

        # Valid candidate payload referencing above segments
        self.valid_data = {
            "schema_version": "1.0.0",
            "episode_summary": {
                "brief": "ዳዊት ታደሰ የግብርና ሎጂስቲክስና የቀዝቃዛ ማከማቻ ፈተናዎችን በስፋት ይተነትናል።",
                "comprehensive": "በዚህ ክፍል አቶ ዳዊት ታደሰ የግብርና ምርቶች በመጓጓዣ ወቅት የሚባክኑበትን ምክንያት እና የቴክኖሎጂ መፍትሄዎችን ያብራራሉ።",
                "primary_themes": ["Logistics", "Cold Storage"],
            },
            "guest_profile": {
                "name": "Dawit Tadesse",
                "title": "Founder",
                "company": "Nile Cold Chain",
                "bio": "Mechanical engineer working on cold storage systems.",
                "industry": "Logistics",
            },
            "journey_milestones": [
                {
                    "phase_or_year": "2018",
                    "milestone_description": "የመጀመሪያው የቀዝቃዛ ማከማቻ ተሽከርካሪ ሙከራ ተጀመረ።",
                    "strategic_decision": "የውጭ ሀገር መኪናዎችን ከመግዛት ይልቅ በሀገር ውስጥ ማገጣጠም ተመረጠ።",
                    "evidence_segment_indices": [3, 4],
                }
            ],
            "insights": [
                {
                    "title": "Cold Chain Unit Economics",
                    "category": "Operations",
                    "summary": "Calculating perishable spoilage by second preserves margin.",
                    "takeaways": ["Track cargo arrival temperatures.", "Prioritize telemetry sensors."],
                    "practical_action": "Audit current transit spoilage rates before expanding fleet.",
                    "evidence_segment_indices": [3, 4],
                    "confidence_score": 0.95,
                }
            ],
            "quotations": [
                {
                    "amharic_quote": "የቀዝቃዛ ማከማቻ ቴክኖሎጂ በየቦታው ካልተዘረጋ ሰብሉ በሙቀት ይበላሻል።",
                    "english_translation": "If cold storage technology is not deployed across hubs, produce perishes from heat.",
                    "speaker": "Dawit Tadesse",
                    "source_segment_indices": [5],
                    "timestamp_seconds": 30,
                    "context": "Explaining spoilage risks across agricultural corridors.",
                }
            ],
            "suggested_tags": ["Logistics", "Operations"],
        }

    def test_verbatim_quote_and_canonical_timestamp_derivation(self) -> None:
        """Verifies exact verbatim Amharic quote matches and derives canonical start_ms / 1000."""
        payload, errors, status = self.validator.validate_and_assemble(self.valid_data, self.segments)

        self.assertEqual(status, ValidationStatus.PASSED)
        self.assertEqual(len([e for e in errors if e.severity == ValidationSeverity.ERROR]), 0)
        self.assertIsNotNone(payload)
        self.assertEqual(len(payload.quotations), 1)

        quote = payload.quotations[0]
        self.assertEqual(quote.canonical_start_ms, 30000)
        self.assertEqual(quote.canonical_timestamp_seconds, 30)
        self.assertFalse(quote.has_timestamp_discrepancy)
        self.assertEqual(quote.review_status, "candidate")

    def test_canonical_timestamp_preservation_on_model_discrepancy(self) -> None:
        """
        When model reports a timestamp different from source segment start_ms,
        preserves canonical timestamp and flags a DISCREPANT_TIMESTAMP warning.
        """
        data = json.loads(json.dumps(self.valid_data))
        # Model reports 34 seconds instead of segment 5's canonical 30 seconds
        data["quotations"][0]["timestamp_seconds"] = 34

        payload, errors, status = self.validator.validate_and_assemble(data, self.segments)

        self.assertIsNotNone(payload)
        quote = payload.quotations[0]
        # Canonical timestamp MUST remain 30 seconds (from start_ms: 30000)
        self.assertEqual(quote.canonical_start_ms, 30000)
        self.assertEqual(quote.canonical_timestamp_seconds, 30)
        self.assertEqual(quote.reported_timestamp_seconds, 34)
        self.assertTrue(quote.has_timestamp_discrepancy)

        # Status should still pass (or partial if error), warning is recorded
        discrepancy_warnings = [e for e in errors if e.error_code == ValidationErrorCode.DISCREPANT_TIMESTAMP]
        self.assertEqual(len(discrepancy_warnings), 1)
        self.assertEqual(discrepancy_warnings[0].severity, ValidationSeverity.WARNING)

    def test_cross_segment_quotation_contiguous_success(self) -> None:
        """Verifies cross-segment quote spanning segments 3 and 4 succeeds when contiguous."""
        data = json.loads(json.dumps(self.valid_data))
        # Quote begins in segment 3 and ends in segment 4
        cross_quote = "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።"
        data["quotations"] = [
            {
                "amharic_quote": cross_quote,
                "english_translation": "The greatest test in logistics is calculating perishable cargo by the second.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [3, 4],
                "timestamp_seconds": 16,
                "context": "Discussing freight tracking.",
            }
        ]

        payload, errors, status = self.validator.validate_and_assemble(data, self.segments)
        self.assertEqual(status, ValidationStatus.PASSED)
        self.assertEqual(len([e for e in errors if e.severity == ValidationSeverity.ERROR]), 0)
        self.assertEqual(payload.quotations[0].canonical_timestamp_seconds, 16)
        self.assertEqual(payload.quotations[0].source_segment_indices, [3, 4])

        # Assert quotation_segments relational linkages with sequence ordering (Milestone 3)
        self.assertEqual(len(payload.quotation_segments), 2)
        self.assertEqual(payload.quotation_segments[0].quotation_index, 0)
        self.assertEqual(payload.quotation_segments[0].segment_index, 3)
        self.assertEqual(payload.quotation_segments[0].sequence_order, 0)
        self.assertEqual(payload.quotation_segments[1].quotation_index, 0)
        self.assertEqual(payload.quotation_segments[1].segment_index, 4)
        self.assertEqual(payload.quotation_segments[1].sequence_order, 1)

    def test_cross_segment_quotation_non_contiguous_rejection(self) -> None:
        """Rejects cross-segment quote that references non-contiguous segment indices."""
        data = json.loads(json.dumps(self.valid_data))
        data["quotations"] = [
            {
                "amharic_quote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
                "english_translation": "Testing translation for non contiguous segments.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [2, 5],  # Non-contiguous!
                "timestamp_seconds": 10,
                "context": "Context test",
            }
        ]

        payload, errors, status = self.validator.validate_and_assemble(data, self.segments)
        error_codes = [e.error_code for e in errors]
        self.assertIn(ValidationErrorCode.NON_CONTIGUOUS_SEGMENTS, error_codes)
        self.assertEqual(status, ValidationStatus.FAILED)

    def test_fabricated_quote_adversarial_rejection(self) -> None:
        """
        Adversarial test: Model hallucinates a quote not spoken anywhere in the source transcript.
        Ensures quote is preserved verbatim in payload, error is recorded, and status reflects failure.
        """
        data = json.loads(json.dumps(self.valid_data))
        fabricated_text = "በኢትዮጵያ ውስጥ ቢዝነስ ለመስራት ትልቁ ሚስጥር የመንግስት ድጋፍ ማግኘት ብቻ ነው።"
        data["quotations"] = [
            {
                "amharic_quote": fabricated_text,
                "english_translation": "The only secret to business in Ethiopia is government support.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [3],
                "timestamp_seconds": 16,
                "context": "Fabricated statement.",
            }
        ]

        payload, errors, status = self.validator.validate_and_assemble(data, self.segments)
        self.assertEqual(status, ValidationStatus.FAILED)

        quote_errors = [e for e in errors if e.error_code == ValidationErrorCode.QUOTE_NOT_IN_SOURCE]
        self.assertEqual(len(quote_errors), 1)

        # Must preserve original fabricated candidate quote without rewriting or auto-correcting
        self.assertEqual(payload.quotations[0].amharic_quote, fabricated_text)

    def test_paraphrased_quote_adversarial_rejection(self) -> None:
        """
        Adversarial test: Model outputs an Amharic paraphrase rather than exact verbatim spoken words.
        Ensures paraphrase is caught and rejected.
        """
        data = json.loads(json.dumps(self.valid_data))
        # Paraphrased version of segment 5 (altered wording)
        paraphrased = "የማቀዝቀዣ ማሽኖች በየቦታው ካልተተከሉ አትክልቱና ፍራፍሬው በፀሐይ ሙቀት ይበላሻል።"
        data["quotations"] = [
            {
                "amharic_quote": paraphrased,
                "english_translation": "If cooling machines are not planted everywhere, vegetables spoil.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [5],
                "timestamp_seconds": 30,
                "context": "Paraphrase test.",
            }
        ]

        payload, errors, status = self.validator.validate_and_assemble(data, self.segments)
        self.assertEqual(status, ValidationStatus.FAILED)
        self.assertTrue(any(e.error_code == ValidationErrorCode.QUOTE_NOT_IN_SOURCE for e in errors))

    def test_nonexistent_segment_index_rejection(self) -> None:
        """Rejects references to segment indices that do not exist in the source transcript."""
        data = json.loads(json.dumps(self.valid_data))
        data["insights"][0]["evidence_segment_indices"] = [999]  # Out of range

        payload, errors, status = self.validator.validate_and_assemble(data, self.segments)
        self.assertEqual(status, ValidationStatus.FAILED)
        self.assertTrue(any(e.error_code == ValidationErrorCode.SEGMENT_NOT_FOUND for e in errors))

    def test_confidence_score_cannot_bypass_unsupported_evidence(self) -> None:
        """
        Adversarial test: An insight with confidence_score: 0.999 must still fail
        if evidence references are missing or invalid.
        """
        data = json.loads(json.dumps(self.valid_data))
        data["insights"][0]["confidence_score"] = 0.999
        data["insights"][0]["evidence_segment_indices"] = [888]

        payload, errors, status = self.validator.validate_and_assemble(data, self.segments)
        self.assertEqual(status, ValidationStatus.FAILED)

        seg_errors = [e for e in errors if e.error_code == ValidationErrorCode.SEGMENT_NOT_FOUND]
        self.assertGreater(len(seg_errors), 0)
        self.assertIn("cannot override missing evidence", seg_errors[0].message)

    def test_partial_status_when_some_items_valid_and_some_invalid(self) -> None:
        """
        Verifies that when some candidate items are valid and others are invalid,
        the status transitions to PARTIAL (requiring human editorial review).
        """
        data = json.loads(json.dumps(self.valid_data))
        # Add 1 valid quote and 1 fabricated quote
        data["quotations"].append(
            {
                "amharic_quote": "ይህ ፈጽሞ ያልተነገረ ሀሰተኛ ንግግር ነው።",
                "english_translation": "This is completely fabricated.",
                "speaker": "Unknown",
                "source_segment_index": 1,
                "timestamp_seconds": 5,
                "context": "Fabrication",
            }
        )

        payload, errors, status = self.validator.validate_and_assemble(data, self.segments)
        # One valid quote and one valid insight, but one bad quote -> PARTIAL
        self.assertEqual(status, ValidationStatus.PARTIAL)
        self.assertEqual(len(payload.quotations), 2)

    def test_valid_segment_references_establish_provenance_only_without_factual_approval(self) -> None:
        """
        Confirms that valid segment indices establish provenance linkage only.
        Technical validation passing (ValidationStatus.PASSED) DOES NOT prove that the
        substantive business claims are true or approved, and strictly leaves review_status
        as 'candidate' pending human editorial review.
        """
        payload, errors, status = self.validator.validate_and_assemble(self.valid_data, self.segments)

        # Technical validation passes because cited segments exist and quote is verbatim
        self.assertEqual(status, ValidationStatus.PASSED)
        self.assertIsNotNone(payload)

        # Provenance linkage is verified
        self.assertEqual(len(payload.evidence_references), 2)  # Segment 3 and 4 linked
        for ev in payload.evidence_references:
            self.assertIn(ev.segment_index, [3, 4])

        # Substantive claims are strictly UNAPPROVED candidates
        for insight in payload.insights:
            self.assertEqual(
                insight.review_status,
                "candidate",
                "Automated validation must NEVER promote candidate insight to 'approved'.",
            )
            # Database serialization must reflect 'candidate'
            db_dict = insight.to_db_dict(episode_id="ep-123")
            self.assertEqual(db_dict["review_status"], "candidate")

        for quote in payload.quotations:
            self.assertEqual(quote.review_status, "candidate")
            db_dict = quote.to_db_dict(episode_id="ep-123")
            self.assertEqual(db_dict["review_status"], "candidate")


if __name__ == "__main__":
    unittest.main()
