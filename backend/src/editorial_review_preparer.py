"""
Meri Content Pipeline v1: Deterministic Editorial Review Preparation Engine.

Prepares human-reviewable editorial artifacts from local candidate staging JSON
and reconstructed transcripts without external API calls or database connections.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from .caption_reconstructor import RollingCaptionReconstructor
from .extraction_models import (
    ValidationErrorCode,
    ValidationErrorItem,
    ValidationSeverity,
)
from .models import NormalizedSegment
from .syntactic_validator import SyntacticValidator
from .transcript_normalizer import TranscriptNormalizer, clean_amharic_text
from .transcript_parser import parse_transcript

logger = logging.getLogger("meri.editorial_review_preparer")

DEFAULT_SPONSOR_RANGE = (15, 44)
CANONICAL_SCHEMA_VERSION = "1.0.0"
EDITORIAL_DISCLAIMER = (
    "FOR HUMAN EDITORIAL REVIEW ONLY. This document contains unapproved candidate "
    "extractions and automated validation signals. It does NOT constitute editorial "
    "approval, factual verification, speaker authentication, or authorization for publication."
)


@dataclass(frozen=True)
class EditorialReviewResult:
    """Outcome of editorial review preparation."""
    status: str  # "ready_for_human_review", "validation_failed", "error"
    report: Dict[str, Any]
    exit_code: int


class EditorialReviewPreparer:
    """
    Deterministic preparer of human editorial review packages from staged candidate JSON.
    """

    def __init__(
        self,
        syntactic_validator: Optional[SyntacticValidator] = None,
        sponsor_range: Tuple[int, int] = DEFAULT_SPONSOR_RANGE,
    ) -> None:
        self.syntactic_validator = syntactic_validator or SyntacticValidator()
        self.sponsor_range = sponsor_range

    def prepare_review(
        self,
        transcript_path: str,
        candidate_staging_path: str,
        output_path: Optional[str] = None,
        reconstruct_rolling: bool = True,
        format_hint: Optional[str] = None,
    ) -> EditorialReviewResult:
        """
        Executes end-to-end local review preparation.
        Validates candidate JSON, reconstructs transcript, grounds evidence, checks sponsor overlap,
        and outputs a structured human-review package.
        """
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        sponsor_flagged_items: List[Dict[str, Any]] = []

        # 1. Read & validate candidate staging JSON
        if not candidate_staging_path or not os.path.exists(candidate_staging_path):
            err_msg = f"Candidate staging file not found: {candidate_staging_path}"
            logger.error(err_msg)
            report = self._build_error_report(
                transcript_path=transcript_path,
                candidate_staging_path=candidate_staging_path,
                output_path=output_path,
                error_code="CANDIDATE_FILE_NOT_FOUND",
                message=err_msg,
            )
            self._write_output_if_requested(report, output_path)
            return EditorialReviewResult(status="error", report=report, exit_code=2)

        try:
            with open(candidate_staging_path, "r", encoding="utf-8") as f:
                raw_candidate_json = f.read()
        except Exception as exc:
            err_msg = f"Failed to read candidate staging file: {exc}"
            logger.error(err_msg)
            report = self._build_error_report(
                transcript_path=transcript_path,
                candidate_staging_path=candidate_staging_path,
                output_path=output_path,
                error_code="CANDIDATE_FILE_READ_ERROR",
                message=err_msg,
            )
            self._write_output_if_requested(report, output_path)
            return EditorialReviewResult(status="error", report=report, exit_code=2)

        # Layer 1 Syntactic Validation
        parsed_candidate_data, syntactic_errors = self.syntactic_validator.validate_raw_json(raw_candidate_json)
        for err in syntactic_errors:
            err_dict = self._error_item_to_dict(err)
            if err.severity == ValidationSeverity.ERROR:
                errors.append(err_dict)
            else:
                warnings.append(err_dict)

        if parsed_candidate_data is None:
            report = self._build_validation_failure_report(
                transcript_path=transcript_path,
                candidate_staging_path=candidate_staging_path,
                output_path=output_path,
                errors=errors,
                warnings=warnings,
                failure_reason="Candidate staging JSON is malformed or empty.",
            )
            self._write_output_if_requested(report, output_path)
            return EditorialReviewResult(status="validation_failed", report=report, exit_code=1)

        # 2. Read & Reconstruct Transcript
        if not transcript_path or not os.path.exists(transcript_path):
            err_msg = f"Transcript file not found: {transcript_path}"
            logger.error(err_msg)
            report = self._build_error_report(
                transcript_path=transcript_path,
                candidate_staging_path=candidate_staging_path,
                output_path=output_path,
                error_code="TRANSCRIPT_FILE_NOT_FOUND",
                message=err_msg,
            )
            self._write_output_if_requested(report, output_path)
            return EditorialReviewResult(status="error", report=report, exit_code=2)

        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                raw_transcript_content = f.read()
            cues = parse_transcript(raw_transcript_content, format_hint=format_hint)
            if reconstruct_rolling:
                reconstructor = RollingCaptionReconstructor()
                segments = reconstructor.reconstruct_to_segments(cues)
                reconstruction_method = "rolling_caption_reconstruction"
            else:
                normalizer = TranscriptNormalizer()
                segments = normalizer.normalize(cues)
                reconstruction_method = "standard_normalization"
        except Exception as exc:
            err_msg = f"Failed to parse or reconstruct transcript: {exc}"
            logger.error(err_msg)
            report = self._build_error_report(
                transcript_path=transcript_path,
                candidate_staging_path=candidate_staging_path,
                output_path=output_path,
                error_code="TRANSCRIPT_PROCESSING_ERROR",
                message=err_msg,
            )
            self._write_output_if_requested(report, output_path)
            return EditorialReviewResult(status="error", report=report, exit_code=2)

        segments_by_idx: Dict[int, NormalizedSegment] = {s.segment_index: s for s in segments}
        total_segments = len(segments)

        # 3. Process Review Package Sections
        review_package: Dict[str, Any] = {}
        quotation_grounding_passed = True
        evidence_grounding_valid = True

        # Section A: Episode Summary
        summary_raw = parsed_candidate_data.get("episode_summary", {})
        review_package["episode_summary"] = {
            "candidate": summary_raw,
            "review": {
                "status": "unreviewed",
                "decision": "unreviewed",
                "reviewer_notes": None,
            },
        }

        # Section B: Guest Profile
        guest_raw = parsed_candidate_data.get("guest_profile", {})
        review_package["guest_profile"] = {
            "candidate": guest_raw,
            "grounding_status": "provisional_unverified",
            "source_speaker_classification": "unresolved",
            "review": {
                "status": "unreviewed",
                "decision": "unreviewed",
                "reviewer_notes": None,
            },
        }

        # Section C: Journey Milestones
        milestones_raw = parsed_candidate_data.get("journey_milestones", [])
        milestones_review: List[Dict[str, Any]] = []
        for m_idx, m in enumerate(milestones_raw):
            if not isinstance(m, dict):
                continue
            ev_indices = m.get("evidence_segment_indices", [])
            ev_excerpts: List[Dict[str, Any]] = []
            m_has_missing_seg = False
            m_sponsor_overlap_segs: List[int] = []

            for s_idx in ev_indices:
                if isinstance(s_idx, int) and s_idx in segments_by_idx:
                    seg = segments_by_idx[s_idx]
                    ev_excerpts.append({
                        "segment_index": seg.segment_index,
                        "start_seconds": seg.start_seconds,
                        "end_seconds": round(seg.end_ms / 1000.0, 2),
                        "speaker_label": seg.speaker_label,
                        "text": seg.text,
                    })
                    if self._is_in_sponsor_range(s_idx):
                        m_sponsor_overlap_segs.append(s_idx)
                else:
                    m_has_missing_seg = True
                    evidence_grounding_valid = False
                    errors.append({
                        "severity": "error",
                        "error_code": "SEGMENT_NOT_FOUND",
                        "item_type": "milestone",
                        "item_index": m_idx,
                        "field": f"evidence_segment_indices[{s_idx}]",
                        "message": f"Milestone {m_idx} references non-existent segment {s_idx} (total segments: {total_segments}).",
                    })

            has_sponsor_warning = bool(m_sponsor_overlap_segs)
            if has_sponsor_warning:
                warnings.append({
                    "severity": "warning",
                    "error_code": "SPONSOR_RANGE_OVERLAP",
                    "item_type": "milestone",
                    "item_index": m_idx,
                    "field": "evidence_segment_indices",
                    "message": f"Milestone {m_idx} cites segment(s) {m_sponsor_overlap_segs} overlapping sponsor range [{self.sponsor_range[0]}..{self.sponsor_range[1]}].",
                })
                sponsor_flagged_items.append({
                    "item_type": "milestone",
                    "item_index": m_idx,
                    "overlapping_segments": m_sponsor_overlap_segs,
                })

            milestones_review.append({
                "item_index": m_idx,
                "candidate": m,
                "evidence_excerpts": ev_excerpts,
                "evidence_grounding_status": "unresolved" if m_has_missing_seg else "resolved",
                "sponsor_overlap_warning": has_sponsor_warning,
                "sponsor_overlap_segments": m_sponsor_overlap_segs,
                "review": {
                    "status": "unreviewed",
                    "decision": "unreviewed",
                    "reviewer_notes": None,
                },
            })
        review_package["journey_milestones"] = milestones_review

        # Section D: Insights
        insights_raw = parsed_candidate_data.get("insights", [])
        insights_review: List[Dict[str, Any]] = []
        for ins_idx, ins in enumerate(insights_raw):
            if not isinstance(ins, dict):
                continue
            ev_indices = ins.get("evidence_segment_indices", [])
            ev_excerpts: List[Dict[str, Any]] = []
            ins_has_missing_seg = False
            ins_sponsor_overlap_segs: List[int] = []

            for s_idx in ev_indices:
                if isinstance(s_idx, int) and s_idx in segments_by_idx:
                    seg = segments_by_idx[s_idx]
                    ev_excerpts.append({
                        "segment_index": seg.segment_index,
                        "start_seconds": seg.start_seconds,
                        "end_seconds": round(seg.end_ms / 1000.0, 2),
                        "speaker_label": seg.speaker_label,
                        "text": seg.text,
                    })
                    if self._is_in_sponsor_range(s_idx):
                        ins_sponsor_overlap_segs.append(s_idx)
                else:
                    ins_has_missing_seg = True
                    evidence_grounding_valid = False
                    errors.append({
                        "severity": "error",
                        "error_code": "SEGMENT_NOT_FOUND",
                        "item_type": "insight",
                        "item_index": ins_idx,
                        "field": f"evidence_segment_indices[{s_idx}]",
                        "message": f"Insight {ins_idx} references non-existent segment {s_idx} (total segments: {total_segments}).",
                    })

            has_sponsor_warning = bool(ins_sponsor_overlap_segs)
            if has_sponsor_warning:
                warnings.append({
                    "severity": "warning",
                    "error_code": "SPONSOR_RANGE_OVERLAP",
                    "item_type": "insight",
                    "item_index": ins_idx,
                    "field": "evidence_segment_indices",
                    "message": f"Insight {ins_idx} cites segment(s) {ins_sponsor_overlap_segs} overlapping sponsor range [{self.sponsor_range[0]}..{self.sponsor_range[1]}].",
                })
                sponsor_flagged_items.append({
                    "item_type": "insight",
                    "item_index": ins_idx,
                    "overlapping_segments": ins_sponsor_overlap_segs,
                })

            insights_review.append({
                "item_index": ins_idx,
                "candidate": ins,
                "evidence_excerpts": ev_excerpts,
                "evidence_grounding_status": "unresolved" if ins_has_missing_seg else "resolved",
                "speaker_classification": "unresolved",
                "sponsor_overlap_warning": has_sponsor_warning,
                "sponsor_overlap_segments": ins_sponsor_overlap_segs,
                "review": {
                    "status": "unreviewed",
                    "evidential_support": "unreviewed",
                    "clarity": "unreviewed",
                    "practical_usefulness": "unreviewed",
                    "decision": "unreviewed",
                    "reviewer_notes": None,
                },
            })
        review_package["insights"] = insights_review

        # Section E: Quotations
        quotes_raw = parsed_candidate_data.get("quotations", [])
        quotes_review: List[Dict[str, Any]] = []
        for q_idx, q in enumerate(quotes_raw):
            if not isinstance(q, dict):
                continue
            amharic_quote = str(q.get("amharic_quote", ""))
            clean_candidate_quote = clean_amharic_text(amharic_quote)
            indices = q.get("source_segment_indices") or []
            if isinstance(indices, int):
                indices = [indices]
            elif not isinstance(indices, list):
                indices = []

            quote_excerpts: List[Dict[str, Any]] = []
            q_missing_segs = False
            q_sponsor_overlap_segs: List[int] = []

            # Check existence of segments
            for s_idx in indices:
                if isinstance(s_idx, int) and s_idx in segments_by_idx:
                    seg = segments_by_idx[s_idx]
                    quote_excerpts.append({
                        "segment_index": seg.segment_index,
                        "start_seconds": seg.start_seconds,
                        "end_seconds": round(seg.end_ms / 1000.0, 2),
                        "speaker_label": seg.speaker_label,
                        "text": seg.text,
                    })
                    if self._is_in_sponsor_range(s_idx):
                        q_sponsor_overlap_segs.append(s_idx)
                else:
                    q_missing_segs = True
                    evidence_grounding_valid = False
                    quotation_grounding_passed = False
                    errors.append({
                        "severity": "error",
                        "error_code": "SEGMENT_NOT_FOUND",
                        "item_type": "quotation",
                        "item_index": q_idx,
                        "field": f"source_segment_indices[{s_idx}]",
                        "message": f"Quotation {q_idx} references non-existent segment {s_idx} (total segments: {total_segments}).",
                    })

            canonical_seconds: Optional[int] = None
            timestamp_consistent = True
            time_diff: Optional[int] = None
            reconstructed_text = ""
            grounding_status = "unresolved_evidence"
            grounding_note = ""

            if indices and not q_missing_segs:
                # Canonical timestamp
                first_seg = segments_by_idx[indices[0]]
                canonical_seconds = first_seg.start_ms // 1000
                reported_ts = q.get("timestamp_seconds")
                if reported_ts is not None and isinstance(reported_ts, (int, float)):
                    reported_int = int(reported_ts)
                    if reported_int != canonical_seconds:
                        timestamp_consistent = False
                        time_diff = abs(reported_int - canonical_seconds)
                        warnings.append({
                            "severity": "warning",
                            "error_code": "DISCREPANT_TIMESTAMP",
                            "item_type": "quotation",
                            "item_index": q_idx,
                            "field": "timestamp_seconds",
                            "message": f"Quotation {q_idx} model reported timestamp ({reported_int}s) differs from canonical segment timestamp ({canonical_seconds}s).",
                        })

                # Check contiguity
                if len(indices) > 1:
                    is_contiguous = all(indices[i] + 1 == indices[i + 1] for i in range(len(indices) - 1))
                    if not is_contiguous:
                        quotation_grounding_passed = False
                        errors.append({
                            "severity": "error",
                            "error_code": "NON_CONTIGUOUS_SEGMENTS",
                            "item_type": "quotation",
                            "item_index": q_idx,
                            "field": "source_segment_indices",
                            "message": f"Quotation {q_idx} references non-contiguous segment indices {indices}.",
                        })

                # Verbatim check
                reconstructed_text = " ".join(clean_amharic_text(segments_by_idx[i].text) for i in indices)
                if clean_candidate_quote and clean_candidate_quote in reconstructed_text:
                    grounding_status = "grounded"
                    grounding_note = "Verbatim Amharic match verified in referenced segment(s)."
                else:
                    grounding_status = "mismatch"
                    quotation_grounding_passed = False
                    grounding_note = "Quotation text was not found verbatim in referenced segment(s)."
                    errors.append({
                        "severity": "error",
                        "error_code": "QUOTE_NOT_IN_SOURCE",
                        "item_type": "quotation",
                        "item_index": q_idx,
                        "field": "amharic_quote",
                        "message": f"Quotation {q_idx} not found verbatim in referenced segment(s) {indices}.",
                    })
            elif q_missing_segs:
                grounding_status = "unresolved_evidence"
                grounding_note = "Cannot evaluate verbatim grounding because referenced segment(s) do not exist."

            has_sponsor_warning = bool(q_sponsor_overlap_segs)
            if has_sponsor_warning:
                warnings.append({
                    "severity": "warning",
                    "error_code": "SPONSOR_RANGE_OVERLAP",
                    "item_type": "quotation",
                    "item_index": q_idx,
                    "field": "source_segment_indices",
                    "message": f"Quotation {q_idx} references segment(s) {q_sponsor_overlap_segs} overlapping sponsor range [{self.sponsor_range[0]}..{self.sponsor_range[1]}].",
                })
                sponsor_flagged_items.append({
                    "item_type": "quotation",
                    "item_index": q_idx,
                    "overlapping_segments": q_sponsor_overlap_segs,
                })

            quotes_review.append({
                "item_index": q_idx,
                "candidate": q,
                "canonical_timestamp_seconds": canonical_seconds,
                "timestamp_consistent": timestamp_consistent,
                "timestamp_difference_seconds": time_diff,
                "speaker_attribution_status": "unverified",
                "speaker_attribution_note": "Transcript captions lack named speaker diarization; speaker attribution requires human verification.",
                "source_segment_indices": indices,
                "source_excerpts": quote_excerpts,
                "concatenated_source_text": reconstructed_text,
                "grounding_status": grounding_status,
                "grounding_note": grounding_note,
                "sponsor_overlap_warning": has_sponsor_warning,
                "sponsor_overlap_segments": q_sponsor_overlap_segs,
                "review": {
                    "status": "unreviewed",
                    "decision": "unreviewed",
                    "reviewer_notes": None,
                },
            })
        review_package["quotations"] = quotes_review

        # Section F: Suggested Tags
        tags_raw = parsed_candidate_data.get("suggested_tags", [])
        review_package["suggested_tags"] = {
            "candidate": tags_raw,
            "review": {
                "status": "unreviewed",
                "decision": "unreviewed",
                "reviewer_notes": None,
            },
        }

        # Determine overall package status
        has_fatal_errors = bool(errors)
        overall_status = "validation_failed" if has_fatal_errors else "ready_for_human_review"
        exit_code = 1 if has_fatal_errors else 0

        # Assemble Final Report
        report: Dict[str, Any] = {
            "artifact_type": "editorial_review_package",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "status": overall_status,
            "metadata": {
                "source_transcript_path": transcript_path,
                "candidate_staging_path": candidate_staging_path,
                "output_report_path": output_path,
                "transcript_segment_count": total_segments,
                "reconstruction_method": reconstruction_method,
                "sponsor_range_heuristic": list(self.sponsor_range),
                "prepared_at": datetime.now(timezone.utc).isoformat(),
            },
            "automated_validation": {
                "schema_valid": len([e for e in errors if e.get("error_code") in self._syntactic_error_codes()]) == 0,
                "syntactic_error_count": len([e for e in errors if e.get("error_code") in self._syntactic_error_codes()]),
                "evidence_grounding_valid": evidence_grounding_valid,
                "quotation_grounding_passed": quotation_grounding_passed,
                "total_errors": len(errors),
                "total_warnings": len(warnings),
                "errors": errors,
                "warnings": warnings,
            },
            "sponsor_warnings": {
                "warning_count": len(sponsor_flagged_items),
                "flagged_items": sponsor_flagged_items,
                "heuristic_description": (
                    f"Audit-specific heuristic flagging segment indices [{self.sponsor_range[0]}..{self.sponsor_range[1]}] "
                    f"(known sponsor advertisement / theme music block). Overlapping items are flagged for human review "
                    f"and are not automatically rejected."
                ),
            },
            "review_package": review_package,
            "limitations": [
                "Speaker attribution cannot be confirmed automatically from transcript captions lacking named speaker diarization.",
                "Candidate text is staged and unapproved; human editorial review is required before approval or publication.",
                f"Sponsor-range overlap is an audit heuristic based on Chunk 0 commercial placement (segments {self.sponsor_range[0]}–{self.sponsor_range[1]}).",
            ],
            "disclaimer": EDITORIAL_DISCLAIMER,
        }

        self._write_output_if_requested(report, output_path)
        return EditorialReviewResult(status=overall_status, report=report, exit_code=exit_code)

    def _is_in_sponsor_range(self, seg_idx: int) -> bool:
        """Determines if a segment index falls within the sponsor advertisement heuristic range."""
        return self.sponsor_range[0] <= seg_idx <= self.sponsor_range[1]

    def _syntactic_error_codes(self) -> Set[str]:
        return {
            ValidationErrorCode.MALFORMED_JSON.value,
            ValidationErrorCode.SCHEMA_VIOLATION.value,
            ValidationErrorCode.MISSING_REQUIRED_KEY.value,
            ValidationErrorCode.TYPE_MISMATCH.value,
            ValidationErrorCode.INVALID_CATEGORY.value,
            ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS.value,
            ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS.value,
        }

    def _error_item_to_dict(self, err: ValidationErrorItem) -> Dict[str, Any]:
        return {
            "severity": err.severity.value if hasattr(err.severity, "value") else str(err.severity),
            "error_code": err.error_code.value if hasattr(err.error_code, "value") else str(err.error_code),
            "item_type": err.item_type,
            "item_index": err.item_index,
            "field": err.field,
            "message": err.message,
        }

    def _build_error_report(
        self,
        transcript_path: str,
        candidate_staging_path: str,
        output_path: Optional[str],
        error_code: str,
        message: str,
    ) -> Dict[str, Any]:
        return {
            "artifact_type": "editorial_review_package",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "status": "error",
            "metadata": {
                "source_transcript_path": transcript_path,
                "candidate_staging_path": candidate_staging_path,
                "output_report_path": output_path,
                "sponsor_range_heuristic": list(self.sponsor_range),
                "prepared_at": datetime.now(timezone.utc).isoformat(),
            },
            "automated_validation": {
                "schema_valid": False,
                "syntactic_error_count": 1,
                "evidence_grounding_valid": False,
                "quotation_grounding_passed": False,
                "total_errors": 1,
                "total_warnings": 0,
                "errors": [{
                    "severity": "error",
                    "error_code": error_code,
                    "item_type": "system",
                    "item_index": None,
                    "field": None,
                    "message": message,
                }],
                "warnings": [],
            },
            "sponsor_warnings": {
                "warning_count": 0,
                "flagged_items": [],
                "heuristic_description": f"Audit-specific heuristic range [{self.sponsor_range[0]}..{self.sponsor_range[1]}].",
            },
            "review_package": None,
            "limitations": [
                "Workflow aborted due to configuration or file access error.",
            ],
            "disclaimer": EDITORIAL_DISCLAIMER,
        }

    def _build_validation_failure_report(
        self,
        transcript_path: str,
        candidate_staging_path: str,
        output_path: Optional[str],
        errors: List[Dict[str, Any]],
        warnings: List[Dict[str, Any]],
        failure_reason: str,
    ) -> Dict[str, Any]:
        return {
            "artifact_type": "editorial_review_package",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "status": "validation_failed",
            "metadata": {
                "source_transcript_path": transcript_path,
                "candidate_staging_path": candidate_staging_path,
                "output_report_path": output_path,
                "sponsor_range_heuristic": list(self.sponsor_range),
                "prepared_at": datetime.now(timezone.utc).isoformat(),
            },
            "automated_validation": {
                "schema_valid": False,
                "syntactic_error_count": len(errors),
                "evidence_grounding_valid": False,
                "quotation_grounding_passed": False,
                "total_errors": len(errors),
                "total_warnings": len(warnings),
                "errors": errors,
                "warnings": warnings,
            },
            "sponsor_warnings": {
                "warning_count": 0,
                "flagged_items": [],
                "heuristic_description": f"Audit-specific heuristic range [{self.sponsor_range[0]}..{self.sponsor_range[1]}].",
            },
            "review_package": None,
            "limitations": [
                failure_reason,
            ],
            "disclaimer": EDITORIAL_DISCLAIMER,
        }

    def _write_output_if_requested(self, report: Dict[str, Any], output_path: Optional[str]) -> None:
        if not output_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
