"""
Meri Content Pipeline v1: Layer 2 Semantic and Evidence Validator.
Verifies segment provenance existence, canonical timestamp derivation,
and exact Amharic quotation verification against normalized transcript segments.

CRITICAL EVIDENCE SEMANTICS:
- Segment existence verification establishes PROVENANCE ONLY: it confirms that cited segments
  exist in the source transcript, establishing an auditable trail for editors.
- Automated validation DOES NOT prove that an extracted business claim or takeaway is factually true.
- All candidate items are strictly staged with review_status="candidate".
- A technical ValidationStatus.PASSED outcome NEVER authorizes publication or marks insights as approved.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from .extraction_models import (
    CandidateEvidenceReference,
    CandidateExtractionPayload,
    CandidateGuestProfile,
    CandidateInsight,
    CandidateMilestone,
    CandidateQuotation,
    CandidateSummary,
    ValidationErrorCode,
    ValidationErrorItem,
    ValidationSeverity,
    ValidationStatus,
)
from .models import NormalizedSegment
from .transcript_normalizer import clean_amharic_text


class SemanticEvidenceValidator:
    """
    Validates candidate extraction output against normalized source transcript segments.
    Enforces that:
    1. Every cited segment exists in the source transcript (establishing provenance linkage).
    2. Quotation timestamps are derived canonically from source segment start_ms (in ms internally, seconds at boundaries).
    3. Model timestamp discrepancies are flagged and canonical source timestamps are preserved.
    4. Amharic quotations are verified verbatim against normalized source segment text.
    5. Cross-segment quotations require contiguous source segment ranges.
    6. Candidate quotes are preserved as-is upon failure without automatic repair or rewriting.
    7. High model confidence scores never bypass or excuse missing evidence.
    8. All insights and quotations retain review_status='candidate' pending human editorial review.
    """

    def validate_and_assemble(
        self,
        data: Dict[str, Any],
        segments: List[NormalizedSegment],
    ) -> Tuple[Optional[CandidateExtractionPayload], List[ValidationErrorItem], ValidationStatus]:
        """
        Executes semantic validation across all candidate entities and assembles
        the CandidateExtractionPayload.

        Returns:
            (payload_or_none, validation_errors_list, validation_status)
        """
        errors: List[ValidationErrorItem] = []
        segments_by_idx: Dict[int, NormalizedSegment] = {s.segment_index: s for s in segments}
        total_segments = len(segments)

        # 1. Episode summary
        summary_raw = data.get("episode_summary", {})
        candidate_summary = CandidateSummary(
            brief=str(summary_raw.get("brief", "")),
            comprehensive=str(summary_raw.get("comprehensive", "")),
            primary_themes=list(summary_raw.get("primary_themes", [])),
        )

        # 2. Guest profile
        guest_raw = data.get("guest_profile", {})
        candidate_guest = CandidateGuestProfile(
            name=str(guest_raw.get("name", "")),
            title=str(guest_raw.get("title", "")),
            company=str(guest_raw.get("company", "")),
            bio=str(guest_raw.get("bio", "")),
            industry=str(guest_raw.get("industry", "")),
            journey_summary=guest_raw.get("journey_summary"),
        )

        # 3. Milestones
        milestones_raw = data.get("journey_milestones", [])
        candidate_milestones: List[CandidateMilestone] = []
        for m_idx, m_raw in enumerate(milestones_raw):
            if not isinstance(m_raw, dict):
                continue
            ev_indices = m_raw.get("evidence_segment_indices", [])
            valid_m_indices: List[int] = []
            if not ev_indices:
                errors.append(
                    ValidationErrorItem(
                        item_type="milestone",
                        item_index=m_idx,
                        field="evidence_segment_indices",
                        error_code=ValidationErrorCode.EMPTY_EVIDENCE,
                        message=f"Milestone at index {m_idx} has empty evidence_segment_indices.",
                    )
                )
            else:
                for seg_idx in ev_indices:
                    if not isinstance(seg_idx, int) or seg_idx not in segments_by_idx:
                        errors.append(
                            ValidationErrorItem(
                                item_type="milestone",
                                item_index=m_idx,
                                field=f"evidence_segment_indices[{seg_idx}]",
                                error_code=ValidationErrorCode.SEGMENT_NOT_FOUND,
                                message=f"Milestone {m_idx} references non-existent segment index {seg_idx} "
                                        f"(total source segments: {total_segments}).",
                            )
                        )
                    else:
                        valid_m_indices.append(seg_idx)

            candidate_milestones.append(
                CandidateMilestone(
                    phase_or_year=str(m_raw.get("phase_or_year", "")),
                    milestone_description=str(m_raw.get("milestone_description", "")),
                    strategic_decision=str(m_raw.get("strategic_decision", "")),
                    evidence_segment_indices=valid_m_indices if len(valid_m_indices) == len(ev_indices) else ev_indices,
                )
            )

        # 4. Insights and Evidence References
        insights_raw = data.get("insights", [])
        candidate_insights: List[CandidateInsight] = []
        evidence_references: List[CandidateEvidenceReference] = []
        valid_insight_count = 0

        for ins_idx, ins_raw in enumerate(insights_raw):
            if not isinstance(ins_raw, dict):
                continue
            ev_indices = ins_raw.get("evidence_segment_indices", [])
            conf_score = float(ins_raw.get("confidence_score", 0.0))
            insight_has_error = False

            if not ev_indices:
                insight_has_error = True
                errors.append(
                    ValidationErrorItem(
                        item_type="insight",
                        item_index=ins_idx,
                        field="evidence_segment_indices",
                        error_code=ValidationErrorCode.EMPTY_EVIDENCE,
                        message=f"Insight at index {ins_idx} ('{ins_raw.get('title', '')}') has no evidence segment indices.",
                    )
                )
            else:
                for seg_idx in ev_indices:
                    if not isinstance(seg_idx, int) or seg_idx not in segments_by_idx:
                        insight_has_error = True
                        errors.append(
                            ValidationErrorItem(
                                item_type="insight",
                                item_index=ins_idx,
                                field=f"evidence_segment_indices[{seg_idx}]",
                                error_code=ValidationErrorCode.SEGMENT_NOT_FOUND,
                                message=f"Insight {ins_idx} references non-existent segment {seg_idx} "
                                        f"(total source segments: {total_segments}). Model confidence score "
                                        f"{conf_score:.2f} cannot override missing evidence.",
                            )
                        )
                    else:
                        evidence_references.append(
                            CandidateEvidenceReference(
                                insight_index=ins_idx,
                                segment_index=seg_idx,
                                relevance_score=conf_score,
                            )
                        )

            if not insight_has_error:
                valid_insight_count += 1

            candidate_insights.append(
                CandidateInsight(
                    title=str(ins_raw.get("title", "")),
                    category=str(ins_raw.get("category", "")),
                    summary=str(ins_raw.get("summary", "")),
                    takeaways=list(ins_raw.get("takeaways", [])),
                    practical_action=str(ins_raw.get("practical_action", "")),
                    evidence_segment_indices=list(ev_indices),
                    confidence_score=conf_score,
                    display_order=ins_idx,
                    review_status="candidate",
                )
            )

        # 5. Quotations (Exact Verbatim & Timestamp Grounding)
        quotations_raw = data.get("quotations", [])
        candidate_quotations: List[CandidateQuotation] = []
        valid_quote_count = 0

        for q_idx, q_raw in enumerate(quotations_raw):
            if not isinstance(q_raw, dict):
                continue

            amharic_quote = str(q_raw.get("amharic_quote", ""))
            clean_candidate_quote = clean_amharic_text(amharic_quote)
            quote_has_error = False

            # Resolve source segment indices
            indices: List[int] = []
            if "source_segment_indices" in q_raw and isinstance(q_raw["source_segment_indices"], list):
                indices = [int(i) for i in q_raw["source_segment_indices"] if isinstance(i, (int, float))]
            elif "source_segment_index" in q_raw and isinstance(q_raw["source_segment_index"], (int, float)):
                indices = [int(q_raw["source_segment_index"])]

            if not indices:
                quote_has_error = True
                errors.append(
                    ValidationErrorItem(
                        item_type="quotation",
                        item_index=q_idx,
                        field="source_segment_indices",
                        error_code=ValidationErrorCode.EMPTY_EVIDENCE,
                        message=f"Quotation at index {q_idx} specifies no source segment indices.",
                    )
                )
                canonical_start_ms = 0
                canonical_seconds = 0
            else:
                # Check segment existence
                missing_indices = [idx for idx in indices if idx not in segments_by_idx]
                if missing_indices:
                    quote_has_error = True
                    for m_idx in missing_indices:
                        errors.append(
                            ValidationErrorItem(
                                item_type="quotation",
                                item_index=q_idx,
                                field=f"source_segment_indices[{m_idx}]",
                                error_code=ValidationErrorCode.SEGMENT_NOT_FOUND,
                                message=f"Quotation {q_idx} references non-existent segment {m_idx} "
                                        f"(total source segments: {total_segments}).",
                            )
                        )
                    canonical_start_ms = 0
                    canonical_seconds = 0
                else:
                    # Check cross-segment contiguity
                    if len(indices) > 1:
                        sorted_indices = sorted(indices)
                        is_contiguous = (
                            indices == sorted_indices
                            and all(sorted_indices[i] + 1 == sorted_indices[i + 1] for i in range(len(sorted_indices) - 1))
                        )
                        if not is_contiguous:
                            quote_has_error = True
                            errors.append(
                                ValidationErrorItem(
                                    item_type="quotation",
                                    item_index=q_idx,
                                    field="source_segment_indices",
                                    error_code=ValidationErrorCode.NON_CONTIGUOUS_SEGMENTS,
                                    message=f"Cross-segment quotation {q_idx} references non-contiguous segment indices {indices}. "
                                            f"Cross-segment quotes must specify a strictly contiguous range.",
                                )
                            )

                    # Derive canonical timestamp from the first source segment's start_ms
                    first_seg = segments_by_idx[indices[0]]
                    canonical_start_ms = first_seg.start_ms
                    canonical_seconds = canonical_start_ms // 1000

                    # Verbatim Amharic quote verification
                    reconstructed_text = " ".join(
                        clean_amharic_text(segments_by_idx[i].text) for i in indices
                    )

                    if clean_candidate_quote not in reconstructed_text:
                        quote_has_error = True
                        errors.append(
                            ValidationErrorItem(
                                item_type="quotation",
                                item_index=q_idx,
                                field="amharic_quote",
                                error_code=ValidationErrorCode.QUOTE_NOT_IN_SOURCE,
                                message=f"Quotation {q_idx} not found verbatim in referenced segment(s) {indices}. "
                                        f"Paraphrase or fabricated quote detected. Preserving candidate quote for audit.",
                            )
                        )

            # Check timestamp discrepancy against model-reported value
            reported_ts_val = q_raw.get("timestamp_seconds")
            has_discrepancy = False
            reported_seconds: Optional[int] = None

            if reported_ts_val is not None and isinstance(reported_ts_val, (int, float)):
                reported_seconds = int(reported_ts_val)
                if indices and indices[0] in segments_by_idx:
                    if reported_seconds != canonical_seconds:
                        has_discrepancy = True
                        diff_sec = abs(reported_seconds - canonical_seconds)
                        errors.append(
                            ValidationErrorItem(
                                item_type="quotation",
                                item_index=q_idx,
                                field="timestamp_seconds",
                                error_code=ValidationErrorCode.DISCREPANT_TIMESTAMP,
                                severity=ValidationSeverity.WARNING,
                                message=f"Quotation {q_idx} model reported timestamp ({reported_seconds}s) differs from "
                                        f"canonical source segment timestamp ({canonical_seconds}s from {canonical_start_ms}ms, "
                                        f"offset: {diff_sec}s). Canonical source timestamp is preserved.",
                            )
                        )

            if not quote_has_error:
                valid_quote_count += 1

            candidate_quotations.append(
                CandidateQuotation(
                    amharic_quote=amharic_quote,
                    english_translation=str(q_raw.get("english_translation", "")),
                    speaker=str(q_raw.get("speaker", "")),
                    source_segment_indices=indices,
                    canonical_start_ms=canonical_start_ms,
                    canonical_timestamp_seconds=canonical_seconds,
                    context=str(q_raw.get("context", "")),
                    reported_timestamp_seconds=reported_seconds,
                    has_timestamp_discrepancy=has_discrepancy,
                    importance_rationale=q_raw.get("importance_rationale"),
                    display_order=q_idx,
                    review_status="candidate",
                )
            )

        # 6. Suggested tags
        candidate_tags = [str(t) for t in data.get("suggested_tags", []) if isinstance(t, str)]

        # Assemble CandidateExtractionPayload
        payload = CandidateExtractionPayload(
            schema_version=str(data.get("schema_version", "1.0.0")),
            episode_summary=candidate_summary,
            guest_profile=candidate_guest,
            journey_milestones=candidate_milestones,
            insights=candidate_insights,
            quotations=candidate_quotations,
            suggested_tags=candidate_tags,
            evidence_references=evidence_references,
        )

        # 7. Compute ValidationStatus
        fatal_errors = [e for e in errors if e.severity == ValidationSeverity.ERROR]
        total_insights = len(insights_raw)
        total_quotes = len(quotations_raw)

        if not fatal_errors:
            status = ValidationStatus.PASSED
        elif valid_insight_count > 0 and valid_quote_count > 0:
            # Some items valid, but some had errors => needs human editorial review
            status = ValidationStatus.PARTIAL
        else:
            # Critical failure: no valid insights or quotes, or pervasive errors
            status = ValidationStatus.FAILED

        return payload, errors, status
