"""
Unit tests for RollingCaptionReconstructor and CaptionDiagnostics.

Milestone 7.4 Test Suite:
1. Synthetic caption text growing across successive cues (prefix extension).
2. Repeated word genuinely spoken twice (within and across utterances).
3. Two legitimate identical sentences spoken at different times.
4. Caption that changes speaker with turn marker '>>'.
5. 10 ms visual transition snapshot.
6. Partial phrase whose relationship to the next cue is ambiguous.
7. Amharic text with Ethiopic punctuation and Unicode NFC preservation.
8. Complete provenance mapping from reconstructed spans back to source cues.
9. Caption stream diagnostics calculation without text exposure.
"""

import unicodedata
import unittest

from backend.src.caption_reconstructor import (
    CaptionDiagnostics,
    RollingCaptionReconstructor,
    diagnose_caption_stream,
)
from backend.src.models import NormalizedSegment, RawCue, ReconstructedSpeechSpan


class TestCaptionReconstructor(unittest.TestCase):
    """Synthetic fixture tests for rolling caption reconstruction and provenance tracking."""

    def setUp(self) -> None:
        self.reconstructor = RollingCaptionReconstructor()

    # 1. A caption whose text grows across successive cues
    def test_caption_text_grows_across_successive_cues(self) -> None:
        """
        Verifies that when caption text accumulates across 2-line rolling cues,
        the static prefix is cleanly subtracted and newly spoken words are emitted as discrete spans.
        """
        cues = [
            RawCue(start_ms=1000, end_ms=3000, text="የቀዝቃዛ ሰንሰለት", source_index=0),
            RawCue(start_ms=3000, end_ms=3010, text="የቀዝቃዛ ሰንሰለት", source_index=1),  # 10ms snapshot
            RawCue(start_ms=3010, end_ms=5500, text="የቀዝቃዛ ሰንሰለት ሎጂስቲክስ ስራ", source_index=2),
            RawCue(start_ms=5500, end_ms=5510, text="ሎጂስቲክስ ስራ", source_index=3),  # 10ms snapshot
            RawCue(start_ms=5510, end_ms=8000, text="ሎጂስቲክስ ስራ ትልቅ ፈተና ነው።", source_index=4),
        ]

        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 3)

        # Span 0: Opening utterance
        self.assertEqual(spans[0].span_index, 0)
        self.assertEqual(spans[0].text, "የቀዝቃዛ ሰንሰለት")
        self.assertEqual(spans[0].start_ms, 1000)
        self.assertEqual(spans[0].end_ms, 3010)
        self.assertEqual(spans[0].source_cue_indices, [0, 1])
        self.assertEqual(spans[0].reconstruction_method, "independent")

        # Span 1: First extension (prefix 'የቀዝቃዛ ሰንሰለት' removed)
        self.assertEqual(spans[1].span_index, 1)
        self.assertEqual(spans[1].text, "ሎጂስቲክስ ስራ")
        self.assertEqual(spans[1].start_ms, 3010)
        self.assertEqual(spans[1].end_ms, 5510)
        self.assertEqual(spans[1].source_cue_indices, [2, 3])
        self.assertEqual(spans[1].reconstruction_method, "prefix_subtraction")

        # Span 2: Second extension (prefix 'ሎጂስቲክስ ስራ' removed)
        self.assertEqual(spans[2].span_index, 2)
        self.assertEqual(spans[2].text, "ትልቅ ፈተና ነው።")
        self.assertEqual(spans[2].start_ms, 5510)
        self.assertEqual(spans[2].end_ms, 8000)
        self.assertEqual(spans[2].source_cue_indices, [4])
        self.assertEqual(spans[2].reconstruction_method, "prefix_subtraction")

    # 2. A repeated word that is genuinely spoken twice
    def test_repeated_word_genuinely_spoken_twice(self) -> None:
        """
        Verifies that repeated words genuinely spoken by a speaker are never stripped:
        - Internal repetition within a sentence ("በጣም በጣም")
        - Repetition across distinct sequential utterances
        """
        # Internal word repetition
        cues_internal = [
            RawCue(start_ms=1000, end_ms=4000, text="ይህ በጣም በጣም ጠቃሚ ሀሳብ ነው።", source_index=0),
        ]
        spans_internal = self.reconstructor.reconstruct(cues_internal)
        self.assertEqual(len(spans_internal), 1)
        self.assertEqual(spans_internal[0].text, "ይህ በጣም በጣም ጠቃሚ ሀሳብ ነው።")
        self.assertEqual(spans_internal[0].text.count("በጣም"), 2)

        # Repetition across successive utterances with speech durations
        cues_cross = [
            RawCue(start_ms=1000, end_ms=2500, text="አዎ", source_index=0),
            RawCue(start_ms=2600, end_ms=4000, text="አዎ", source_index=1),
        ]
        spans_cross = self.reconstructor.reconstruct(cues_cross)
        self.assertEqual(len(spans_cross), 2)
        self.assertEqual(spans_cross[0].text, "አዎ")
        self.assertEqual(spans_cross[0].start_ms, 1000)
        self.assertEqual(spans_cross[1].text, "አዎ")
        self.assertEqual(spans_cross[1].start_ms, 2600)
        self.assertNotEqual(spans_cross[0].span_index, spans_cross[1].span_index)

    # 3. Two legitimate identical sentences spoken at different times
    def test_two_legitimate_identical_sentences_at_different_times(self) -> None:
        """
        Verifies that identical sentences spoken at different parts of an interview
        (e.g. at minute 1 and minute 30) are preserved as distinct segments.
        """
        cues = [
            RawCue(start_ms=10000, end_ms=13000, text="እንኳን ደህና መጣችሁ።", source_index=0),
            RawCue(start_ms=1800000, end_ms=1803000, text="እንኳን ደህና መጣችሁ።", source_index=1),
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0].text, "እንኳን ደህና መጣችሁ።")
        self.assertEqual(spans[0].start_ms, 10000)
        self.assertEqual(spans[1].text, "እንኳን ደህና መጣችሁ።")
        self.assertEqual(spans[1].start_ms, 1800000)
        self.assertEqual(spans[0].source_cue_indices, [0])
        self.assertEqual(spans[1].source_cue_indices, [1])

    # 4. A caption that changes speaker
    def test_caption_that_changes_speaker(self) -> None:
        """
        Verifies that '>>' speaker turn markers are recognized, cleanly extracted,
        and attributed without contaminating the verbatim spoken Amharic quote text.
        """
        cues = [
            RawCue(start_ms=1000, end_ms=3000, text="ጥያቄው ምንድን ነው?", speaker_label="Host", source_index=0),
            RawCue(start_ms=3000, end_ms=3010, text="ጥያቄው ምንድን ነው?", speaker_label="Host", source_index=1),
            RawCue(start_ms=3010, end_ms=6000, text="ጥያቄው ምንድን ነው? >> መልሱ ግልጽ ነው።", speaker_label="Host", source_index=2),
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 2)

        self.assertEqual(spans[0].text, "ጥያቄው ምንድን ነው?")
        self.assertEqual(spans[0].speaker_label, "Host")

        self.assertEqual(spans[1].text, "መልሱ ግልጽ ነው።")
        self.assertNotIn(">>", spans[1].text)
        self.assertEqual(spans[1].speaker_label, "Speaker Turn")
        self.assertEqual(spans[1].reconstruction_method, "prefix_subtraction")

    # 5. A 10 ms snapshot
    def test_10ms_transition_snapshot(self) -> None:
        """
        Verifies that isolated 10 ms transition cues are not emitted as spoken speech
        but are absorbed into the preceding span's interval and provenance.
        """
        cues = [
            RawCue(start_ms=2000, end_ms=4500, text="ይህ ዋና ንግግር ነው።", source_index=0),
            RawCue(start_ms=4500, end_ms=4510, text="ይህ ዋና ንግግር ነው።", source_index=1),  # 10ms snapshot
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].text, "ይህ ዋና ንግግር ነው።")
        self.assertEqual(spans[0].start_ms, 2000)
        self.assertEqual(spans[0].end_ms, 4510)
        self.assertIn(0, spans[0].source_cue_indices)
        self.assertIn(1, spans[0].source_cue_indices)

    # 6. A partial phrase whose relationship to the next cue is ambiguous
    def test_partial_phrase_ambiguous_relationship(self) -> None:
        """
        Verifies that when a cue does not form a clean prefix extension and has an ambiguous
        partial word overlap, it is conservatively emitted without word loss and flagged as ambiguous.
        """
        cues = [
            RawCue(start_ms=1000, end_ms=3000, text="የመጀመሪያው እርምጃ ወደፊት", source_index=0),
            RawCue(start_ms=3000, end_ms=3010, text="እርምጃ ወደፊት", source_index=1),  # 10ms buffer
            # Cue 2 does NOT start with 'እርምጃ ወደፊት'; it starts with 'ወደፊት' (partial overlap of 1 word)
            RawCue(start_ms=3010, end_ms=5500, text="ወደፊት በመሄድ ላይ ነን", source_index=2),
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 2)

        # First span
        self.assertEqual(spans[0].text, "የመጀመሪያው እርምጃ ወደፊት")
        self.assertFalse(spans[0].is_ambiguous)

        # Ambiguous second span: conservatively preserved in full, flagged for audit
        self.assertEqual(spans[1].text, "ወደፊት በመሄድ ላይ ነን")
        self.assertTrue(spans[1].is_ambiguous)
        self.assertIn("partial_overlap", spans[1].uncertainty_reason)
        self.assertEqual(spans[1].confidence, 0.5)

    # 7. Amharic text with Ethiopic punctuation
    def test_amharic_text_with_ethiopic_punctuation(self) -> None:
        """
        Verifies exact preservation of Unicode NFC Amharic text and Ethiopic punctuation marks:
        Wordspace '፡', Full Stop '።', Comma '፣', Semicolon '፤', Colon '፦', Question Mark '፧'.
        """
        text_with_ethiopic = "ሰላም፡ለእናንተ ይሁን። ይህ፤ ጥናት፧ የተሳካ፦ ነው፣"
        cues = [
            RawCue(start_ms=0, end_ms=3000, text=text_with_ethiopic, source_index=0),
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 1)

        result_text = spans[0].text
        self.assertIn("፡", result_text)  # U+1361 Wordspace
        self.assertIn("።", result_text)  # U+1362 Full stop
        self.assertIn("፣", result_text)  # U+1363 Comma
        self.assertIn("፤", result_text)  # U+1364 Semicolon
        self.assertIn("፦", result_text)  # U+1365 Preface colon
        self.assertIn("፧", result_text)  # U+1367 Question mark
        self.assertEqual(result_text, unicodedata.normalize("NFC", result_text))

    # 8. Provenance mapping from reconstructed spans back to source cues
    def test_provenance_mapping_complete_traceability(self) -> None:
        """
        Verifies that every reconstructed speech span retains a complete, unbroken
        audit trail back to the exact source cue indices and time intervals.
        """
        cues = [
            RawCue(start_ms=0, end_ms=2000, text="ክፍል አንድ", source_index=10),
            RawCue(start_ms=2000, end_ms=2010, text="ክፍል አንድ", source_index=11),
            RawCue(start_ms=2010, end_ms=4500, text="ክፍል አንድ ተጀመረ።", source_index=12),
        ]

        segments = self.reconstructor.reconstruct_to_segments(cues)
        self.assertEqual(len(segments), 2)

        # Check NormalizedSegment provenance properties
        seg0 = segments[0]
        self.assertEqual(seg0.segment_index, 0)
        self.assertEqual(seg0.text, "ክፍል አንድ")
        self.assertEqual(seg0.source_cue_indices, [10, 11])
        self.assertEqual(seg0.original_start_ms, 0)
        self.assertEqual(seg0.original_end_ms, 2010)

        seg1 = segments[1]
        self.assertEqual(seg1.segment_index, 1)
        self.assertEqual(seg1.text, "ተጀመረ።")
        self.assertEqual(seg1.source_cue_indices, [12])
        self.assertEqual(seg1.original_start_ms, 2010)
        self.assertEqual(seg1.original_end_ms, 4500)

        # Verify that all 3 raw cue indices are mapped
        all_source_indices = set(c.source_index for c in cues)
        covered_indices = set()
        for seg in segments:
            covered_indices.update(seg.source_cue_indices)
        self.assertEqual(all_source_indices, covered_indices)

    # 9. Caption diagnostics
    def test_diagnose_caption_stream(self) -> None:
        """
        Verifies aggregate diagnostics calculation without exposing raw transcript content.
        """
        cues = [
            RawCue(start_ms=0, end_ms=2000, text="ሰላም", source_index=0),       # > 500ms
            RawCue(start_ms=2000, end_ms=2010, text="ሰላም", source_index=1),    # 10ms snapshot (identical)
            RawCue(start_ms=2010, end_ms=4000, text="ሰላም ዓለም", source_index=2), # > 500ms (prefix extension)
            RawCue(start_ms=4000, end_ms=4050, text="አዲስ", source_index=3),     # 11-100ms
            RawCue(start_ms=4050, end_ms=4300, text="አዲስ ነገር", source_index=4), # 101-500ms
        ]

        diag = diagnose_caption_stream(cues)
        self.assertEqual(diag.total_cues, 5)
        self.assertEqual(diag.duration_0_to_10_ms, 1)
        self.assertEqual(diag.duration_11_to_100_ms, 1)
        self.assertEqual(diag.duration_101_to_500_ms, 1)
        self.assertEqual(diag.duration_over_500_ms, 2)
        self.assertEqual(diag.identical_to_prev_count, 1)
        self.assertEqual(diag.prefix_extension_count, 2)

        d_dict = diag.to_dict()
        self.assertIn("duration_distribution", d_dict)
        self.assertIn("sequential_relationships", d_dict)

    # 10. Independent meaningful short cue
    def test_independent_meaningful_short_cue(self) -> None:
        """
        Verifies that an independent short cue (duration <= 50ms) containing meaningful
        speech is NOT swallowed as a transition snapshot and is preserved as a discrete span.
        """
        cues = [
            RawCue(start_ms=1000, end_ms=1040, text="አዎ", source_index=0),  # 40ms independent speech
            RawCue(start_ms=1500, end_ms=4000, text="እቀጥላለሁ።", source_index=1),
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0].text, "አዎ")
        self.assertEqual(spans[0].start_ms, 1000)
        self.assertEqual(spans[0].end_ms, 1040)
        self.assertEqual(spans[0].source_cue_indices, [0])
        self.assertEqual(spans[0].reconstruction_method, "short_cue_independent")

    # 11. Short cue whose text differs from preceding display
    def test_short_cue_whose_text_differs_from_preceding_display(self) -> None:
        """
        Verifies that when a short cue (duration <= 50ms) arrives immediately following
        another span but contains DIFFERENT text, it is NOT absorbed into the preceding span.
        """
        cues = [
            RawCue(start_ms=1000, end_ms=3000, text="ጥያቄ አለኝ", source_index=0),
            RawCue(start_ms=3000, end_ms=3040, text="አዎ", source_index=1),  # 40ms, text differs from prev
            RawCue(start_ms=3040, end_ms=5000, text="አዎ መልስ አለኝ", source_index=2),
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 3)

        # Span 0: First question
        self.assertEqual(spans[0].text, "ጥያቄ አለኝ")
        self.assertEqual(spans[0].end_ms, 3000)

        # Span 1: Short cue preserved independently
        self.assertEqual(spans[1].text, "አዎ")
        self.assertEqual(spans[1].start_ms, 3000)
        self.assertEqual(spans[1].end_ms, 3040)
        self.assertEqual(spans[1].source_cue_indices, [1])

        # Span 2: Prefix 'አዎ' cleanly subtracted from Cue 2
        self.assertEqual(spans[2].text, "መልስ አለኝ")
        self.assertEqual(spans[2].start_ms, 3040)
        self.assertEqual(spans[2].end_ms, 5000)
        self.assertEqual(spans[2].source_cue_indices, [2])

    # 12. Ambiguous short cue
    def test_ambiguous_short_cue(self) -> None:
        """
        Verifies that an ambiguous short cue with unresolved partial word overlap
        is preserved without silent deletion and explicitly flagged for editorial review.
        """
        cues = [
            RawCue(start_ms=1000, end_ms=3000, text="አንድ ሁለት", source_index=0),
            RawCue(start_ms=3000, end_ms=3030, text="ሁለት አራት", source_index=1),  # 30ms, partial overlap
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[1].text, "ሁለት አራት")
        self.assertTrue(spans[1].is_ambiguous)
        self.assertEqual(spans[1].confidence, 0.5)
        self.assertEqual(spans[1].reconstruction_method, "short_cue_ambiguous")

    # 13. Preservation of all original cue IDs and source intervals
    def test_short_cue_preserves_all_cue_ids_and_intervals(self) -> None:
        """
        Verifies 100% complete audit trail for a sequence mixing genuine transition snapshots,
        independent short cues, and multi-line rolling expansions.
        """
        cues = [
            RawCue(start_ms=0, end_ms=2000, text="ንግግር ተጀመረ", source_index=101),
            RawCue(start_ms=2000, end_ms=2010, text="ንግግር ተጀመረ", source_index=102),  # 10ms transition
            RawCue(start_ms=2010, end_ms=4000, text="ንግግር ተጀመረ በሰላም", source_index=103),
            RawCue(start_ms=4000, end_ms=4030, text="አዎ", source_index=104),  # 30ms independent short cue
            RawCue(start_ms=4030, end_ms=6000, text="አዎ እናመሰግናለን።", source_index=105),
        ]
        spans = self.reconstructor.reconstruct(cues)
        self.assertEqual(len(spans), 4)

        # Every raw cue index must be present in source_cue_indices across spans
        all_raw_cues = {101, 102, 103, 104, 105}
        covered_cues = set()
        for s in spans:
            for idx in s.source_cue_indices:
                covered_cues.add(idx)
        self.assertEqual(all_raw_cues, covered_cues)

        # Every span must have valid source intervals
        for s in spans:
            self.assertGreater(len(s.source_intervals), 0)
            for sm, em in s.source_intervals:
                self.assertLessEqual(sm, em)


if __name__ == "__main__":
    unittest.main()
