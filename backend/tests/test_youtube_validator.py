"""
Unit tests for YouTube URL validation and 11-character video ID extraction.
"""

import unittest
from backend.src.models import InvalidYouTubeUrlError
from backend.src.youtube_validator import validate_and_extract_youtube_video_id


class TestYouTubeValidator(unittest.TestCase):
    """Positive and negative tests for validate_and_extract_youtube_video_id."""

    def test_positive_standard_watch_urls(self) -> None:
        """Validates standard watch?v= URLs with valid 11-char IDs."""
        test_cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://youtube.com/watch?v=sample101XY", "sample101XY"),
            ("https://m.youtube.com/watch?v=AbCd_Ef-Gh1", "AbCd_Ef-Gh1"),
            ("https://music.youtube.com/watch?v=12345678901", "12345678901"),
        ]
        for url, expected_id in test_cases:
            with self.subTest(url=url):
                video_id = validate_and_extract_youtube_video_id(url)
                self.assertEqual(video_id, expected_id)
                self.assertEqual(len(video_id), 11)

    def test_positive_shortened_and_embed_urls(self) -> None:
        """Validates youtu.be short links, embed, and shorts endpoints."""
        test_cases = [
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://youtu.be/sample101XY", "sample101XY"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ]
        for url, expected_id in test_cases:
            with self.subTest(url=url):
                video_id = validate_and_extract_youtube_video_id(url)
                self.assertEqual(video_id, expected_id)

    def test_positive_urls_with_query_parameters(self) -> None:
        """Ensures additional parameters (timestamp, playlist, feature) do not disrupt ID extraction."""
        test_cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1420s", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=sample101XY&feature=share&t=10s", "sample101XY"),
            ("https://youtu.be/dQw4w9WgXcQ?t=1420s", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1", "dQw4w9WgXcQ"),
        ]
        for url, expected_id in test_cases:
            with self.subTest(url=url):
                video_id = validate_and_extract_youtube_video_id(url)
                self.assertEqual(video_id, expected_id)

    def test_negative_invalid_domains(self) -> None:
        """Rejects non-YouTube domains and phishing mimics."""
        invalid_urls = [
            "https://vimeo.com/12345678901",
            "https://evil-youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.fakedomain.com/watch?v=dQw4w9WgXcQ",
            "https://dailymotion.com/video/x7tgad0",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(InvalidYouTubeUrlError):
                    validate_and_extract_youtube_video_id(url)

    def test_negative_malformed_or_empty_inputs(self) -> None:
        """Rejects null, empty, whitespace, or malformed inputs."""
        invalid_inputs = [
            "",
            "   ",
            None,
            12345,
            "not-a-url",
            "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
        ]
        for inp in invalid_inputs:
            with self.subTest(inp=inp):
                with self.assertRaises(InvalidYouTubeUrlError):
                    validate_and_extract_youtube_video_id(inp)  # type: ignore

    def test_negative_invalid_video_id_length_and_characters(self) -> None:
        """Rejects video IDs that are not strictly 11 characters or have invalid symbols."""
        invalid_ids = [
            "https://www.youtube.com/watch?v=short",  # 5 chars
            "https://www.youtube.com/watch?v=toolongvideoidentifier123",  # 26 chars
            "https://www.youtube.com/watch?v=dQw4w9WgXc!",  # invalid symbol '!'
            "https://www.youtube.com/watch?v=dQw4w9WgXc@",  # invalid symbol '@'
            "https://www.youtube.com/watch?v=dQw4w9 WgXcQ",  # contains space
            "https://www.youtube.com/watch",  # missing 'v' parameter
            "https://youtu.be/",  # missing path ID
        ]
        for url in invalid_ids:
            with self.subTest(url=url):
                with self.assertRaises(InvalidYouTubeUrlError):
                    validate_and_extract_youtube_video_id(url)


if __name__ == "__main__":
    unittest.main()
