"""
Meri Content Pipeline v1: Transcript Normalization Engine.
Enforces stable monotonic segment indexing, Unicode NFC Amharic normalization,
conservative whitespace cleanup, and an explicit, non-silent overlap policy.
"""

import re
import unicodedata
from typing import List, Optional

from .models import (
    InvalidTimestampError,
    MalformedCueError,
    NormalizedSegment,
    OverlapPolicy,
    RawCue,
    TranscriptAcquisitionMethod,
    TranscriptOverlapError,
)

# Regex to collapse consecutive whitespace without touching Ethiopic wordspaces (U+1361 '፡')
_WHITESPACE_COLLAPSER = re.compile(r"[ \t\r\n\f\v]+")


def clean_amharic_text(text: str) -> str:
    """
    Normalizes transcript text to Unicode NFC and applies conservative whitespace cleanup.
    Preserves all authentic Amharic characters, fidel syllabics, and Ethiopic punctuation:
    - '፡' (U+1361 Ethiopic Wordspace)
    - '።' (U+1362 Ethiopic Full Stop)
    - '፣' (U+1363 Ethiopic Comma)
    - '፤' (U+1364 Ethiopic Semicolon)
    - '፦' (U+1365 Ethiopic Preface Colon)
    - '፧' (U+1367 Ethiopic Question Mark)
    """
    if not text:
        return ""

    # Canonical Unicode NFC normalization ensures composed Ethiopic glyphs
    normalized = unicodedata.normalize("NFC", text)

    # Collapse consecutive standard whitespace into a single ASCII space
    collapsed = _WHITESPACE_COLLAPSER.sub(" ", normalized).strip()

    return collapsed


class TranscriptNormalizer:
    """
    Normalizes raw transcript cues into strict database-compliant NormalizedSegment atoms.
    """

    def __init__(
        self,
        acquisition_method: TranscriptAcquisitionMethod = TranscriptAcquisitionMethod.MANUAL_UPLOAD,
        language_code: str = "am",
        overlap_policy: OverlapPolicy = OverlapPolicy.REJECT,
        default_speaker: str = "Speaker",
    ) -> None:
        self.acquisition_method = acquisition_method
        self.language_code = language_code
        self.overlap_policy = overlap_policy
        self.default_speaker = default_speaker

    def normalize(self, raw_cues: List[RawCue]) -> List[NormalizedSegment]:
        """
        Executes normalization on a list of RawCue objects:
        1. Validates cue bounds and timestamps.
        2. Applies stable ordering by (start_ms, end_ms, source_index).
        3. Detects and handles overlaps according to the declared OverlapPolicy.
        4. Cleans text with Unicode NFC and conservative whitespace cleanup.
        5. Assigns deterministic zero-based segment_index.
        6. Derives stored start_seconds = round(start_ms / 1000.0, 2).
        """
        if not raw_cues:
            raise MalformedCueError("Cannot normalize an empty list of transcript cues.")

        # Step 1: Pre-validation of individual cues
        validated_cues: List[RawCue] = []
        for idx, cue in enumerate(raw_cues):
            if cue.start_ms < 0:
                raise InvalidTimestampError(
                    f"Cue at index {idx} has negative start timestamp: {cue.start_ms}ms"
                )
            if cue.end_ms < cue.start_ms:
                raise InvalidTimestampError(
                    f"Cue at index {idx} has end_ms ({cue.end_ms}ms) earlier than start_ms ({cue.start_ms}ms)"
                )

            cleaned_text = clean_amharic_text(cue.text)
            if not cleaned_text:
                raise MalformedCueError(f"Cue at index {idx} contains only empty or whitespace text.")

            speaker = clean_amharic_text(cue.speaker_label) or self.default_speaker

            validated_cues.append(
                RawCue(
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    text=cleaned_text,
                    speaker_label=speaker,
                    source_index=cue.source_index if cue.source_index is not None else idx,
                    original_start_ms=cue.original_start_ms if cue.original_start_ms is not None else cue.start_ms,
                    original_end_ms=cue.original_end_ms if cue.original_end_ms is not None else cue.end_ms,
                )
            )

        # Step 2: Deterministic, stable ordering
        sorted_cues = sorted(
            validated_cues,
            key=lambda c: (c.start_ms, c.end_ms, c.source_index if c.source_index is not None else 0),
        )

        # Step 3: Overlap detection and policy application
        processed_cues: List[RawCue] = []
        for i, curr in enumerate(sorted_cues):
            if i > 0:
                prev = processed_cues[-1]
                if curr.start_ms < prev.end_ms:
                    # Overlap detected!
                    overlap_duration = prev.end_ms - curr.start_ms
                    if self.overlap_policy == OverlapPolicy.REJECT:
                        raise TranscriptOverlapError(
                            f"Transcript overlap of {overlap_duration}ms detected between cue "
                            f"[{prev.start_ms}ms - {prev.end_ms}ms: '{prev.text[:30]}...'] and cue "
                            f"[{curr.start_ms}ms - {curr.end_ms}ms: '{curr.text[:30]}...']. "
                            f"To permit source overlap, configure overlap_policy=OverlapPolicy.ALLOW."
                        )
                    elif self.overlap_policy == OverlapPolicy.CLAMP_PREVIOUS:
                        # Explicit truncation policy: clamp previous cue end_ms to current start_ms
                        clamped_end = curr.start_ms
                        if clamped_end < prev.start_ms:
                            clamped_end = prev.start_ms
                        processed_cues[-1] = RawCue(
                            start_ms=prev.start_ms,
                            end_ms=clamped_end,
                            text=prev.text,
                            speaker_label=prev.speaker_label,
                            source_index=prev.source_index,
                            original_start_ms=prev.original_start_ms,
                            original_end_ms=prev.original_end_ms,
                        )
                    elif self.overlap_policy == OverlapPolicy.ALLOW:
                        # Allow policy: preserve exact raw timestamps on both cues
                        pass

            processed_cues.append(curr)

        # Step 4: Construct NormalizedSegment instances with deterministic zero-based indices
        normalized_segments: List[NormalizedSegment] = []
        for segment_index, cue in enumerate(processed_cues):
            start_seconds = round(cue.start_ms / 1000.0, 2)
            normalized_segments.append(
                NormalizedSegment(
                    segment_index=segment_index,
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    start_seconds=start_seconds,
                    speaker_label=cue.speaker_label,
                    language_code=self.language_code,
                    acquisition_method=self.acquisition_method.value,
                    text=cue.text,
                    confidence=1.0 if self.acquisition_method == TranscriptAcquisitionMethod.MANUAL_UPLOAD else None,
                    original_start_ms=cue.original_start_ms,
                    original_end_ms=cue.original_end_ms,
                )
            )

        return normalized_segments
