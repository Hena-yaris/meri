"""
Unit tests for TranscriptNormalizer: Amharic Unicode preservation,
monotonic indexing, and explicit overlap policy enforcement.
"""

from pathlib import Path
import unicodedata
import unittest

from backend.src.models import (
    InvalidTimestampError,
    MalformedCueError,
    OverlapPolicy,
    RawCue,
    TranscriptAcquisitionMethod,
    TranscriptOverlapError,
)
from backend.src.transcript_normalizer import TranscriptNormalizer, clean_amharic_text
from backend.src.transcript_parser import parse_srt_transcript

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestTranscriptNormalizer(unittest.TestCase):
    """Tests for transcript cue normalization and text preservation."""

    def test_positive_normalization_flow(self) -> None:
        """Verifies full normalization into NormalizedSegment instances."""
        cues = [
            RawCue(start_ms=0, end_ms=14200, text="እንኳን ደህና መጣችሁ።", speaker_label="Dawit"),
            RawCue(start_ms=14201, end_ms=35000, text="የሎጂስቲክስ ስራ ትልቁ ፈተና...", speaker_label="Dawit"),
        ]

        normalizer = TranscriptNormalizer(
            acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD,
            language_code="am",
        )
        segments = normalizer.normalize(cues)

        self.assertEqual(len(segments), 2)

        # Monotonic segment index
        self.assertEqual(segments[0].segment_index, 0)
        self.assertEqual(segments[1].segment_index, 1)

        # Derived start_seconds
        self.assertEqual(segments[0].start_seconds, 0.0)
        self.assertEqual(segments[1].start_seconds, 14.20)

        # Columns
        self.assertEqual(segments[0].language_code, "am")
        self.assertEqual(segments[0].acquisition_method, "manual_upload")
        self.assertEqual(segments[0].confidence, 1.0)

    def test_positive_amharic_text_preservation(self) -> None:
        """Verifies Unicode NFC normalization and exact preservation of Ethiopic punctuation."""
        raw_text = "  ሰላም፡ለእናንተ\tይሁን።\n\nይህ   ምርመራ፤   የተሳካ፧   ነው፦   "
        cleaned = clean_amharic_text(raw_text)

        # Standard whitespace collapsed
        self.assertNotIn("\t", cleaned)
        self.assertNotIn("\n", cleaned)
        self.assertNotIn("   ", cleaned)

        # Ethiopic wordspace and punctuation preserved exactly
        self.assertIn("፡", cleaned)  # U+1361 Wordspace
        self.assertIn("።", cleaned)  # U+1362 Full stop
        self.assertIn("፤", cleaned)  # U+1364 Semicolon
        self.assertIn("፧", cleaned)  # U+1367 Question mark
        self.assertIn("፦", cleaned)  # U+1365 Preface colon

        # Unicode NFC verified
        self.assertEqual(cleaned, unicodedata.normalize("NFC", cleaned))

    def test_positive_stable_reordering_of_out_of_order_cues(self) -> None:
        """Ensures cues arriving out of order are stably sorted by (start_ms, end_ms)."""
        cues = [
            RawCue(start_ms=35000, end_ms=50000, text="ሶስተኛ ዓረፍተ ነገር", source_index=2),
            RawCue(start_ms=0, end_ms=15000, text="የመጀመሪያ ዓረፍተ ነገር", source_index=0),
            RawCue(start_ms=16000, end_ms=34000, text="ሁለተኛ ዓረፍተ ነገር", source_index=1),
        ]
        normalizer = TranscriptNormalizer()
        segments = normalizer.normalize(cues)

        self.assertEqual([s.segment_index for s in segments], [0, 1, 2])
        self.assertEqual(segments[0].start_ms, 0)
        self.assertEqual(segments[1].start_ms, 16000)
        self.assertEqual(segments[2].start_ms, 35000)

    def test_overlap_policy_reject_default(self) -> None:
        """Verifies that OverlapPolicy.REJECT is the default and detects collisions with descriptive errors."""
        default_normalizer = TranscriptNormalizer()
        self.assertEqual(default_normalizer.overlap_policy, OverlapPolicy.REJECT)

        overlap_srt = (FIXTURES_DIR / "overlapping_transcript.srt").read_text(encoding="utf-8")
        cues = parse_srt_transcript(overlap_srt)

        with self.assertRaises(TranscriptOverlapError) as ctx:
            default_normalizer.normalize(cues)

        self.assertIn("overlap of 2000ms detected", str(ctx.exception).lower())

    def test_overlap_policy_allow(self) -> None:
        """Verifies that OverlapPolicy.ALLOW preserves original source timestamps without modification."""
        overlap_srt = (FIXTURES_DIR / "overlapping_transcript.srt").read_text(encoding="utf-8")
        cues = parse_srt_transcript(overlap_srt)

        normalizer = TranscriptNormalizer(overlap_policy=OverlapPolicy.ALLOW)
        segments = normalizer.normalize(cues)

        self.assertEqual(len(segments), 2)
        # Original timestamps preserved
        self.assertEqual(segments[0].start_ms, 0)
        self.assertEqual(segments[0].end_ms, 10000)
        self.assertEqual(segments[1].start_ms, 8000)
        self.assertEqual(segments[1].end_ms, 18000)
        self.assertFalse(segments[0].is_clamped)
        self.assertFalse(segments[1].is_clamped)

    def test_overlap_policy_clamp_previous(self) -> None:
        """Verifies that OverlapPolicy.CLAMP_PREVIOUS explicitly truncates while preserving original timestamps."""
        overlap_srt = (FIXTURES_DIR / "overlapping_transcript.srt").read_text(encoding="utf-8")
        cues = parse_srt_transcript(overlap_srt)

        normalizer = TranscriptNormalizer(overlap_policy=OverlapPolicy.CLAMP_PREVIOUS)
        segments = normalizer.normalize(cues)

        self.assertEqual(len(segments), 2)
        # First segment end_ms clamped from 10000ms down to 8000ms (second segment start_ms)
        self.assertEqual(segments[0].start_ms, 0)
        self.assertEqual(segments[0].end_ms, 8000)
        # Original un-clamped timestamp remains accessible for auditing!
        self.assertEqual(segments[0].original_end_ms, 10000)
        self.assertTrue(segments[0].is_clamped)

        # Second segment was not clamped
        self.assertEqual(segments[1].start_ms, 8000)
        self.assertEqual(segments[1].end_ms, 18000)
        self.assertEqual(segments[1].original_end_ms, 18000)
        self.assertFalse(segments[1].is_clamped)

    def test_negative_empty_cue_list(self) -> None:
        """Rejects empty cue inputs."""
        normalizer = TranscriptNormalizer()
        with self.assertRaises(MalformedCueError):
            normalizer.normalize([])

    def test_negative_blank_text_cue(self) -> None:
        """Rejects cues containing only whitespace."""
        cues = [RawCue(start_ms=0, end_ms=1000, text="   ")]
        normalizer = TranscriptNormalizer()
        with self.assertRaises(MalformedCueError):
            normalizer.normalize(cues)


if __name__ == "__main__":
    unittest.main()
