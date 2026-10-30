"""
Meri Content Pipeline v1: Unit tests for Editorial Review Preparer (Milestone 7.8).

Tests deterministic local review preparation covering:
1. Valid synthetic candidate input.
2. Missing required candidate text.
3. Invalid segment indices.
4. Quotation grounding and timestamp consistency.
5. Evidence excerpts matching the selected reconstructed segments.
6. Sponsor-range overlap producing a warning rather than rejection.
7. Unresolved speaker attribution remaining unresolved.
8. Preservation of Amharic characters and Ethiopic punctuation.
9. Default review status remaining unreviewed.
10. Malformed JSON and schema violations failing clearly.
"""

import json
import os
import tempfile
import unittest

from backend.src.editorial_review_preparer import (
    DEFAULT_SPONSOR_RANGE,
    EDITORIAL_DISCLAIMER,
    EditorialReviewPreparer,
)


class TestEditorialReviewPreparer(unittest.TestCase):
    """Test suite for Milestone 7.8 Editorial Review Preparer."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.transcript_path = os.path.join(self.temp_dir.name, "test_transcript.vtt")
        self.candidate_path = os.path.join(self.temp_dir.name, "test_candidate.json")
        self.output_path = os.path.join(self.temp_dir.name, "test_output.json")

        # Create a reliable synthetic transcript with known Ethiopic text and segments
        # Segments:
        # 0: Intro (0-10s)
        # 1: Quote 0 text (10-25s)
        # 2: Discussion / sponsor slot (25-40s)
        # 3: Quote 1 text (40-60s)
        # 4: Conclusion (60-75s)
        vtt_content = (
            "WEBVTT - Test Transcript\n\n"
            "00:00:00.000 --> 00:00:10.000\n"
            "እንኳን ደህና መጣችሁ ይህ የመሪ ፖድካስት ውይይት ነው።\n\n"
            "00:00:10.000 --> 00:00:25.000\n"
            "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።\n\n"
            "00:00:25.000 --> 00:00:40.000\n"
            "ይህ የንግድ ማስታወቂያ እና የገበያ መረጃ ክፍለ ጊዜ ነው።\n\n"
            "00:00:40.000 --> 00:01:00.000\n"
            "መጀመሪያ ላይ የራሳችንን መኪና ከመግዛት ይልቅ ያሉትን የጭነት መኪናዎች በመከራየት እና በማሻሻል ጀመርን።\n\n"
            "00:01:00.000 --> 00:01:15.000\n"
            "በመጨረሻም ስራችንን በከፍተኛ ጥራት እና ውጤታማነት አጠናቀቅን።\n"
        )
        with open(self.transcript_path, "w", encoding="utf-8") as f:
            f.write(vtt_content)

        # Baseline valid candidate payload grounded in segments 1 and 3
        self.valid_candidate = {
            "schema_version": "1.0.0",
            "episode_summary": {
                "brief": "ውይይት ስለ ኢትዮጵያ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ እና የገበሬዎች ምርት አያያዝ።",
                "comprehensive": (
                    "ዳዊት ታደሰ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ በኢትዮጵያ ያለውን ተግዳሮት እና መፍትሄዎች በሰፊው ያብራራል። "
                    "በመንገድ ላይ የሚባክነውን የገበሬዎች ምርት ለመቀነስ የተከተሏቸውን ዘዴዎች እና የቴክኖሎጂ አጠቃቀም ይተነትናል።"
                ),
                "primary_themes": ["Cold Chain Logistics", "Agritech Freight"],
            },
            "guest_profile": {
                "name": "Dawit Tadesse",
                "title": "Founder & Managing Director",
                "company": "Nile Cold Chain Logistics",
                "bio": "Mechanical engineer turned logistics entrepreneur who spent 8 years designing modular refrigerated truck containers.",
                "industry": "Agricultural Logistics & Cold Storage",
                "journey_summary": "Pivoted from engineering consultancy into logistics after witnessing harvest spoilage.",
            },
            "journey_milestones": [
                {
                    "phase_or_year": "2018 - Prototype Phase",
                    "milestone_description": "Engineered the first modular hybrid refrigerated container suited for volcanic gravel roads.",
                    "strategic_decision": "Rejected purchasing new European refrigerated trucks in favor of building retrofittable container bodies locally.",
                    "evidence_segment_indices": [1],
                }
            ],
            "insights": [
                {
                    "title": "Decoupling Fleet Ownership from Logistics",
                    "category": "Operations",
                    "summary": "Purchasing heavy transport vehicles burns seed capital too early. Partnering with existing truckers yields faster profitability.",
                    "takeaways": [
                        "Heavy asset purchases tie down working capital needed for quality control.",
                        "Retrofitting independent trucker fleets cuts capital expenditure by 60%.",
                    ],
                    "practical_action": "Audit current asset depreciation against subcontracting models before financing fleet expansions.",
                    "evidence_segment_indices": [1, 3],
                    "confidence_score": 0.95,
                }
            ],
            "quotations": [
                {
                    "amharic_quote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
                    "english_translation": "The greatest test in logistics isn't buying trucks; it's calculating by the second the value of harvest perishing on the highway.",
                    "speaker": "Dawit Tadesse",
                    "source_segment_indices": [1],
                    "timestamp_seconds": 10,
                    "context": "Explaining why telemetry monitoring matters more than fleet volume.",
                    "importance_rationale": "Encapsulates the shift from capital expenditure to information velocity.",
                }
            ],
            "suggested_tags": ["Logistics", "ColdChain", "Ethiopia"],
        }
        with open(self.candidate_path, "w", encoding="utf-8") as f:
            json.dump(self.valid_candidate, f, ensure_ascii=False, indent=2)

        self.preparer = EditorialReviewPreparer(sponsor_range=(2, 2))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_01_valid_synthetic_candidate_input(self) -> None:
        """Requirement 1: Valid synthetic candidate input produces ready_for_human_review package."""
        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=self.candidate_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )

        self.assertEqual(result.status, "ready_for_human_review")
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(os.path.exists(self.output_path))

        report = result.report
        self.assertEqual(report["artifact_type"], "editorial_review_package")
        self.assertTrue(report["automated_validation"]["schema_valid"])
        self.assertTrue(report["automated_validation"]["evidence_grounding_valid"])
        self.assertTrue(report["automated_validation"]["quotation_grounding_passed"])
        self.assertEqual(report["automated_validation"]["total_errors"], 0)
        self.assertEqual(report["disclaimer"], EDITORIAL_DISCLAIMER)

    def test_02_missing_required_candidate_text(self) -> None:
        """Requirement 2: Missing required candidate text fails clearly without fabricating content."""
        invalid_candidate = dict(self.valid_candidate)
        # Violate schema: empty bio (min length is 50)
        invalid_candidate["guest_profile"] = {
            "name": "Dawit Tadesse",
            "title": "Founder",
            "company": "Nile Logistics",
            "bio": "Too short",  # < 50 chars
            "industry": "Logistics",
        }
        bad_candidate_path = os.path.join(self.temp_dir.name, "bad_text_candidate.json")
        with open(bad_candidate_path, "w", encoding="utf-8") as f:
            json.dump(invalid_candidate, f)

        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=bad_candidate_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )

        self.assertEqual(result.status, "validation_failed")
        self.assertEqual(result.exit_code, 1)
        self.assertFalse(result.report["automated_validation"]["schema_valid"])
        self.assertGreater(result.report["automated_validation"]["total_errors"], 0)

    def test_03_invalid_segment_indices(self) -> None:
        """Requirement 3: Invalid segment indices produce unresolved state and SEGMENT_NOT_FOUND error."""
        invalid_candidate = dict(self.valid_candidate)
        invalid_candidate["insights"] = [
            {
                "title": "Decoupling Fleet Ownership from Logistics",
                "category": "Operations",
                "summary": "Purchasing heavy transport vehicles burns seed capital too early.",
                "takeaways": ["Heavy asset purchases tie down working capital."],
                "practical_action": "Audit asset depreciation models.",
                "evidence_segment_indices": [999],  # Does not exist
                "confidence_score": 0.90,
            }
        ]
        bad_candidate_path = os.path.join(self.temp_dir.name, "bad_indices_candidate.json")
        with open(bad_candidate_path, "w", encoding="utf-8") as f:
            json.dump(invalid_candidate, f)

        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=bad_candidate_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )

        self.assertEqual(result.status, "validation_failed")
        self.assertEqual(result.exit_code, 1)
        self.assertFalse(result.report["automated_validation"]["evidence_grounding_valid"])

        errors = result.report["automated_validation"]["errors"]
        has_seg_error = any(e.get("error_code") == "SEGMENT_NOT_FOUND" for e in errors)
        self.assertTrue(has_seg_error)

        insight_review = result.report["review_package"]["insights"][0]
        self.assertEqual(insight_review["evidence_grounding_status"], "unresolved")

    def test_04_quotation_grounding_and_timestamp_consistency(self) -> None:
        """Requirement 4: Quotation grounding checks verbatim match and checks timestamp consistency."""
        # 4A: Fabricated quote text triggers QUOTE_NOT_IN_SOURCE
        bad_quote_candidate = dict(self.valid_candidate)
        bad_quote_candidate["quotations"] = [
            {
                "amharic_quote": "ይህ ፈጽሞ በንግግሩ ውስጥ የሌለ የተፈጠረ ሀረግ እና ልብ ወለድ ነው።",  # Not in segment 1
                "english_translation": "This is completely fabricated text.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [1],
                "timestamp_seconds": 10,
                "context": "Fake context statement.",
                "importance_rationale": "Rationale.",
            }
        ]
        bad_quote_path = os.path.join(self.temp_dir.name, "bad_quote_candidate.json")
        with open(bad_quote_path, "w", encoding="utf-8") as f:
            json.dump(bad_quote_candidate, f)

        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=bad_quote_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )
        self.assertEqual(result.status, "validation_failed")
        self.assertFalse(result.report["automated_validation"]["quotation_grounding_passed"])
        quote_review = result.report["review_package"]["quotations"][0]
        self.assertEqual(quote_review["grounding_status"], "mismatch")

        # 4B: Timestamp discrepancy triggers warning but preserves canonical seconds
        discrepant_ts_candidate = dict(self.valid_candidate)
        discrepant_ts_candidate["quotations"] = [
            {
                "amharic_quote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
                "english_translation": "The greatest test in logistics...",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": [1],
                "timestamp_seconds": 999,  # Reported 999s vs segment 1 start 10s
                "context": "Explaining telemetry.",
                "importance_rationale": "Rationale.",
            }
        ]
        discrepant_path = os.path.join(self.temp_dir.name, "discrepant_ts_candidate.json")
        with open(discrepant_path, "w", encoding="utf-8") as f:
            json.dump(discrepant_ts_candidate, f)

        result_ts = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=discrepant_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )
        quote_ts_review = result_ts.report["review_package"]["quotations"][0]
        self.assertEqual(quote_ts_review["canonical_timestamp_seconds"], 10)
        self.assertFalse(quote_ts_review["timestamp_consistent"])
        self.assertEqual(quote_ts_review["timestamp_difference_seconds"], 989)
        self.assertGreater(result_ts.report["automated_validation"]["total_warnings"], 0)

    def test_05_evidence_excerpts_matching_selected_segments(self) -> None:
        """Requirement 5: Evidence excerpts match the selected reconstructed segments."""
        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=self.candidate_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )
        insight_review = result.report["review_package"]["insights"][0]
        excerpts = insight_review["evidence_excerpts"]
        self.assertEqual(len(excerpts), 2)
        # Excerpt 0 must match segment 1
        self.assertEqual(excerpts[0]["segment_index"], 1)
        self.assertIn("የሎጂስቲክስ ስራ ትልቁ ፈተና", excerpts[0]["text"])
        # Excerpt 1 must match segment 3
        self.assertEqual(excerpts[1]["segment_index"], 3)
        self.assertIn("መጀመሪያ ላይ የራሳችንን መኪና", excerpts[1]["text"])

    def test_06_sponsor_range_overlap_creates_warning_not_rejection(self) -> None:
        """Requirement 6: Evidence overlapping sponsor range creates warning without rejecting candidate."""
        sponsor_candidate = dict(self.valid_candidate)
        # Segment 2 is in our test sponsor range (2, 2)
        sponsor_candidate["insights"] = [
            {
                "title": "Insight In Sponsor Block",
                "category": "Operations",
                "summary": "Summary of insight that touches segment 2.",
                "takeaways": ["Takeaway 1."],
                "practical_action": "Practical action.",
                "evidence_segment_indices": [1, 2],  # Index 2 is in sponsor range!
                "confidence_score": 0.85,
            }
        ]
        sponsor_path = os.path.join(self.temp_dir.name, "sponsor_candidate.json")
        with open(sponsor_path, "w", encoding="utf-8") as f:
            json.dump(sponsor_candidate, f)

        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=sponsor_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )

        # Status must remain ready_for_human_review, NOT rejected!
        self.assertEqual(result.status, "ready_for_human_review")
        self.assertEqual(result.exit_code, 0)
        self.assertGreater(result.report["sponsor_warnings"]["warning_count"], 0)

        flagged = result.report["sponsor_warnings"]["flagged_items"]
        self.assertTrue(any(item["item_type"] == "insight" and 2 in item["overlapping_segments"] for item in flagged))

        ins_review = result.report["review_package"]["insights"][0]
        self.assertTrue(ins_review["sponsor_overlap_warning"])
        self.assertEqual(ins_review["sponsor_overlap_segments"], [2])

    def test_07_unresolved_speaker_attribution_remains_unresolved(self) -> None:
        """Requirement 7: Unresolved speaker attribution remains unresolved without guessing."""
        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=self.candidate_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )
        report = result.report
        # Quotation speaker status must be unverified
        quote_review = report["review_package"]["quotations"][0]
        self.assertEqual(quote_review["speaker_attribution_status"], "unverified")

        # Guest profile speaker classification must be unresolved
        guest_review = report["review_package"]["guest_profile"]
        self.assertEqual(guest_review["source_speaker_classification"], "unresolved")

        # Insight speaker classification must be unresolved
        insight_review = report["review_package"]["insights"][0]
        self.assertEqual(insight_review["speaker_classification"], "unresolved")

    def test_08_preservation_of_amharic_characters_and_punctuation(self) -> None:
        """Requirement 8: Preservation of Amharic characters and Ethiopic punctuation."""
        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=self.candidate_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )
        with open(self.output_path, "r", encoding="utf-8") as f:
            raw_output = f.read()

        # Must contain verbatim Ethiopic full stop and words without unicode escape sequences
        self.assertIn("የሎጂስቲክስ ስራ ትልቁ ፈተና", raw_output)
        self.assertIn("።", raw_output)
        self.assertNotIn("\\u1362", raw_output)  # Not escaped as unicode code point

    def test_09_default_review_status_remaining_unreviewed(self) -> None:
        """Requirement 9: Default review status remains unreviewed across all sections."""
        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=self.candidate_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )
        pkg = result.report["review_package"]

        # Episode summary
        self.assertEqual(pkg["episode_summary"]["review"]["status"], "unreviewed")
        self.assertEqual(pkg["episode_summary"]["review"]["decision"], "unreviewed")
        self.assertIsNone(pkg["episode_summary"]["review"]["reviewer_notes"])

        # Guest profile
        self.assertEqual(pkg["guest_profile"]["review"]["status"], "unreviewed")
        self.assertEqual(pkg["guest_profile"]["review"]["decision"], "unreviewed")

        # Milestones
        for m in pkg["journey_milestones"]:
            self.assertEqual(m["review"]["status"], "unreviewed")
            self.assertEqual(m["review"]["decision"], "unreviewed")

        # Insights
        for ins in pkg["insights"]:
            self.assertEqual(ins["review"]["status"], "unreviewed")
            self.assertEqual(ins["review"]["decision"], "unreviewed")
            self.assertEqual(ins["review"]["evidential_support"], "unreviewed")
            self.assertEqual(ins["review"]["clarity"], "unreviewed")
            self.assertEqual(ins["review"]["practical_usefulness"], "unreviewed")

        # Quotations
        for q in pkg["quotations"]:
            self.assertEqual(q["review"]["status"], "unreviewed")
            self.assertEqual(q["review"]["decision"], "unreviewed")

        # Tags
        self.assertEqual(pkg["suggested_tags"]["review"]["status"], "unreviewed")

    def test_10_malformed_json_and_schema_violations_fail_clearly(self) -> None:
        """Requirement 10: Malformed JSON and missing files fail clearly without crashing."""
        malformed_path = os.path.join(self.temp_dir.name, "malformed.json")
        with open(malformed_path, "w", encoding="utf-8") as f:
            f.write("{invalid: json syntax, missing quotes")

        result = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path=malformed_path,
            output_path=self.output_path,
            reconstruct_rolling=False,
        )
        self.assertEqual(result.status, "validation_failed")
        self.assertEqual(result.exit_code, 1)
        self.assertFalse(result.report["automated_validation"]["schema_valid"])
        has_malformed = any(
            e.get("error_code") == "MALFORMED_JSON"
            for e in result.report["automated_validation"]["errors"]
        )
        self.assertTrue(has_malformed)

        # Missing file test
        result_missing = self.preparer.prepare_review(
            transcript_path=self.transcript_path,
            candidate_staging_path="non_existent_candidate_file_xyz.json",
            output_path=self.output_path,
            reconstruct_rolling=False,
        )
        self.assertEqual(result_missing.status, "error")
        self.assertEqual(result_missing.exit_code, 2)


if __name__ == "__main__":
    unittest.main()
