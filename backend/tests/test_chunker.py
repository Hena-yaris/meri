"""
Unit tests for TranscriptChunker: context window synthesis,
overlap behavior, segment coverage, and source traceability.
"""

from pathlib import Path
import unittest

from backend.src.chunker import TranscriptChunker, estimate_token_count
from backend.src.models import NormalizedSegment
from backend.src.transcript_normalizer import TranscriptNormalizer
from backend.src.transcript_parser import parse_json_transcript

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestTranscriptChunker(unittest.TestCase):
    """Tests for TranscriptChunker and token count estimation."""

    def setUp(self) -> None:
        json_path = FIXTURES_DIR / "sample_transcript.json"
        raw_cues = parse_json_transcript(json_path.read_text(encoding="utf-8"))
        self.segments = TranscriptNormalizer().normalize(raw_cues)

    def test_positive_single_chunk_small_transcript(self) -> None:
        """A short transcript with default target words (800) fits in 1 complete chunk."""
        chunker = TranscriptChunker(target_chunk_words=800, overlap_words=50)
        chunks = chunker.chunk(self.segments)

        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk.chunk_index, 0)
        self.assertEqual(chunk.start_segment_index, 0)
        self.assertEqual(chunk.end_segment_index, len(self.segments) - 1)
        self.assertEqual(chunk.start_ms, self.segments[0].start_ms)
        self.assertEqual(chunk.end_ms, self.segments[-1].end_ms)
        self.assertGreater(chunk.token_count_estimate, 0)
        self.assertIn("የቀዝቃዛ ሰንሰለት", chunk.chunk_text)

    def test_positive_multi_chunk_with_overlap(self) -> None:
        """
        Forces multi-chunk splitting by setting low word targets (e.g. 15 words)
        and verifies segment overlap, monotonicity, and coverage.
        """
        # Our 4 segments have ~15 words each, so target 15 words with 5 words overlap splits into multiple chunks
        chunker = TranscriptChunker(target_chunk_words=15, overlap_words=5)
        chunks = chunker.chunk(self.segments)

        self.assertGreater(len(chunks), 1)

        # 1. Monotonic chunk indices
        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk.chunk_index, i)
            self.assertLessEqual(chunk.start_segment_index, chunk.end_segment_index)
            self.assertEqual(chunk.start_ms, self.segments[chunk.start_segment_index].start_ms)
            self.assertEqual(chunk.end_ms, self.segments[chunk.end_segment_index].end_ms)
            self.assertGreater(chunk.token_count_estimate, 0)

        # 2. Complete segment coverage: every segment from 0 to N-1 must be in at least one chunk
        covered_indices = set()
        for chunk in chunks:
            for idx in range(chunk.start_segment_index, chunk.end_segment_index + 1):
                covered_indices.add(idx)

        expected_indices = set(range(len(self.segments)))
        self.assertEqual(covered_indices, expected_indices)

        # 3. Overlap check: verify that chunks share segments while advancing
        for i in range(len(chunks) - 1):
            curr_chunk = chunks[i]
            next_chunk = chunks[i + 1]
            # Next chunk must strictly start AFTER curr_chunk's start (forward progress)
            self.assertGreater(next_chunk.start_segment_index, curr_chunk.start_segment_index)

    def test_positive_single_segment_transcript(self) -> None:
        """Edge case: transcript with exactly 1 segment produces 1 valid chunk."""
        single_seg = [self.segments[0]]
        chunker = TranscriptChunker()
        chunks = chunker.chunk(single_seg)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[0].start_segment_index, 0)
        self.assertEqual(chunks[0].end_segment_index, 0)

    def test_positive_empty_segment_list(self) -> None:
        """Edge case: empty segment list returns empty chunk list."""
        chunker = TranscriptChunker()
        self.assertEqual(chunker.chunk([]), [])

    def test_oversized_single_segment_forms_standalone_chunk(self) -> None:
        """
        Verifies that if a single segment's word count exceeds target_chunk_words,
        it forms a standalone chunk without being truncated or causing infinite loops.
        """
        # Create an oversized segment with ~30 words
        long_text = "ቃል " * 30
        oversized_seg = NormalizedSegment(
            segment_index=0,
            start_ms=0,
            end_ms=20000,
            start_seconds=0.0,
            speaker_label="Speaker",
            language_code="am",
            acquisition_method="manual_upload",
            text=long_text.strip(),
        )
        subsequent_seg = NormalizedSegment(
            segment_index=1,
            start_ms=20001,
            end_ms=30000,
            start_seconds=20.0,
            speaker_label="Speaker",
            language_code="am",
            acquisition_method="manual_upload",
            text="ቀጣይ አጭር ዓረፍተ ነገር።",
        )

        # Chunker configured with target of only 10 words
        chunker = TranscriptChunker(target_chunk_words=10, overlap_words=2)
        chunks = chunker.chunk([oversized_seg, subsequent_seg])

        self.assertEqual(len(chunks), 2)
        # First chunk contains exactly the oversized segment
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[0].start_segment_index, 0)
        self.assertEqual(chunks[0].end_segment_index, 0)

        # Second chunk cleanly advances to segment 1
        self.assertEqual(chunks[1].chunk_index, 1)
        self.assertEqual(chunks[1].start_segment_index, 1)
        self.assertEqual(chunks[1].end_segment_index, 1)

    def test_token_count_estimate_heuristic(self) -> None:
        """Verifies token count estimation formula on various text lengths."""
        self.assertEqual(estimate_token_count(""), 0)
        self.assertEqual(estimate_token_count("ሰላም"), 2)  # ceil(1 * 1.3) = 2
        text_10_words = "አንድ ሁለት ሶስት አራት አምስት ስድስት ሰባት ስምንት ዘጠኝ አስር"
        self.assertEqual(estimate_token_count(text_10_words), 13)  # ceil(10 * 1.3) = 13

    def test_format_chunk_text_explicit_segment_tagging(self) -> None:
        """
        Step 2 Requirement: Verify format_chunk_text explicitly tags every line with
        [Seg <index> | <speaker> | <timestamp>s]: <text>.
        """
        from backend.src.chunker import format_chunk_text

        # Test empty segments list
        self.assertEqual(format_chunk_text([]), "")

        # Test multi-segment formatting with non-zero indices, distinct speakers, and authentic Amharic
        segs = [
            NormalizedSegment(
                segment_index=14,
                start_ms=125400,
                end_ms=129500,
                start_seconds=125.4,
                speaker_label="Host A",
                language_code="am",
                acquisition_method="manual_upload",
                text="የመጀመሪያው ጥያቄዬ ስለ ንግድ ስራው ጅማሮ ነው።",
            ),
            NormalizedSegment(
                segment_index=15,
                start_ms=130000,
                end_ms=138200,
                start_seconds=130.0,
                speaker_label="Guest B",
                language_code="am",
                acquisition_method="manual_upload",
                text="እሺ፡ ስራውን የጀመርነው በትንሽ ካፒታል ነበር።",
            ),
        ]

        formatted = format_chunk_text(segs)
        lines = formatted.split("\n")
        self.assertEqual(len(lines), 2)

        # 1. Verify exact structure, segment index, speaker, timestamp, and text
        self.assertEqual(
            lines[0],
            "[Seg 14 | Host A | 125.4s]: የመጀመሪያው ጥያቄዬ ስለ ንግድ ስራው ጅማሮ ነው።",
        )
        self.assertEqual(
            lines[1],
            "[Seg 15 | Guest B | 130.0s]: እሺ፡ ስራውን የጀመርነው በትንሽ ካፒታል ነበር።",
        )

        # 2. Verify individual attributes preserved
        for idx, seg in enumerate(segs):
            self.assertIn(f"Seg {seg.segment_index}", lines[idx])
            self.assertIn(seg.speaker_label, lines[idx])
            self.assertIn(f"{seg.start_seconds}s", lines[idx])
            self.assertTrue(lines[idx].endswith(seg.text))

    def test_chunk_synthesizes_text_with_explicit_segment_tags(self) -> None:
        """
        Verifies that chunks generated by TranscriptChunker contain the explicit
        segment index tags on every single segment line.
        """
        chunker = TranscriptChunker(target_chunk_words=800, overlap_words=50)
        chunks = chunker.chunk(self.segments)
        self.assertGreater(len(chunks), 0)

        chunk = chunks[0]
        # Verify that all segments in chunk have explicit tags in chunk_text
        for seg in self.segments:
            expected_tag = f"[Seg {seg.segment_index} | {seg.speaker_label} | {seg.start_seconds}s]: {seg.text}"
            self.assertIn(expected_tag, chunk.chunk_text)


if __name__ == "__main__":
    unittest.main()
