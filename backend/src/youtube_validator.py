"""
Meri Content Pipeline v1: YouTube URL validation and 11-character video ID extraction.
Ensures deterministic deduplication against episodes.youtube_video_id UNIQUE constraint.
"""

import re
from urllib.parse import parse_qs, urlparse

from .models import InvalidYouTubeUrlError

# Canonical set of authorized YouTube hostnames
_AUTHORIZED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

# Strict 11-character YouTube video ID format (Base64URL characters: A-Z, a-z, 0-9, -, _)
_VIDEO_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def validate_and_extract_youtube_video_id(url: str) -> str:
    """
    Validates that a URL points to an authentic YouTube recording and extracts
    the canonical 11-character YouTube Video ID.

    Supported URL patterns:
    - Standard watch: https://www.youtube.com/watch?v=dQw4w9WgXcQ
    - Shortened:      https://youtu.be/dQw4w9WgXcQ
    - Embed:          https://www.youtube.com/embed/dQw4w9WgXcQ
    - Shorts:         https://www.youtube.com/shorts/dQw4w9WgXcQ
    - Legacy /v/:     https://www.youtube.com/v/dQw4w9WgXcQ
    - With timestamps: https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1420s

    Raises InvalidYouTubeUrlError if the URL is empty, non-YouTube, malformed,
    or the extracted video ID does not strictly match the 11-character specification.
    """
    if not url or not isinstance(url, str):
        raise InvalidYouTubeUrlError("YouTube URL must be a non-empty string.")

    trimmed = url.strip()
    if not trimmed:
        raise InvalidYouTubeUrlError("YouTube URL cannot be blank.")

    try:
        parsed = urlparse(trimmed)
    except Exception as exc:
        raise InvalidYouTubeUrlError(f"Malformed URL string: {exc}") from exc

    if not parsed.scheme or parsed.scheme.lower() not in ("http", "https"):
        raise InvalidYouTubeUrlError(
            f"Invalid URL scheme '{parsed.scheme}'. YouTube URL must use http or https."
        )

    host = (parsed.hostname or "").lower()
    if host not in _AUTHORIZED_HOSTS:
        raise InvalidYouTubeUrlError(
            f"Unauthorized or unrecognized host '{host}'. Only verified YouTube domains are permitted."
        )

    candidate_id = ""

    # Pattern A: Short URL format (https://youtu.be/<video_id>)
    if host == "youtu.be":
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts:
            candidate_id = path_parts[0]

    # Pattern B: Query parameter (https://www.youtube.com/watch?v=<video_id>)
    elif "v" in parse_qs(parsed.query):
        v_values = parse_qs(parsed.query)["v"]
        if v_values and v_values[0]:
            candidate_id = v_values[0]

    # Pattern C: Path segment (https://www.youtube.com/embed/<id>, /shorts/<id>, /v/<id>)
    if not candidate_id and parsed.path:
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2 and path_parts[0] in ("embed", "shorts", "v"):
            candidate_id = path_parts[1]

    # Validate the candidate 11-char ID
    if not candidate_id:
        raise InvalidYouTubeUrlError(
            f"Could not extract a YouTube video ID from URL: '{trimmed}'"
        )

    if not _VIDEO_ID_REGEX.match(candidate_id):
        raise InvalidYouTubeUrlError(
            f"Extracted video ID '{candidate_id}' does not match standard 11-character "
            f"YouTube identifier requirements."
        )

    return candidate_id
