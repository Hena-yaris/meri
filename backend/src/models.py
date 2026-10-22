"""
Meri Content Pipeline v1: Data models and exceptions for transcript ingestion.
Strictly conforms to Supabase PostgreSQL migration: 20261020000001_content_pipeline_foundation.sql
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class TranscriptAcquisitionMethod(str, Enum):
    """
    Method used to acquire source transcripts.
    Strictly matches PostgreSQL enum: transcript_acquisition_method.
    """
    YOUTUBE_CAPTION_MANUAL = "youtube_caption_manual"
    YOUTUBE_CAPTION_AUTO = "youtube_caption_auto"
    WHISPER_AUDIO = "whisper_audio"
    MANUAL_UPLOAD = "manual_upload"
    EXTERNAL_VENDOR = "external_vendor"


class OverlapPolicy(str, Enum):
    """
    Explicit policy governing how overlapping transcript cues are handled.
    - REJECT: Strict default. Fails validation with descriptive error if segments overlap.
    - ALLOW: Preserves original source timestamps without modification (legal in Postgres).
    - CLAMP_PREVIOUS: Explicitly truncates previous segment end_ms to current start_ms.
    """
    REJECT = "reject"
    ALLOW = "allow"
    CLAMP_PREVIOUS = "clamp_previous"


class TranscriptPipelineError(Exception):
    """Base exception for transcript ingestion pipeline errors."""
    pass


class InvalidYouTubeUrlError(TranscriptPipelineError):
    """Raised when a YouTube URL is malformed, from an unauthorized domain, or lacks an 11-char ID."""
    pass


class MalformedCueError(TranscriptPipelineError):
    """Raised when a transcript cue is structurally invalid or unparseable."""
    pass


class InvalidTimestampError(TranscriptPipelineError):
    """Raised when timestamps are negative, end time is earlier than start time, or timecodes fail parsing."""
    pass


class TranscriptOverlapError(TranscriptPipelineError):
    """Raised when overlapping cues are detected under OverlapPolicy.REJECT."""
    pass


@dataclass(frozen=True)
class RawCue:
    """
    An unnormalized transcript cue extracted directly from source JSON, SRT, or WebVTT.
    """
    start_ms: int
    end_ms: int
    text: str
    speaker_label: str = "Speaker"
    source_index: Optional[int] = None
    original_start_ms: Optional[int] = None
    original_end_ms: Optional[int] = None


@dataclass(frozen=True)
class NormalizedSegment:
    """
    Ground-truth transcript atom.
    Strictly conforms to PostgreSQL table: transcript_segments.
    """
    segment_index: int
    start_ms: int
    end_ms: int
    start_seconds: float
    speaker_label: str
    language_code: str
    acquisition_method: str
    text: str
    confidence: Optional[float] = None
    original_start_ms: Optional[int] = None
    original_end_ms: Optional[int] = None

    def __post_init__(self) -> None:
        if self.segment_index < 0:
            raise InvalidTimestampError(f"segment_index must be >= 0, got {self.segment_index}")
        if self.start_ms < 0:
            raise InvalidTimestampError(f"start_ms must be >= 0, got {self.start_ms}")
        if self.end_ms < self.start_ms:
            raise InvalidTimestampError(f"end_ms ({self.end_ms}) cannot be earlier than start_ms ({self.start_ms})")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")

    @property
    def is_clamped(self) -> bool:
        """Indicates whether this segment's timestamps were modified by an overlap policy."""
        return (
            (self.original_end_ms is not None and self.original_end_ms != self.end_ms)
            or (self.original_start_ms is not None and self.original_start_ms != self.start_ms)
        )

    def to_db_dict(
        self, episode_id: Optional[str] = None, include_generated: bool = False
    ) -> Dict[str, Any]:
        """
        Serializes the segment to a dictionary matching transcript_segments table schema.

        Args:
            episode_id: Optional UUID of parent episode.
            include_generated: If False (default for database INSERT operations), omits
                'start_seconds' because it is a PostgreSQL GENERATED ALWAYS column.
                If True, includes 'start_seconds' for read verification and contract tests.
        """
        payload: Dict[str, Any] = {
            "segment_index": self.segment_index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "speaker_label": self.speaker_label,
            "language_code": self.language_code,
            "acquisition_method": self.acquisition_method,
            "text": self.text,
            "confidence": self.confidence,
        }
        if include_generated:
            payload["start_seconds"] = self.start_seconds
        if episode_id is not None:
            payload["episode_id"] = episode_id
        return payload

    def to_insert_dict(self, episode_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Convenience helper producing an INSERT-safe dictionary with generated columns omitted.
        """
        return self.to_db_dict(episode_id=episode_id, include_generated=False)


@dataclass(frozen=True)
class TranscriptChunk:
    """
    Synthesized context window for AI extraction.
    Strictly conforms to PostgreSQL table: transcript_chunks.
    """
    chunk_index: int
    start_segment_index: int
    end_segment_index: int
    start_ms: int
    end_ms: int
    token_count_estimate: int
    chunk_text: str

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise ValueError(f"chunk_index must be >= 0, got {self.chunk_index}")
        if self.start_segment_index < 0:
            raise ValueError(f"start_segment_index must be >= 0, got {self.start_segment_index}")
        if self.end_segment_index < self.start_segment_index:
            raise ValueError(
                f"end_segment_index ({self.end_segment_index}) cannot be less than "
                f"start_segment_index ({self.start_segment_index})"
            )
        if self.start_ms < 0:
            raise InvalidTimestampError(f"start_ms must be >= 0, got {self.start_ms}")
        if self.end_ms < self.start_ms:
            raise InvalidTimestampError(f"end_ms ({self.end_ms}) cannot be less than start_ms ({self.start_ms})")
        if self.token_count_estimate <= 0:
            raise ValueError(f"token_count_estimate must be > 0, got {self.token_count_estimate}")

    def to_db_dict(self, episode_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Serializes the chunk to a dictionary matching transcript_chunks table schema.
        """
        payload: Dict[str, Any] = {
            "chunk_index": self.chunk_index,
            "start_segment_index": self.start_segment_index,
            "end_segment_index": self.end_segment_index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "token_count_estimate": self.token_count_estimate,
            "chunk_text": self.chunk_text,
        }
        if episode_id is not None:
            payload["episode_id"] = episode_id
        return payload
