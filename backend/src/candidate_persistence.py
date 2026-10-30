"""
Meri Content Pipeline v1: Candidate Knowledge Persistence & Editorial Review Boundary.
Strictly implements Milestone 3 requirements:
1. Multi-segment quotation relational provenance in `quotation_segments`.
2. Strict candidate review status preservation (never automatically promoted to approved).
3. Server-side authorized editorial review boundary.
4. Guarantee that editorial approval never automatically publishes an episode.
"""

from dataclasses import asdict
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from .extraction_models import (
    CandidateExtractionPayload,
    CandidateInsight,
    CandidateQuotation,
    CandidateQuotationSegment,
    ExtractionRunRecord,
    ValidationStatus,
)
from .models import NormalizedSegment, TranscriptChunk



class EditorialAuthorizationError(Exception):
    """Raised when an unprivileged or untrusted actor attempts editorial review or approval."""
    pass


class CrossEpisodeIntegrityError(Exception):
    """Raised when an association attempts to link items across different episodes."""
    pass


class SegmentReferenceIntegrityError(ValueError):
    """Raised when candidate evidence or quotation references a segment index that does not exist in segment_index_to_id."""
    pass


class CandidatePersistenceService:
    """
    Handles atomic relational persistence of validated candidate extraction payloads
    and enforces strict server-side editorial review boundaries.
    """

    @staticmethod
    def validate_candidate_payload_references(
        payload: CandidateExtractionPayload,
        segment_index_to_id: Dict[int, str],
    ) -> None:
        """
        Validates that every segment reference in candidate payload exists in segment_index_to_id
        and that candidate indices and sequence orders are valid.

        Raises:
            SegmentReferenceIntegrityError: If any referenced segment_index is missing from segment_index_to_id.
            ValueError: If insight or quotation indices are out of bounds or sequence orders are duplicated.
        """
        total_insights = len(payload.insights)
        total_quotations = len(payload.quotations)

        # 1. Validate insight evidence references
        missing_insight_segments: Dict[int, List[int]] = {}
        for ev in payload.evidence_references:
            if ev.insight_index < 0 or ev.insight_index >= total_insights:
                raise ValueError(
                    f"Invalid insight_evidence reference: insight_index {ev.insight_index} is out of bounds "
                    f"(total candidate insights: {total_insights})"
                )
            if ev.segment_index not in segment_index_to_id:
                if ev.insight_index not in missing_insight_segments:
                    missing_insight_segments[ev.insight_index] = []
                missing_insight_segments[ev.insight_index].append(ev.segment_index)

        if missing_insight_segments:
            details = "; ".join(
                f"insight_index {ins_idx} references missing segment_index(es) {seg_indices}"
                for ins_idx, seg_indices in sorted(missing_insight_segments.items())
            )
            raise SegmentReferenceIntegrityError(
                f"Invalid insight_evidence reference: {details}"
            )

        # 2. Validate quotation segment references
        missing_quote_segments: Dict[int, List[int]] = {}
        seen_qs_orders: Set[Tuple[int, int]] = set()
        for qs in payload.quotation_segments:
            if qs.quotation_index < 0 or qs.quotation_index >= total_quotations:
                raise ValueError(
                    f"Invalid quotation_segment reference: quotation_index {qs.quotation_index} is out of bounds "
                    f"(total candidate quotations: {total_quotations})"
                )
            if (qs.quotation_index, qs.sequence_order) in seen_qs_orders:
                raise ValueError(
                    f"Duplicate quotation_segment sequence_order {qs.sequence_order} for quotation_index {qs.quotation_index}"
                )
            seen_qs_orders.add((qs.quotation_index, qs.sequence_order))

            if qs.segment_index not in segment_index_to_id:
                if qs.quotation_index not in missing_quote_segments:
                    missing_quote_segments[qs.quotation_index] = []
                missing_quote_segments[qs.quotation_index].append(qs.segment_index)

        if missing_quote_segments:
            details = "; ".join(
                f"quotation_index {q_idx} references missing segment_index(es) {seg_indices}"
                for q_idx, seg_indices in sorted(missing_quote_segments.items())
            )
            raise SegmentReferenceIntegrityError(
                f"Invalid quotation_segment reference: {details}"
            )

        # 3. Validate quotation source segment indices (anchor and spanned segments)
        missing_quote_sources: Dict[int, List[int]] = {}
        for q_idx, quote in enumerate(payload.quotations):
            for seg_idx in quote.source_segment_indices:
                if seg_idx not in segment_index_to_id:
                    if q_idx not in missing_quote_sources:
                        missing_quote_sources[q_idx] = []
                    missing_quote_sources[q_idx].append(seg_idx)

        if missing_quote_sources:
            details = "; ".join(
                f"quotation_index {q_idx} references missing segment_index(es) {seg_indices}"
                for q_idx, seg_indices in sorted(missing_quote_sources.items())
            )
            raise SegmentReferenceIntegrityError(
                f"Invalid quotation source reference: {details}"
            )

    @staticmethod
    def persist_candidate_extraction(
        cursor: Any,
        episode_id: str,
        extraction_run: ExtractionRunRecord,
        segment_index_to_id: Dict[int, str],
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Persists an extraction run and its candidate knowledge items to PostgreSQL.

        STRICT BOUNDARY CONSTRAINTS:
        - `review_status` on all candidate insights and quotations is explicitly 'candidate'.
        - Extraction validation passing NEVER promotes any item to 'verified' or 'approved'.
        - Quotation starting segment anchor is stored in `quotations.segment_id`.
        - All spanned segments are stored with deterministic sequence_order in `quotation_segments`.
        - Insight supporting citations are stored in `insight_evidence`.
        - Publication status of the episode is untouched.
        """
        payload = extraction_run.candidate_payload
        if payload:
            # Validate all segment references before inserting candidate rows
            CandidatePersistenceService.validate_candidate_payload_references(
                payload=payload,
                segment_index_to_id=segment_index_to_id,
            )

        # 1. Insert extraction_runs record
        errors_json = json.dumps([err.to_dict() for err in extraction_run.validation_errors])
        cursor.execute(
            """
            INSERT INTO extraction_runs (
                job_id, episode_id, run_number, model_id, prompt_version,
                raw_response_json, validation_status, validation_errors,
                tokens_prompt, tokens_completion
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s
            ) RETURNING id;
            """,
            (
                job_id or extraction_run.job_id,
                episode_id,
                extraction_run.run_number,
                extraction_run.model_id,
                extraction_run.prompt_version,
                extraction_run.raw_response_json,
                extraction_run.validation_status.value,
                errors_json,
                extraction_run.tokens_prompt,
                extraction_run.tokens_completion,
            ),
        )
        run_row = cursor.fetchone()
        if not run_row or not run_row[0]:
            raise RuntimeError("Failed to persist extraction_run: database returned no ID")
        run_id = str(run_row[0])

        if not payload:
            return {
                "run_id": run_id,
                "insights_inserted": 0,
                "quotations_inserted": 0,
                "evidence_inserted": 0,
                "quotation_segments_inserted": 0,
            }

        # 2. Insert candidate insights (review_status='candidate' strictly enforced)
        insight_id_map: Dict[int, str] = {}
        insights_inserted = 0
        for idx, insight in enumerate(payload.insights):
            cursor.execute(
                """
                INSERT INTO insights (
                    episode_id, extraction_run_id, category, title, summary,
                    takeaways, practical_action, display_order, review_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, 'candidate'
                ) RETURNING id;
                """,
                (
                    episode_id,
                    run_id,
                    insight.category,
                    insight.title,
                    insight.summary,
                    insight.takeaways,
                    insight.practical_action,
                    insight.display_order,
                ),
            )
            ins_row = cursor.fetchone()
            if not ins_row or not ins_row[0]:
                raise RuntimeError(f"Failed to persist insight {idx}: database returned no ID")
            insight_id_map[idx] = str(ins_row[0])
            insights_inserted += 1

        # 3. Insert insight evidence links
        evidence_inserted = 0
        for ev in payload.evidence_references:
            target_insight_id = insight_id_map.get(ev.insight_index)
            target_segment_id = segment_index_to_id.get(ev.segment_index)
            if target_insight_id and target_segment_id:
                cursor.execute(
                    """
                    INSERT INTO insight_evidence (
                        insight_id, segment_id, relevance_score, claim_quote_snippet, notes
                    ) VALUES (
                        %s, %s, %s, %s, %s
                    ) ON CONFLICT (insight_id, segment_id) DO NOTHING;
                    """,
                    (
                        target_insight_id,
                        target_segment_id,
                        ev.relevance_score,
                        ev.claim_quote_snippet,
                        ev.notes,
                    ),
                )
                evidence_inserted += 1

        # 4. Insert candidate quotations
        # Preserving starting segment anchor in segment_id and canonical timestamp
        quote_id_map: Dict[int, str] = {}
        quotations_inserted = 0
        for q_idx, quote in enumerate(payload.quotations):
            anchor_seg_id = None
            if quote.source_segment_indices:
                first_seg_idx = quote.source_segment_indices[0]
                anchor_seg_id = segment_index_to_id.get(first_seg_idx)

            cursor.execute(
                """
                INSERT INTO quotations (
                    episode_id, extraction_run_id, segment_id, amharic_quote,
                    english_translation, speaker, timestamp_seconds, context,
                    display_order, review_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, 'candidate'
                ) RETURNING id;
                """,
                (
                    episode_id,
                    run_id,
                    anchor_seg_id,
                    quote.amharic_quote,
                    quote.english_translation,
                    quote.speaker,
                    quote.canonical_timestamp_seconds,
                    quote.context,
                    quote.display_order,
                ),
            )
            q_row = cursor.fetchone()
            if not q_row or not q_row[0]:
                raise RuntimeError(f"Failed to persist quotation {q_idx}: database returned no ID")
            quote_id_map[q_idx] = str(q_row[0])
            quotations_inserted += 1

        # 5. Insert quotation_segments (relational multi-segment provenance with sequence ordering)
        quotation_segments_inserted = 0
        for qs in payload.quotation_segments:
            target_quote_id = quote_id_map.get(qs.quotation_index)
            target_segment_id = segment_index_to_id.get(qs.segment_index)
            if target_quote_id and target_segment_id:
                cursor.execute(
                    """
                    INSERT INTO quotation_segments (
                        quotation_id, segment_id, sequence_order
                    ) VALUES (
                        %s, %s, %s
                    ) ON CONFLICT (quotation_id, segment_id) DO NOTHING;
                    """,
                    (
                        target_quote_id,
                        target_segment_id,
                        qs.sequence_order,
                    ),
                )
                quotation_segments_inserted += 1

        return {
            "run_id": run_id,
            "insights_inserted": insights_inserted,
            "quotations_inserted": quotations_inserted,
            "evidence_inserted": evidence_inserted,
            "quotation_segments_inserted": quotation_segments_inserted,
        }

    @staticmethod
    def execute_editorial_review(
        cursor: Any,
        item_type: str,
        item_id: str,
        decision: str,
        reviewer_id: Optional[str] = None,
        is_authorized_actor: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes editorial review via the database `review_candidate_item` RPC function.

        Enforces that:
        - Only authorized operations can succeed.
        - User-editable profile metadata or unauthenticated roles are rejected.
        - Editorial approval never automatically publishes an episode.
        """
        if not is_authorized_actor:
            raise EditorialAuthorizationError(
                "Access denied: caller does not have authorized editorial review privileges."
            )

        cursor.execute(
            """
            SELECT review_candidate_item(%s, %s::uuid, %s, %s::uuid);
            """,
            (
                item_type,
                item_id,
                decision,
                reviewer_id,
            ),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Editorial review RPC returned no response for {item_type} {item_id}")
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])

    @staticmethod
    def persist_transcript_segments(
        cursor: Any,
        episode_id: str,
        segments: List[NormalizedSegment],
    ) -> Dict[int, str]:
        """
        Persists normalized transcript segments to the existing `transcript_segments` table.
        Transaction ownership remains strictly with the caller; this method will not commit.

        Args:
            cursor: Active database cursor.
            episode_id: Parent episode UUID.
            segments: List of NormalizedSegment atoms.

        Returns:
            Deterministic mapping from source segment_index -> persisted database UUID (str).

        Raises:
            ValueError: If episode_id is missing, segments contains duplicate segment indices,
                        or any segment has an invalid segment_index.
            RuntimeError: If database insertion fails to return a generated UUID.
            Exception: Propagates database exceptions (e.g. unique constraint or foreign key violations).
        """
        if not episode_id:
            raise ValueError("episode_id is required to persist transcript segments")

        if not segments:
            return {}

        seen_indices: Set[int] = set()
        for seg in segments:
            if seg.segment_index < 0:
                raise ValueError(f"segment_index must be >= 0, got {seg.segment_index}")
            if seg.segment_index in seen_indices:
                raise ValueError(f"Duplicate segment_index {seg.segment_index} detected in input segments")
            seen_indices.add(seg.segment_index)

        segment_index_to_id: Dict[int, str] = {}
        for seg in segments:
            # Respect generated columns: 'start_seconds' is GENERATED ALWAYS AS STORED in PostgreSQL.
            # Never include 'start_seconds' in the INSERT column list.
            acq_method = seg.acquisition_method.value if hasattr(seg.acquisition_method, "value") else str(seg.acquisition_method)
            cursor.execute(
                """
                INSERT INTO transcript_segments (
                    episode_id, segment_index, start_ms, end_ms,
                    speaker_label, language_code, acquisition_method, text, confidence
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING segment_index, id;
                """,
                (
                    episode_id,
                    seg.segment_index,
                    seg.start_ms,
                    seg.end_ms,
                    seg.speaker_label,
                    seg.language_code,
                    acq_method,
                    seg.text,
                    seg.confidence,
                ),
            )
            row = cursor.fetchone()
            if not row or len(row) < 2 or not row[1]:
                raise RuntimeError(
                    f"Failed to persist transcript segment {seg.segment_index}: database returned no ID"
                )
            ret_seg_idx, ret_id = row[0], str(row[1])
            if ret_seg_idx != seg.segment_index:
                raise RuntimeError(
                    f"Segment index mismatch on insert: expected {seg.segment_index}, database returned {ret_seg_idx}"
                )
            segment_index_to_id[seg.segment_index] = ret_id

        return segment_index_to_id


    @staticmethod
    def persist_transcript_chunks(
        cursor: Any,
        episode_id: str,
        chunks: List[TranscriptChunk],
        valid_segment_indices: Optional[Set[int]] = None,
    ) -> int:
        """
        Persists synthesized context chunks to the existing `transcript_chunks` table.
        Transaction ownership remains strictly with the caller; this method will not commit.

        Args:
            cursor: Active database cursor.
            episode_id: Parent episode UUID.
            chunks: List of TranscriptChunk instances to persist.
            valid_segment_indices: Optional set of source segment indices. If provided,
                                  validates that chunk start and end boundaries reference
                                  valid source segments.

        Returns:
            Count of chunks successfully inserted.

        Raises:
            ValueError: If episode_id is missing, duplicate chunk indices exist,
                        or chunk boundaries are structurally invalid or out-of-bounds.
            RuntimeError: If database insertion fails to return a generated UUID.
            Exception: Propagates database exceptions.
        """
        if not episode_id:
            raise ValueError("episode_id is required to persist transcript chunks")

        if not chunks:
            return 0

        seen_chunk_indices: Set[int] = set()
        for chunk in chunks:
            if chunk.chunk_index < 0:
                raise ValueError(f"chunk_index must be >= 0, got {chunk.chunk_index}")
            if chunk.chunk_index in seen_chunk_indices:
                raise ValueError(f"Duplicate chunk_index {chunk.chunk_index} detected in input chunks")
            seen_chunk_indices.add(chunk.chunk_index)

            if chunk.start_segment_index < 0:
                raise ValueError(f"start_segment_index must be >= 0, got {chunk.start_segment_index}")
            if chunk.end_segment_index < chunk.start_segment_index:
                raise ValueError(
                    f"end_segment_index ({chunk.end_segment_index}) cannot be less than "
                    f"start_segment_index ({chunk.start_segment_index})"
                )
            if chunk.start_ms < 0 or chunk.end_ms < chunk.start_ms:
                raise ValueError(
                    f"Invalid timestamps in chunk {chunk.chunk_index}: start_ms={chunk.start_ms}, end_ms={chunk.end_ms}"
                )

            if valid_segment_indices is not None:
                if chunk.start_segment_index not in valid_segment_indices:
                    raise ValueError(
                        f"Chunk {chunk.chunk_index} start_segment_index {chunk.start_segment_index} "
                        f"does not exist in valid source segments"
                    )
                if chunk.end_segment_index not in valid_segment_indices:
                    raise ValueError(
                        f"Chunk {chunk.chunk_index} end_segment_index {chunk.end_segment_index} "
                        f"does not exist in valid source segments"
                    )

        chunks_inserted = 0
        for chunk in chunks:
            cursor.execute(
                """
                INSERT INTO transcript_chunks (
                    episode_id, chunk_index, start_segment_index, end_segment_index,
                    start_ms, end_ms, token_count_estimate, chunk_text
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id;
                """,
                (
                    episode_id,
                    chunk.chunk_index,
                    chunk.start_segment_index,
                    chunk.end_segment_index,
                    chunk.start_ms,
                    chunk.end_ms,
                    chunk.token_count_estimate,
                    chunk.chunk_text,
                ),
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                raise RuntimeError(
                    f"Failed to persist transcript chunk {chunk.chunk_index}: database returned no ID"
                )
            chunks_inserted += 1

        return chunks_inserted


def persist_transcript_segments(
    cursor: Any,
    episode_id: str,
    segments: List[NormalizedSegment],
) -> Dict[int, str]:
    """Helper dispatching to CandidatePersistenceService.persist_transcript_segments."""
    return CandidatePersistenceService.persist_transcript_segments(cursor, episode_id, segments)


def persist_transcript_chunks(
    cursor: Any,
    episode_id: str,
    chunks: List[TranscriptChunk],
    valid_segment_indices: Optional[Set[int]] = None,
) -> int:
    """Helper dispatching to CandidatePersistenceService.persist_transcript_chunks."""
    return CandidatePersistenceService.persist_transcript_chunks(
        cursor, episode_id, chunks, valid_segment_indices=valid_segment_indices
    )
