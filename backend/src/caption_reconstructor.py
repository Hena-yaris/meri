"""
Meri Content Pipeline v1: Provenance-Preserving Rolling Caption Reconstruction Engine.

Addresses rolling caption snapshots (e.g. YouTube 2-line auto-captions) by reconstructing
discrete spoken utterances while preserving 100% source cue provenance, raw timestamps,
Amharic Unicode NFC normalization, and Ethiopic punctuation.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    MalformedCueError,
    NormalizedSegment,
    RawCue,
    ReconstructedSpeechSpan,
)
from .transcript_normalizer import clean_amharic_text


@dataclass(frozen=True)
class CaptionDiagnostics:
    """
    Structured aggregate diagnostics of a caption cue stream.
    Characterizes duration distributions, repetition patterns, and rolling display indicators
    without exposing raw transcript text.
    """
    total_cues: int
    duration_0_to_10_ms: int
    duration_11_to_100_ms: int
    duration_101_to_500_ms: int
    duration_over_500_ms: int
    identical_to_prev_count: int
    prefix_extension_count: int
    preceding_extends_current_count: int
    independent_cue_count: int
    is_rolling_display: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_cues": self.total_cues,
            "duration_distribution": {
                "0_10_ms": self.duration_0_to_10_ms,
                "11_100_ms": self.duration_11_to_100_ms,
                "101_500_ms": self.duration_101_to_500_ms,
                "over_500_ms": self.duration_over_500_ms,
            },
            "sequential_relationships": {
                "identical_to_preceding": self.identical_to_prev_count,
                "prefix_extension": self.prefix_extension_count,
                "preceding_extends_current": self.preceding_extends_current_count,
                "independent_cues": self.independent_cue_count,
            },
            "is_rolling_display": self.is_rolling_display,
        }


def diagnose_caption_stream(cues: List[RawCue], snapshot_threshold_ms: int = 50) -> CaptionDiagnostics:
    """
    Generates aggregate diagnostics for a list of RawCues without leaking transcript text.
    Classifies duration bins and sequential text relationships.
    """
    if not cues:
        return CaptionDiagnostics(
            total_cues=0,
            duration_0_to_10_ms=0,
            duration_11_to_100_ms=0,
            duration_101_to_500_ms=0,
            duration_over_500_ms=0,
            identical_to_prev_count=0,
            prefix_extension_count=0,
            preceding_extends_current_count=0,
            independent_cue_count=0,
            is_rolling_display=False,
        )

    dur_0_10 = 0
    dur_11_100 = 0
    dur_101_500 = 0
    dur_over_500 = 0

    identical_count = 0
    prefix_extension_count = 0
    preceding_extends_current_count = 0
    independent_count = 0

    for i, c in enumerate(cues):
        dur = c.end_ms - c.start_ms
        if dur <= 10:
            dur_0_10 += 1
        elif dur <= 100:
            dur_11_100 += 1
        elif dur <= 500:
            dur_101_500 += 1
        else:
            dur_over_500 += 1

        if i == 0:
            independent_count += 1
        else:
            prev = cues[i - 1]
            prev_txt = clean_amharic_text(prev.text)
            curr_txt = clean_amharic_text(c.text)

            if curr_txt == prev_txt:
                identical_count += 1
            elif curr_txt.startswith(prev_txt):
                prefix_extension_count += 1
            elif prev_txt.startswith(curr_txt):
                preceding_extends_current_count += 1
            else:
                independent_count += 1

    # Heuristic: A caption stream is a rolling display if > 25% of cues are <= 50ms snapshots
    # and > 25% of cues extend the preceding caption.
    is_rolling = (dur_0_10 / len(cues) > 0.25) and (prefix_extension_count / len(cues) > 0.25)

    return CaptionDiagnostics(
        total_cues=len(cues),
        duration_0_to_10_ms=dur_0_10,
        duration_11_to_100_ms=dur_11_100,
        duration_101_to_500_ms=dur_101_500,
        duration_over_500_ms=dur_over_500,
        identical_to_prev_count=identical_count,
        prefix_extension_count=prefix_extension_count,
        preceding_extends_current_count=preceding_extends_current_count,
        independent_cue_count=independent_count,
        is_rolling_display=is_rolling,
    )


class RollingCaptionReconstructor:
    """
    Reconstructs true spoken speech utterances from rolling-caption cues.
    Preserves traceable mapping from every emitted span to its source cues and intervals.
    Maintains Ethiopic punctuation and Unicode NFC normalization.
    Flags ambiguous relationships for human review without silent data loss.
    """

    def __init__(
        self,
        snapshot_threshold_ms: int = 50,
        speaker_turn_marker: str = ">>",
        default_speaker: str = "Speaker",
        language_code: str = "am",
        acquisition_method: str = "youtube_caption_auto",
        strip_turn_markers: bool = True,
        contiguous_threshold_ms: int = 500,
    ) -> None:
        self.snapshot_threshold_ms = snapshot_threshold_ms
        self.speaker_turn_marker = speaker_turn_marker
        self.default_speaker = default_speaker
        self.language_code = language_code
        self.acquisition_method = acquisition_method
        self.strip_turn_markers = strip_turn_markers
        self.contiguous_threshold_ms = contiguous_threshold_ms

    def _is_transition_snapshot(self, curr_text: str, prev_text: str) -> bool:
        """
        Conservative verification of visual display-transition snapshots.
        A short cue is treated as a transition snapshot ONLY if its text satisfies
        the established transition-pattern rules relative to the preceding span
        (exact match, turn marker equivalence, or suffix match from multi-line visual roll).
        """
        if not prev_text:
            return False

        c_clean = clean_amharic_text(curr_text)
        p_clean = clean_amharic_text(prev_text)

        if c_clean == p_clean:
            return True

        c_no_turn = clean_amharic_text(c_clean.replace(self.speaker_turn_marker, "").strip())
        p_no_turn = clean_amharic_text(p_clean.replace(self.speaker_turn_marker, "").strip())

        if c_no_turn == p_no_turn:
            return True

        # Suffix check: in 2-line rolling captions, Line 2 spoken in prev_span moves to Line 1 in snapshot
        if p_clean.endswith(c_clean) or p_no_turn.endswith(c_no_turn):
            return True

        return False

    def reconstruct(self, cues: List[RawCue]) -> List[ReconstructedSpeechSpan]:
        """
        Processes a list of RawCue objects into ReconstructedSpeechSpan utterances:
        1. Identifies transient snapshot cues (duration <= snapshot_threshold_ms) and verifies
           that their text and position strictly match the display transition pattern before absorption.
        2. Preserves non-transition short cues containing independent or ambiguous speech without loss.
        3. Detects prefix-extension cues, extracts newly spoken text, and attaches source cue provenance.
        4. Identifies and preserves speaker turn changes (e.g. '>>').
        5. Detects ambiguous partial overlaps and flags them for review without silent word drops.
        6. Preserves Unicode NFC normalization and all Ethiopic punctuation.
        """
        if not cues:
            return []

        # Ensure stable chronological ordering
        sorted_cues = sorted(
            cues,
            key=lambda c: (c.start_ms, c.end_ms, c.source_index if c.source_index is not None else 0),
        )

        spans: List[ReconstructedSpeechSpan] = []
        last_display_text = ""
        last_cue_end_ms = -1
        current_speaker = self.default_speaker
        span_index = 0

        for i, curr in enumerate(sorted_cues):
            cue_idx = curr.source_index if curr.source_index is not None else i
            dur = curr.end_ms - curr.start_ms
            curr_text = clean_amharic_text(curr.text)

            if not curr_text:
                continue

            # If there was a significant gap since the last cue, the rolling display buffer was cleared
            is_contiguous = (last_cue_end_ms >= 0) and (curr.start_ms <= last_cue_end_ms + self.contiguous_threshold_ms)
            if not is_contiguous:
                last_display_text = ""

            # Case A: Visual transition snapshot (verified duration, contiguity, AND text relationship)
            is_snapshot = False
            if dur <= self.snapshot_threshold_ms and spans and is_contiguous:
                prev_span = spans[-1]
                if self._is_transition_snapshot(curr_text, prev_span.text) or (
                    last_display_text and self._is_transition_snapshot(curr_text, last_display_text)
                ):
                    is_snapshot = True

            if is_snapshot:
                # Associate this verified transition snapshot cue with the preceding span's provenance
                prev_span = spans[-1]
                updated_indices = list(prev_span.source_cue_indices)
                if cue_idx not in updated_indices:
                    updated_indices.append(cue_idx)
                updated_intervals = list(prev_span.source_intervals)
                updated_intervals.append((curr.start_ms, curr.end_ms))

                spans[-1] = ReconstructedSpeechSpan(
                    span_index=prev_span.span_index,
                    start_ms=prev_span.start_ms,
                    end_ms=max(prev_span.end_ms, curr.end_ms),
                    start_seconds=prev_span.start_seconds,
                    text=prev_span.text,
                    speaker_label=prev_span.speaker_label,
                    source_cue_indices=updated_indices,
                    source_intervals=updated_intervals,
                    reconstruction_method=prev_span.reconstruction_method,
                    is_ambiguous=prev_span.is_ambiguous,
                    uncertainty_reason=prev_span.uncertainty_reason,
                    language_code=self.language_code,
                    acquisition_method=self.acquisition_method,
                    confidence=prev_span.confidence,
                )
                # Update display context: this snapshot now sits in the on-screen buffer
                last_display_text = curr_text
                last_cue_end_ms = curr.end_ms
                continue

            # Case B: Clean Prefix Extension
            # Cue text starts with the on-screen buffer from the previous cue / snapshot
            if is_contiguous and last_display_text and curr_text.startswith(last_display_text) and curr_text != last_display_text:
                new_text = curr_text[len(last_display_text):].strip()
                if new_text:
                    speaker = curr.speaker_label or current_speaker
                    if self.speaker_turn_marker in new_text:
                        if self.strip_turn_markers:
                            cleaned_speaker_text = new_text.replace(self.speaker_turn_marker, "").strip()
                            new_text = clean_amharic_text(cleaned_speaker_text)
                            speaker = "Speaker Turn"

                    span = ReconstructedSpeechSpan(
                        span_index=span_index,
                        start_ms=curr.start_ms,
                        end_ms=curr.end_ms,
                        start_seconds=round(curr.start_ms / 1000.0, 2),
                        text=clean_amharic_text(new_text),
                        speaker_label=speaker,
                        source_cue_indices=[cue_idx],
                        source_intervals=[(curr.start_ms, curr.end_ms)],
                        reconstruction_method="prefix_subtraction",
                        is_ambiguous=False,
                        uncertainty_reason=None,
                        language_code=self.language_code,
                        acquisition_method=self.acquisition_method,
                        confidence=1.0,
                    )
                    spans.append(span)
                    span_index += 1
                    last_display_text = clean_amharic_text(new_text)
                    last_cue_end_ms = curr.end_ms
                    continue

            # Case C: Ambiguous Partial Word/Phrase Overlap Check
            is_ambiguous = False
            uncertainty_reason = None
            if is_contiguous and last_display_text and curr_text != last_display_text:
                prev_words = last_display_text.split()
                curr_words = curr_text.split()
                max_check = min(len(prev_words), len(curr_words))
                overlap_words = 0
                for k in range(max_check, 0, -1):
                    if prev_words[-k:] == curr_words[:k]:
                        overlap_words = k
                        break

                if overlap_words > 0 and overlap_words < len(curr_words):
                    is_ambiguous = True
                    uncertainty_reason = f"partial_overlap_{overlap_words}_words_unresolved"

            # Case D: Independent Utterance or Non-Transition Short Cue
            reconstruction_method = "independent"
            if dur <= self.snapshot_threshold_ms:
                if is_ambiguous:
                    reconstruction_method = "short_cue_ambiguous"
                else:
                    reconstruction_method = "short_cue_independent"
            elif is_ambiguous:
                reconstruction_method = "conservative_ambiguous"

            speaker = curr.speaker_label or current_speaker
            emit_text = curr_text
            if self.speaker_turn_marker in emit_text and self.strip_turn_markers:
                emit_text = clean_amharic_text(emit_text.replace(self.speaker_turn_marker, "").strip())
                speaker = "Speaker Turn"

            span = ReconstructedSpeechSpan(
                span_index=span_index,
                start_ms=curr.start_ms,
                end_ms=curr.end_ms,
                start_seconds=round(curr.start_ms / 1000.0, 2),
                text=emit_text,
                speaker_label=speaker,
                source_cue_indices=[cue_idx],
                source_intervals=[(curr.start_ms, curr.end_ms)],
                reconstruction_method=reconstruction_method,
                is_ambiguous=is_ambiguous,
                uncertainty_reason=uncertainty_reason,
                language_code=self.language_code,
                acquisition_method=self.acquisition_method,
                confidence=1.0 if not is_ambiguous else 0.5,
            )
            spans.append(span)
            span_index += 1
            last_display_text = curr_text
            last_cue_end_ms = curr.end_ms

        return spans

    def reconstruct_to_segments(self, cues: List[RawCue]) -> List[NormalizedSegment]:
        """
        Reconstructs the cue stream and converts each speech span into a NormalizedSegment atom.
        """
        spans = self.reconstruct(cues)
        return [span.to_normalized_segment() for span in spans]
