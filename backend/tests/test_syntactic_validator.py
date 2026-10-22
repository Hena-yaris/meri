"""
Meri Content Pipeline v1: Unit tests for Layer 1 Syntactic Schema Validator.
Validates raw Gemini JSON output against structural, type, bounds, and enum constraints
defined in backend/schemas/gemini_extraction_schema.v1.json.
"""

import json
from pathlib import Path
import unittest

from backend.src.extraction_models import ValidationErrorCode, ValidationSeverity
from backend.src.syntactic_validator import VALID_BUSINESS_CATEGORIES, SyntacticValidator

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "schemas" / "fixtures"


class TestSyntacticValidator(unittest.TestCase):
    """Test suite for Layer 1 syntactic and schema validation."""

    def setUp(self) -> None:
        self.validator = SyntacticValidator()
        self.valid_fixture_path = FIXTURES_DIR / "sample_candidate_gemini_response.json"
        self.invalid_fixture_path = FIXTURES_DIR / "sample_invalid_gemini_response.json"

    def test_valid_fixture_passes_syntactic_validation(self) -> None:
        """Verifies that sample_candidate_gemini_response.json passes with 0 errors."""
        with open(self.valid_fixture_path, "r", encoding="utf-8") as f:
            raw_json = f.read()

        parsed, errors = self.validator.validate_raw_json(raw_json)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {errors}")

    def test_invalid_fixture_fails_syntactic_validation(self) -> None:
        """Verifies that sample_invalid_gemini_response.json produces actionable errors."""
        with open(self.invalid_fixture_path, "r", encoding="utf-8") as f:
            raw_json = f.read()

        parsed, errors = self.validator.validate_raw_json(raw_json)
        self.assertIsNotNone(parsed)
        self.assertGreater(len(errors), 0)

        error_codes = [e.error_code for e in errors]
        # Should flag invalid category, bounds, or missing keys
        self.assertTrue(
            any(
                c in error_codes
                for c in [
                    ValidationErrorCode.INVALID_CATEGORY,
                    ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                    ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS,
                    ValidationErrorCode.MISSING_REQUIRED_KEY,
                ]
            )
        )

    def test_malformed_json_and_non_dict_root(self) -> None:
        """Rejects unparseable JSON strings and non-object top-level payloads."""
        # Empty string
        parsed, errors = self.validator.validate_raw_json("")
        self.assertIsNone(parsed)
        self.assertEqual(errors[0].error_code, ValidationErrorCode.MALFORMED_JSON)

        # Syntax error
        parsed, errors = self.validator.validate_raw_json('{"unclosed": "brace"')
        self.assertIsNone(parsed)
        self.assertEqual(errors[0].error_code, ValidationErrorCode.MALFORMED_JSON)

        # Array at root
        parsed, errors = self.validator.validate_raw_json('[1, 2, 3]')
        self.assertIsNone(parsed)
        self.assertEqual(errors[0].error_code, ValidationErrorCode.TYPE_MISMATCH)

    def test_missing_required_top_level_keys(self) -> None:
        """Detects missing mandatory top-level sections."""
        incomplete_payload = {
            "schema_version": "1.0.0",
            # missing episode_summary
            "guest_profile": {"name": "Test"},
            # missing insights, quotations, suggested_tags
        }
        errors = self.validator.validate_dict(incomplete_payload)
        missing_fields = {e.field for e in errors if e.error_code == ValidationErrorCode.MISSING_REQUIRED_KEY}
        self.assertIn("episode_summary", missing_fields)
        self.assertIn("insights", missing_fields)
        self.assertIn("quotations", missing_fields)
        self.assertIn("suggested_tags", missing_fields)

    def test_business_category_enum_enforcement(self) -> None:
        """Ensures insights only accept the 9 standardized business domains."""
        self.assertEqual(len(VALID_BUSINESS_CATEGORIES), 9)

        base_insight = {
            "title": "Scaling Operations",
            "category": "Crypto & Web3",  # Invalid domain
            "summary": "This is a sufficiently long summary explaining operational mechanics.",
            "takeaways": ["First actionable takeaway here."],
            "practical_action": "Implement cold storage node immediately.",
            "evidence_segment_indices": [1],
            "confidence_score": 0.95,
        }

        payload = {
            "schema_version": "1.0.0",
            "episode_summary": {
                "brief": "Short summary text that meets minimum length.",
                "comprehensive": "Comprehensive summary text that meets minimum length and explains context.",
                "primary_themes": ["Operations"],
            },
            "guest_profile": {
                "name": "Abebe Bikila",
                "title": "CEO",
                "company": "Run Logistics",
                "bio": "Veteran founder with extensive experience in marathon scaling.",
                "industry": "Logistics",
            },
            "insights": [base_insight],
            "quotations": [
                {
                    "amharic_quote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
                    "english_translation": "The real test in logistics is calculating perishable cargo by the second.",
                    "speaker": "Abebe Bikila",
                    "source_segment_index": 1,
                    "timestamp_seconds": 120,
                    "context": "Discussing freight tracking across high altitude mountain passes.",
                }
            ],
            "suggested_tags": ["Logistics", "Operations"],
        }

        errors = self.validator.validate_dict(payload)
        category_errors = [e for e in errors if e.error_code == ValidationErrorCode.INVALID_CATEGORY]
        self.assertEqual(len(category_errors), 1)
        self.assertIn("Crypto & Web3", category_errors[0].message)

    def test_array_and_string_boundary_constraints(self) -> None:
        """Enforces string length limits and array bounds."""
        payload = {
            "schema_version": "1.0.0",
            "episode_summary": {
                "brief": "Too short",  # minLength 20
                "comprehensive": "Also short",  # minLength 50
                "primary_themes": [],  # minItems 1
            },
            "guest_profile": {
                "name": "A",  # minLength 2
                "title": "C",
                "company": "B",
                "bio": "Too short bio",  # minLength 20
                "industry": "I",
            },
            "insights": [
                {
                    "title": "Tiny",  # minLength 5
                    "category": "Operations",
                    "summary": "Short",  # minLength 30
                    "takeaways": [],  # minItems 1
                    "practical_action": "Brief",  # minLength 15
                    "evidence_segment_indices": [],  # minItems 1
                    "confidence_score": 1.5,  # maximum 1.0
                }
            ],
            "quotations": [
                {
                    "amharic_quote": "አጭር",  # minLength 10
                    "english_translation": "Short",  # minLength 10
                    "speaker": "A",
                    "source_segment_index": -1,  # minimum 0
                    "timestamp_seconds": -5,  # negative
                    "context": "Context too short",  # minLength 15
                }
            ],
            "suggested_tags": ["OneTagOnly"],  # minItems 2
        }

        errors = self.validator.validate_dict(payload)
        error_fields = [e.field for e in errors]

        self.assertIn("episode_summary.brief", error_fields)
        self.assertIn("episode_summary.comprehensive", error_fields)
        self.assertIn("episode_summary.primary_themes", error_fields)
        self.assertIn("suggested_tags", error_fields)


if __name__ == "__main__":
    unittest.main()
