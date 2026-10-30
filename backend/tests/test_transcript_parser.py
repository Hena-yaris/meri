"""
Unit tests for multi-format transcript parsing (JSON, SRT, WebVTT).
"""

from pathlib import Path
import unittest

from backend.src.models import InvalidTimestampError, MalformedCueError
from backend.src.transcript_parser import (
    parse_json_transcript,
    parse_srt_transcript,
    parse_timestamp_string_to_ms,
    parse_transcript,
    parse_webvtt_transcript,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestTranscriptParser(unittest.TestCase):
    """Positive and negative tests for JSON, SRT, and WebVTT parsers."""

    def test_positive_parse_timestamp_strings(self) -> None:
        """Verifies accurate conversion of timecode strings to milliseconds."""
        test_cases = [
            ("00:00:00,000", 0),
            ("00:00:14,200", 14200),
            ("00:01:14,200", 74200),
            ("01:14:02,500", 4442500),
            ("00:00:14.200", 14200),  # WebVTT period format
            ("14.200", 14200),         # MM:SS.mmm format without hours
            ("01:14.200", 74200),      # MM:SS.mmm
        ]
        for ts_str, expected_ms in test_cases:
            with self.subTest(ts_str=ts_str):
                ms = parse_timestamp_string_to_ms(ts_str)
                self.assertEqual(ms, expected_ms)

    def test_positive_parse_json_fixture(self) -> None:
        """Parses the authentic Amharic JSON fixture matching schema contract."""
        json_path = FIXTURES_DIR / "sample_transcript.json"
        content = json_path.read_text(encoding="utf-8")
        cues = parse_json_transcript(content)

        self.assertEqual(len(cues), 4)
        first = cues[0]
        self.assertEqual(first.start_ms, 0)
        self.assertEqual(first.end_ms, 14200)
        self.assertEqual(first.speaker_label, "Dawit Tadesse")
        self.assertIn("የቀዝቃዛ ሰንሰለት", first.text)

        second = cues[1]
        self.assertEqual(second.start_ms, 14201)
        self.assertEqual(second.end_ms, 35000)
        self.assertIn("የሎጂስቲክስ ስራ", second.text)

    def test_positive_parse_srt_fixture(self) -> None:
        """Parses the sample SRT fixture with speaker prefix extraction."""
        srt_path = FIXTURES_DIR / "sample_transcript.srt"
        content = srt_path.read_text(encoding="utf-8")
        cues = parse_srt_transcript(content)

        self.assertEqual(len(cues), 4)
        first = cues[0]
        self.assertEqual(first.start_ms, 0)
        self.assertEqual(first.end_ms, 14200)
        self.assertEqual(first.speaker_label, "Dawit Tadesse")
        self.assertIn("የቀዝቃዛ ሰንሰለት ሎጂስቲክስ", first.text)

        third = cues[2]
        self.assertEqual(third.speaker_label, "Host")
        self.assertIn("የገበሬዎችን ምርት", third.text)

    def test_positive_parse_webvtt_fixture(self) -> None:
        """Parses the sample WebVTT fixture with <v Speaker> voice tag extraction."""
        vtt_path = FIXTURES_DIR / "sample_transcript.vtt"
        content = vtt_path.read_text(encoding="utf-8")
        cues = parse_webvtt_transcript(content)

        self.assertEqual(len(cues), 4)
        first = cues[0]
        self.assertEqual(first.start_ms, 0)
        self.assertEqual(first.end_ms, 14200)
        self.assertEqual(first.speaker_label, "Dawit Tadesse")
        # Ensure voice tags and HTML tags were stripped cleanly
        self.assertNotIn("<v", first.text)
        self.assertNotIn("</v>", first.text)
        self.assertIn("የቀዝቃዛ ሰንሰለት ሎጂስቲክስ", first.text)

    def test_positive_webvtt_ignores_metadata_and_cue_settings(self) -> None:
        """
        Verifies that WebVTT parsing cleanly ignores NOTE commentary, STYLE blocks,
        REGION blocks, cue identifiers, and trailing cue settings on the timecode line.
        """
        vtt_with_metadata = """WEBVTT - Interview Captions
Kind: captions
Language: am

NOTE This is editorial commentary
Spanning multiple lines of remarks.

STYLE
::cue {
  color: #FFFFFF;
}

REGION
id:fast
width:40%

cue-first-identifier
00:00:01.000 --> 00:00:10.000 line:90% position:50% align:center
<v Dawit Tadesse>የንግድ ስራ የመጀመሪያው እርምጃ።</v>

NOTE another comment between cues

cue-second-identifier
00:00:10.500 --> 00:00:20.000
የሁለተኛው ምዕራፍ ማጠቃለያ።
"""
        cues = parse_webvtt_transcript(vtt_with_metadata)
        self.assertEqual(len(cues), 2)

        first = cues[0]
        self.assertEqual(first.start_ms, 1000)
        self.assertEqual(first.end_ms, 10000)
        self.assertEqual(first.speaker_label, "Dawit Tadesse")
        self.assertEqual(first.text, "የንግድ ስራ የመጀመሪያው እርምጃ።")
        # Ensure metadata is NOT in cue text
        self.assertNotIn("NOTE", first.text)
        self.assertNotIn("STYLE", first.text)
        self.assertNotIn("REGION", first.text)
        self.assertNotIn("cue-first-identifier", first.text)
        self.assertNotIn("line:90%", first.text)

        second = cues[1]
        self.assertEqual(second.start_ms, 10500)
        self.assertEqual(second.end_ms, 20000)
        self.assertEqual(second.text, "የሁለተኛው ምዕራፍ ማጠቃለያ።")
        self.assertNotIn("cue-second-identifier", second.text)
        self.assertNotIn("NOTE", second.text)

    def test_positive_unified_dispatcher(self) -> None:
        """Tests parse_transcript dispatcher with auto-detection and explicit hints."""
        json_content = (FIXTURES_DIR / "sample_transcript.json").read_text(encoding="utf-8")
        srt_content = (FIXTURES_DIR / "sample_transcript.srt").read_text(encoding="utf-8")
        vtt_content = (FIXTURES_DIR / "sample_transcript.vtt").read_text(encoding="utf-8")

        self.assertEqual(len(parse_transcript(json_content)), 4)
        self.assertEqual(len(parse_transcript(srt_content)), 4)
        self.assertEqual(len(parse_transcript(vtt_content)), 4)
        self.assertEqual(len(parse_transcript(srt_content, format_hint="srt")), 4)

    def test_negative_inverted_timestamps(self) -> None:
        """Rejects files where end time is earlier than start time."""
        malformed_srt = (FIXTURES_DIR / "malformed_cues.srt").read_text(encoding="utf-8")
        with self.assertRaises(InvalidTimestampError) as ctx:
            parse_srt_transcript(malformed_srt)
        self.assertIn("earlier than start time", str(ctx.exception))

    def test_negative_json_timestamp_errors(self) -> None:
        """Rejects JSON cues with negative or inverted timestamps."""
        bad_negative = '{"segments": [{"startMs": -500, "endMs": 1000, "text": "test"}]}'
        with self.assertRaises(InvalidTimestampError):
            parse_json_transcript(bad_negative)

        bad_inverted = '{"segments": [{"startMs": 5000, "endMs": 2000, "text": "test"}]}'
        with self.assertRaises(InvalidTimestampError):
            parse_json_transcript(bad_inverted)

        bad_missing = '{"segments": [{"text": "missing timestamps"}]}'
        with self.assertRaises(MalformedCueError):
            parse_json_transcript(bad_missing)

    def test_negative_invalid_timecode_components(self) -> None:
        """Rejects timecodes with out-of-range seconds or minutes."""
        with self.assertRaises(InvalidTimestampError):
            parse_timestamp_string_to_ms("00:75:00,000")  # 75 minutes
        with self.assertRaises(InvalidTimestampError):
            parse_timestamp_string_to_ms("00:00:85,000")  # 85 seconds

    def test_negative_webvtt_missing_header(self) -> None:
        """Rejects WebVTT files lacking the mandatory 'WEBVTT' signature."""
        invalid_vtt = "00:00:00.000 --> 00:00:05.000\nNo header here"
        with self.assertRaises(MalformedCueError) as ctx:
            parse_webvtt_transcript(invalid_vtt)
        self.assertIn("WEBVTT", str(ctx.exception))


    def test_positive_youtube_webvtt_inline_timestamps_and_formatting_tags(self) -> None:
        """Verifies parsing of YouTube auto-generated WebVTT with inline timestamps, <c> tags, and &gt;&gt;."""
        yt_vtt = (
            "WEBVTT\n"
            "Kind: captions\n"
            "Language: am\n"
            "\n"
            "00:00:00.120 --> 00:00:03.709 align:start position:0%\n"
            " \n"
            "የንግድ<00:00:00.480><c> ስራ</c><00:00:00.960><c> የመጀመሪያው</c><00:00:01.439><c> እርምጃ።</c>\n"
            "\n"
            "00:00:03.709 --> 00:00:03.719 align:start position:0%\n"
            "የንግድ ስራ የመጀመሪያው እርምጃ።\n"
            " \n"
            "\n"
            "00:00:03.719 --> 00:00:06.630 align:start position:0%\n"
            "የንግድ ስራ የመጀመሪያው እርምጃ።\n"
            "&gt;&gt; ሁለተኛው<00:00:04.200><c> ምዕራፍ</c><00:00:04.800><c> ተጀመረ።</c>\n"
        )
        cues = parse_webvtt_transcript(yt_vtt)
        self.assertEqual(len(cues), 3)

        # Cue 1: verify inline timestamps and <c> tags stripped, Amharic text and punctuation preserved
        c1 = cues[0]
        self.assertEqual(c1.start_ms, 120)
        self.assertEqual(c1.end_ms, 3709)
        self.assertEqual(c1.text, "የንግድ ስራ የመጀመሪያው እርምጃ።")
        self.assertNotIn("<", c1.text)
        self.assertNotIn(">", c1.text)

        # Cue 2: intermediate snapshot cue preserved with exact timing
        c2 = cues[1]
        self.assertEqual(c2.start_ms, 3709)
        self.assertEqual(c2.end_ms, 3719)
        self.assertEqual(c2.text, "የንግድ ስራ የመጀመሪያው እርምጃ።")

        # Cue 3: &gt;&gt; unescaped to >>, tags stripped
        c3 = cues[2]
        self.assertEqual(c3.start_ms, 3719)
        self.assertEqual(c3.end_ms, 6630)
        self.assertIn(">>", c3.text)
        self.assertIn("ሁለተኛው ምዕራፍ ተጀመረ።", c3.text)
        self.assertNotIn("&gt;", c3.text)
        self.assertNotIn("<c>", c3.text)

    def test_positive_youtube_webvtt_skips_empty_and_formatting_only_cues(self) -> None:
        """Verifies that cues containing only whitespace or empty formatting tags are safely skipped."""
        vtt_with_empty = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "የመጀመሪያው ቃል\n\n"
            "00:00:02.000 --> 00:00:02.010\n"
            " \n"
            " \n\n"
            "00:00:02.010 --> 00:00:03.000\n"
            "<c></c>\n\n"
            "00:00:03.000 --> 00:00:04.000\n"
            "የሁለተኛው ቃል\n"
        )
        cues = parse_webvtt_transcript(vtt_with_empty)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, "የመጀመሪያው ቃል")
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 2000)
        self.assertEqual(cues[1].text, "የሁለተኛው ቃል")
        self.assertEqual(cues[1].start_ms, 3000)
        self.assertEqual(cues[1].end_ms, 4000)

    def test_negative_webvtt_document_with_only_empty_cues_fails(self) -> None:
        """Verifies that a WebVTT file with zero non-empty cues raises MalformedCueError."""
        all_empty_vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            " \n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "<c></c>\n"
        )
        with self.assertRaises(MalformedCueError) as ctx:
            parse_webvtt_transcript(all_empty_vtt)
        self.assertIn("no cue blocks", str(ctx.exception))

    def test_negative_webvtt_malformed_timecode_line_rejected(self) -> None:
        """Verifies that WebVTT cues with malformed timecode syntax are rejected."""
        malformed_timecode_vtt = """WEBVTT

00:00:01.000 --> invalid_timecode
የሙከራ ጽሁፍ
"""
        with self.assertRaises(MalformedCueError) as ctx:
            parse_webvtt_transcript(malformed_timecode_vtt)
        self.assertIn("invalid timecode format", str(ctx.exception))

    def test_negative_webvtt_inverted_timecode_rejected(self) -> None:
        """Verifies that WebVTT cues with end time earlier than start time are rejected."""
        inverted_vtt = """WEBVTT

00:00:10.000 --> 00:00:05.000
የተሳሳተ የጊዜ ሰሌዳ
"""
        with self.assertRaises(InvalidTimestampError) as ctx:
            parse_webvtt_transcript(inverted_vtt)
        self.assertIn("earlier than start time", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
