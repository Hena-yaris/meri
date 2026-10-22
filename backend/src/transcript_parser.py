"""
Meri Content Pipeline v1: Ingestion parser for JSON, SRT, and WebVTT transcript formats.
Preserves raw timestamps, speaker labels, and original Amharic text.
"""

import json
import re
from typing import Any, Dict, List, Optional, Union

from .models import InvalidTimestampError, MalformedCueError, RawCue

# SRT timecode regex: 00:01:23,456 --> 00:01:25,789
_SRT_TIMECODE_REGEX = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
)

# WebVTT timecode regex: 00:01:23.456 --> 00:01:25.789 or 01:23.456 --> 01:25.789
_VTT_TIMECODE_REGEX = re.compile(
    r"^\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})\.(\d{3})"
)

# WebVTT voice tag: <v Dawit Tadesse> or <v.narrator Dawit>
_VTT_VOICE_TAG_REGEX = re.compile(r"<\s*v(?:(?:\.[^>]+)|\s+([^>]+))>\s*")
# General HTML/formatting tags: <b>, </i>, <c.yellow>, etc.
_VTT_TAG_CLEANER = re.compile(r"</?[a-zA-Z0-9_.-]+(?:\s+[^>]*)?>")

# ASCII speaker prefix check: "Dawit: text" or "[Dawit] text"
# Crucial: uses standard ASCII colon ':' so Ethiopic word separator '፡' is never matched!
_SPEAKER_PREFIX_REGEX = re.compile(r"^\s*(?:\[([^\]]+)\]|([A-Za-z0-9_\s]{2,40}):)\s*(.*)$")


def parse_timecode_components_to_ms(hours: int, minutes: int, seconds: int, milliseconds: int) -> int:
    """Converts verified hours, minutes, seconds, milliseconds to total milliseconds."""
    if hours < 0 or minutes < 0 or seconds < 0 or milliseconds < 0:
        raise InvalidTimestampError(
            f"Negative timecode component encountered: {hours}:{minutes}:{seconds}.{milliseconds}"
        )
    if minutes >= 60:
        raise InvalidTimestampError(f"Minutes component out of range (>= 60): {minutes}")
    if seconds >= 60:
        raise InvalidTimestampError(f"Seconds component out of range (>= 60): {seconds}")
    if milliseconds >= 1000:
        raise InvalidTimestampError(f"Milliseconds component out of range (>= 1000): {milliseconds}")

    return (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds


def parse_timestamp_string_to_ms(ts: str) -> int:
    """
    Parses a single timestamp string (HH:MM:SS,mmm or HH:MM:SS.mmm or MM:SS.mmm or SS.mmm)
    into absolute milliseconds.
    """
    cleaned = ts.strip()
    m = re.match(r"^(?:(?:(\d{1,2}):)?(\d{1,2}):)?(\d{1,2})[,.](\d{3})$", cleaned)
    if not m:
        raise InvalidTimestampError(f"Unrecognized timecode format: '{ts}'")

    part1, part2, part3, ms_str = m.groups()
    if part1 is not None and part2 is not None:
        hours = int(part1)
        mins = int(part2)
        secs = int(part3)
    elif part2 is not None:
        hours = 0
        mins = int(part2)
        secs = int(part3)
    else:
        hours = 0
        mins = 0
        secs = int(part3)

    ms = int(ms_str)
    return parse_timecode_components_to_ms(hours, mins, secs, ms)


def _extract_speaker_and_text(raw_text: str, default_speaker: str = "Speaker") -> tuple[str, str]:
    """
    Extracts speaker label and text if prefixed with 'Speaker Name:' or '[Speaker Name]'.
    Ensures Amharic word separator '፡' is NOT interpreted as ASCII colon.
    """
    m = _SPEAKER_PREFIX_REGEX.match(raw_text)
    if m:
        bracketed, colon_prefixed, remaining = m.groups()
        speaker = (bracketed or colon_prefixed or "").strip()
        if speaker and len(speaker) <= 50:
            return speaker, remaining.strip()
    return default_speaker, raw_text.strip()


def parse_json_transcript(content: Union[str, Dict[str, Any], List[Any]]) -> List[RawCue]:
    """
    Parses a JSON transcript into a list of RawCue objects.
    Supports:
    - Official contract: {"format": "segments_json", "segments": [{"startMs": 0, "endMs": 14200, ...}]}
    - Snake case: {"segments": [{"start_ms": 0, "end_ms": 14200, ...}]}
    - Flat list: [{"startMs": 0, "endMs": 14200, "text": "..."}]
    """
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise MalformedCueError(f"Invalid JSON payload: {exc}") from exc
    else:
        data = content

    if isinstance(data, dict):
        if "segments" in data and isinstance(data["segments"], list):
            raw_list = data["segments"]
        else:
            raise MalformedCueError("JSON transcript dictionary must contain a 'segments' array.")
    elif isinstance(data, list):
        raw_list = data
    else:
        raise MalformedCueError("JSON transcript must be a dictionary or list of segment objects.")

    cues: List[RawCue] = []
    for idx, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise MalformedCueError(f"Segment at index {idx} is not an object: {type(item)}")

        # Support both camelCase and snake_case
        start_ms = item.get("startMs", item.get("start_ms"))
        end_ms = item.get("endMs", item.get("end_ms"))
        text = item.get("text", "")
        speaker = item.get("speakerLabel", item.get("speaker_label", item.get("speaker", "Speaker")))

        if start_ms is None or end_ms is None:
            raise MalformedCueError(
                f"Segment at index {idx} missing required startMs/endMs timestamps."
            )

        if not isinstance(start_ms, int) or not isinstance(end_ms, int):
            raise InvalidTimestampError(
                f"Segment at index {idx} has non-integer timestamps: start={start_ms}, end={end_ms}"
            )

        if start_ms < 0:
            raise InvalidTimestampError(
                f"Segment at index {idx} has negative startMs: {start_ms}"
            )

        if end_ms < start_ms:
            raise InvalidTimestampError(
                f"Segment at index {idx} has endMs ({end_ms}) earlier than startMs ({start_ms})"
            )

        if not text or not str(text).strip():
            raise MalformedCueError(f"Segment at index {idx} contains empty or missing text.")

        cues.append(
            RawCue(
                start_ms=start_ms,
                end_ms=end_ms,
                text=str(text).strip(),
                speaker_label=str(speaker).strip() or "Speaker",
                source_index=idx,
            )
        )

    return cues


def parse_srt_transcript(content: str) -> List[RawCue]:
    """
    Parses SubRip (.srt) subtitle content into a list of RawCue objects.
    Rejects malformed timecodes, negative timings, or inverted intervals.
    """
    if not content or not content.strip():
        raise MalformedCueError("SRT transcript content is empty.")

    # Normalize Windows/Mac line endings to \n
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    # Split blocks separated by two or more newlines
    blocks = re.split(r"\n\s*\n", normalized.strip())

    cues: List[RawCue] = []

    for block_idx, block in enumerate(blocks):
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if not lines:
            continue

        # Line 0 is typically sequence index, but could be timecode directly if index omitted
        timecode_line_idx = 0
        if not ("-->" in lines[0]) and len(lines) > 1 and "-->" in lines[1]:
            timecode_line_idx = 1

        timecode_line = lines[timecode_line_idx]
        m = _SRT_TIMECODE_REGEX.match(timecode_line)
        if not m:
            raise MalformedCueError(
                f"SRT block {block_idx + 1} has invalid timecode line: '{timecode_line}'"
            )

        sh, sm, ss, sms, eh, em, es, ems = m.groups()
        start_ms = parse_timecode_components_to_ms(int(sh), int(sm), int(ss), int(sms))
        end_ms = parse_timecode_components_to_ms(int(eh), int(em), int(es), int(ems))

        if end_ms < start_ms:
            raise InvalidTimestampError(
                f"SRT block {block_idx + 1} has end time ({end_ms}ms) earlier than start time ({start_ms}ms)."
            )

        text_lines = lines[timecode_line_idx + 1 :]
        if not text_lines:
            raise MalformedCueError(f"SRT block {block_idx + 1} contains no subtitle text.")

        raw_text = " ".join(text_lines)
        speaker, text = _extract_speaker_and_text(raw_text)

        cues.append(
            RawCue(
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                speaker_label=speaker,
                source_index=block_idx,
            )
        )

    if not cues:
        raise MalformedCueError("SRT file did not contain any valid cues.")

    return cues


def parse_webvtt_transcript(content: str) -> List[RawCue]:
    """
    Parses WebVTT (.vtt) subtitle content into a list of RawCue objects.
    Extracts voice tags (<v Speaker>) and strips styling markup.
    """
    if not content or not content.strip():
        raise MalformedCueError("WebVTT transcript content is empty.")

    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized.startswith("WEBVTT"):
        raise MalformedCueError("WebVTT transcript must begin with 'WEBVTT' signature header.")

    blocks = re.split(r"\n\s*\n", normalized)
    cues: List[RawCue] = []

    for block_idx, block in enumerate(blocks):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        # Header block check (WEBVTT line or NOTE / STYLE / REGION blocks)
        first_line = lines[0].upper()
        if (
            first_line.startswith("WEBVTT")
            or first_line.startswith("NOTE")
            or first_line.startswith("STYLE")
            or first_line.startswith("REGION")
        ):
            # Check if this block also contains a timecode (rare in valid VTT, but handle if so)
            has_timecode = any("-->" in l for l in lines)
            if not has_timecode:
                continue

        # Locate timecode line
        timecode_line_idx = -1
        for idx, l in enumerate(lines):
            if "-->" in l:
                timecode_line_idx = idx
                break

        if timecode_line_idx == -1:
            # Metadata block without cue
            continue

        timecode_line = lines[timecode_line_idx]
        m = _VTT_TIMECODE_REGEX.match(timecode_line)
        if not m:
            raise MalformedCueError(
                f"WebVTT block {block_idx + 1} has invalid timecode format: '{timecode_line}'"
            )

        sh_str, sm_str, ss_str, sms_str, eh_str, em_str, es_str, ems_str = m.groups()
        sh = int(sh_str) if sh_str is not None else 0
        eh = int(eh_str) if eh_str is not None else 0

        start_ms = parse_timecode_components_to_ms(sh, int(sm_str), int(ss_str), int(sms_str))
        end_ms = parse_timecode_components_to_ms(eh, int(em_str), int(es_str), int(ems_str))

        if end_ms < start_ms:
            raise InvalidTimestampError(
                f"WebVTT block {block_idx + 1} has end time ({end_ms}ms) earlier than start time ({start_ms}ms)."
            )

        text_lines = lines[timecode_line_idx + 1 :]
        if not text_lines:
            raise MalformedCueError(f"WebVTT block {block_idx + 1} contains no cue payload.")

        raw_text = " ".join(text_lines)

        # Check for <v Speaker Name> voice tag
        speaker = "Speaker"
        voice_match = _VTT_VOICE_TAG_REGEX.search(raw_text)
        if voice_match:
            voice_val = voice_match.group(1) or ""
            if voice_val.strip():
                speaker = voice_val.strip()
            raw_text = _VTT_VOICE_TAG_REGEX.sub("", raw_text)

        # Strip remaining HTML tags
        cleaned_text = _VTT_TAG_CLEANER.sub("", raw_text).strip()

        # If no voice tag, check standard prefix
        if speaker == "Speaker":
            speaker, cleaned_text = _extract_speaker_and_text(cleaned_text)

        if not cleaned_text:
            raise MalformedCueError(f"WebVTT block {block_idx + 1} text is empty after tag cleanup.")

        cues.append(
            RawCue(
                start_ms=start_ms,
                end_ms=end_ms,
                text=cleaned_text,
                speaker_label=speaker,
                source_index=block_idx,
            )
        )

    if not cues:
        raise MalformedCueError("WebVTT document contains no cue blocks.")

    return cues


def parse_transcript(content: Union[str, Dict[str, Any], List[Any]], format_hint: Optional[str] = None) -> List[RawCue]:
    """
    Automatic dispatcher that parses JSON, SRT, or WebVTT content.
    """
    if isinstance(content, (dict, list)):
        return parse_json_transcript(content)

    if not isinstance(content, str):
        raise MalformedCueError(f"Unsupported content type: {type(content)}")

    trimmed = content.strip()
    hint = (format_hint or "").lower().strip()

    if hint == "json" or trimmed.startswith("{") or trimmed.startswith("["):
        return parse_json_transcript(trimmed)
    elif hint in ("vtt", "webvtt") or trimmed.startswith("WEBVTT"):
        return parse_webvtt_transcript(trimmed)
    elif hint == "srt":
        return parse_srt_transcript(trimmed)

    # Auto-detect between SRT and VTT if no hint provided
    if "WEBVTT" in trimmed[:50]:
        return parse_webvtt_transcript(trimmed)
    else:
        return parse_srt_transcript(trimmed)
