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
from typing import Any, Dict, List, Optional, Tuple

from .extraction_models import (
    CandidateExtractionPayload,
    CandidateInsight,
    CandidateQuotation,
    CandidateQuotationSegment,
    ExtractionRunRecord,
    ValidationStatus,
)


class EditorialAuthorizationError(Exception):
    """Raised when an unprivileged or untrusted actor attempts editorial review or approval."""
    pass


class CrossEpisodeIntegrityError(Exception):
    """Raised when an association attempts to link items across different episodes."""
    pass


class CandidatePersistenceService:
    """
    Handles atomic relational persistence of validated candidate extraction payloads
    and enforces strict server-side editorial review boundaries.
    """

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
        run_id = str(run_row[0]) if run_row else None

        payload = extraction_run.candidate_payload
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
            if ins_row:
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
                        insight_id, segment_id, relevance_score, claim_quote_snippet
                    ) VALUES (
                        %s, %s, %s, %s
                    ) ON CONFLICT (insight_id, segment_id) DO NOTHING;
                    """,
                    (
                        target_insight_id,
                        target_segment_id,
                        ev.relevance_score,
                        ev.claim_quote_snippet,
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
            if q_row:
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
