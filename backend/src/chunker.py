"""
Meri Content Pipeline v1: Context window chunking engine.
Synthesizes contiguous segment ranges into semantic context windows with configurable
word limits and overlap while preserving 100% source segment traceability.
"""

import math
from typing import List, Optional

from .models import NormalizedSegment, TranscriptChunk


def estimate_token_count(text: str) -> int:
    """
    Estimates token count for Amharic and mixed Latin/Ethiopic text.
    Uses word-count heuristic: ceil(words * 1.3).
    Guarantees estimate > 0 for non-empty text.
    """
    if not text:
        return 0
    words = len(text.split())
    if words == 0:
        return 1
    return max(1, math.ceil(words * 1.3))


def format_chunk_text(segments: List[NormalizedSegment]) -> str:
    """
    Synthesizes segment texts into a coherent chunk representation with speaker attributions,
    explicit segment indices, and timestamps for LLM comprehension.
    Format: [Seg <segment_index> | <speaker_label> | <start_seconds>s]: <text>
    """
    lines: List[str] = []
    for seg in segments:
        lines.append(f"[Seg {seg.segment_index} | {seg.speaker_label} | {seg.start_seconds}s]: {seg.text}")
    return "\n".join(lines)



class TranscriptChunker:
    """
    Groups normalized transcript segments into overlapping context windows.
    Ensures that every segment is captured and that every chunk accurately
    tracks its exact start and end segment indices.
    """

    def __init__(
        self,
        target_chunk_words: int = 800,
        overlap_words: int = 150,
        min_chunk_segments: int = 1,
    ) -> None:
        if target_chunk_words <= 0:
            raise ValueError(f"target_chunk_words must be > 0, got {target_chunk_words}")
        if overlap_words < 0:
            raise ValueError(f"overlap_words must be >= 0, got {overlap_words}")
        if overlap_words >= target_chunk_words:
            raise ValueError(
                f"overlap_words ({overlap_words}) must be less than target_chunk_words ({target_chunk_words})"
            )

        self.target_chunk_words = target_chunk_words
        self.overlap_words = overlap_words
        self.min_chunk_segments = min_chunk_segments

    def chunk(self, segments: List[NormalizedSegment]) -> List[TranscriptChunk]:
        """
        Synthesizes a list of contiguous, monotonic NormalizedSegment records
        into TranscriptChunk context windows.

        Traceability Guarantees:
        1. chunk_index is strictly zero-based and sequential (0, 1, 2, ...).
        2. start_segment_index <= end_segment_index for all chunks.
        3. start_ms equals segments[start_segment_index].start_ms.
        4. end_ms equals segments[end_segment_index].end_ms.
        5. Every segment index in [0..len(segments)-1] appears in at least one chunk.
        6. Oversized Single Segments: If an individual segment's word count exceeds
           target_chunk_words, it is never split mid-segment or dropped; it forms a
           standalone chunk covering that single segment, and chunking advances forward.
        """
        if not segments:
            return []

        chunks: List[TranscriptChunk] = []
        num_segments = len(segments)
        current_start_idx = 0
        chunk_index = 0

        while current_start_idx < num_segments:
            # Build chunk starting from current_start_idx
            chunk_segments: List[NormalizedSegment] = []
            accumulated_words = 0
            end_idx = current_start_idx

            while end_idx < num_segments:
                seg = segments[end_idx]
                seg_words = len(seg.text.split())
                chunk_segments.append(seg)
                accumulated_words += seg_words
                end_idx += 1

                # If we have reached the word target and have enough segments, close chunk
                if (
                    accumulated_words >= self.target_chunk_words
                    and len(chunk_segments) >= self.min_chunk_segments
                ):
                    break

            # The slice included segments up to end_idx - 1
            last_segment_in_chunk_idx = end_idx - 1

            chunk_text = format_chunk_text(chunk_segments)
            token_estimate = estimate_token_count(chunk_text)

            chunk = TranscriptChunk(
                chunk_index=chunk_index,
                start_segment_index=segments[current_start_idx].segment_index,
                end_segment_index=segments[last_segment_in_chunk_idx].segment_index,
                start_ms=segments[current_start_idx].start_ms,
                end_ms=segments[last_segment_in_chunk_idx].end_ms,
                token_count_estimate=token_estimate,
                chunk_text=chunk_text,
            )
            chunks.append(chunk)
            chunk_index += 1

            # Termination check: if this chunk reached the final segment, we are finished
            if end_idx >= num_segments:
                break

            # Calculate next chunk's start index based on overlap
            # We want to overlap by approximately `self.overlap_words`, but we MUST
            # advance current_start_idx by at least 1 to prevent infinite loops.
            next_start_idx = last_segment_in_chunk_idx + 1  # Default: no overlap

            if self.overlap_words > 0:
                overlap_accum = 0
                candidate_idx = last_segment_in_chunk_idx
                # Walk backward to collect overlap segments
                while candidate_idx > current_start_idx:
                    overlap_accum += len(segments[candidate_idx].text.split())
                    if overlap_accum >= self.overlap_words:
                        next_start_idx = candidate_idx
                        break
                    candidate_idx -= 1
                else:
                    if candidate_idx > current_start_idx:
                        next_start_idx = candidate_idx

            # Safeguard: strictly ensure forward progress
            if next_start_idx <= current_start_idx:
                next_start_idx = current_start_idx + 1

            current_start_idx = next_start_idx

        return chunks
