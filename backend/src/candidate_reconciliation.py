"""
Meri Content Pipeline v1: Candidate Deduplication and Multi-Chunk Reconciliation Engine.

Implements conservative, deterministic reconciliation of candidate insights and quotations
extracted across overlapping transcript chunks while strictly preserving source evidence,
provenance traceability, and editorial meaning.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. Reconciliation is strictly deterministic, pure-Python, and independent of database access.
2. Never merge different candidate types (e.g. insights with quotations).
3. Never merge two candidates solely because they share a category, anchor segment, speaker, or topic.
4. Prefer exact normalized-text matching combined with compatible candidate type and meaningful evidence overlap.
5. Preserve all valid evidence-segment references when merging duplicates, using deterministic ordering
   and removing duplicate references.
6. Preserve distinctions in substantive claims, mistakes, lessons, and practical recommendations.
7. For quotations, require compatible verbatim text and compatible source attribution.
   Never rewrite or synthesize quoted text.
8. If a match is ambiguous, retain both candidates.
9. Select the canonical candidate deterministically, independent of input ordering.
10. Preserve candidate validity and all required schema fields. Do not invent missing fields or evidence.
11. Return a reconciliation report or structured merge records that identify which candidates were merged and why.
12. Do not automatically publish, approve, or promote any candidate (review_status strictly 'candidate').
"""

from collections import defaultdict
from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import unicodedata

from .extraction_models import (
    CandidateEvidenceReference,
    CandidateExtractionPayload,
    CandidateGuestProfile,
    CandidateInsight,
    CandidateMilestone,
    CandidateQuotation,
    CandidateQuotationSegment,
    CandidateSummary,
)
from .transcript_normalizer import clean_amharic_text

# Regex to collapse consecutive whitespace into a single ASCII space
_WHITESPACE_COLLAPSER = re.compile(r"[ \t\r\n\f\v]+")
# Trailing punctuation stripper for normalized title/category matching
_PUNCTUATION_STRIPPER = re.compile(r"^[\s\.,:;\-—!?፡።፣፤፦፧]+|[\s\.,:;\-—!?፡።፣፤፦፧]+$")


def normalize_text(text: Optional[str]) -> str:
    """
    Normalizes Latin, Amharic, or mixed text for comparison:
    1. Unicode NFC normalization.
    2. Collapses whitespace.
    3. Strips edge punctuation.
    4. Lowercases Latin characters (Amharic fidel is unaffected).
    """
    if not text:
        return ""
    nfc = unicodedata.normalize("NFC", text)
    collapsed = _WHITESPACE_COLLAPSER.sub(" ", nfc).strip()
    stripped = _PUNCTUATION_STRIPPER.sub("", collapsed)
    return stripped.lower()


def normalize_category(category: Optional[str]) -> str:
    """Normalizes business category names for taxonomy compatibility."""
    return normalize_text(category)


def normalize_amharic_quote(quote: Optional[str]) -> str:
    """
    Normalizes spoken Amharic quote verbatim text using clean_amharic_text.
    Preserves exact Ethiopic characters, wordspaces, and sentence punctuation.
    """
    if not quote:
        return ""
    return clean_amharic_text(quote)


@dataclass(frozen=True)
class MergeRecord:
    """
    Auditable structured record documenting a reconciliation merge.
    Identifies which candidate entities were merged and the deterministic rationale.
    """
    candidate_type: str  # 'insight' or 'quotation'
    canonical_identifier: str  # Insight title or quotation snippet
    merged_identifiers: List[str]  # Identifiers of secondary candidates merged into canonical
    reason: str  # Explicit rationale (e.g. title match + evidence overlap [12, 13])
    evidence_segments_before: List[List[int]]  # Evidence/source segments of all inputs before merge
    evidence_segments_after: List[int]  # Deduplicated, deterministically ordered evidence segments
    confidence_before: Optional[List[float]] = None
    confidence_after: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_type": self.candidate_type,
            "canonical_identifier": self.canonical_identifier,
            "merged_identifiers": list(self.merged_identifiers),
            "reason": self.reason,
            "evidence_segments_before": [list(ev) for ev in self.evidence_segments_before],
            "evidence_segments_after": list(self.evidence_segments_after),
            "confidence_before": list(self.confidence_before) if self.confidence_before else None,
            "confidence_after": self.confidence_after,
        }


@dataclass(frozen=True)
class ReconciliationReport:
    """Summary metrics of candidate reconciliation."""
    total_insights_in: int
    total_insights_out: int
    insights_merged_count: int
    total_quotations_in: int
    total_quotations_out: int
    quotations_merged_count: int
    merge_records: List[MergeRecord]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_insights_in": self.total_insights_in,
            "total_insights_out": self.total_insights_out,
            "insights_merged_count": self.insights_merged_count,
            "total_quotations_in": self.total_quotations_in,
            "total_quotations_out": self.total_quotations_out,
            "quotations_merged_count": self.quotations_merged_count,
            "merge_records": [r.to_dict() for r in self.merge_records],
        }


@dataclass(frozen=True)
class InsightReconciliationResult:
    """Result of reconciling candidate insights."""
    insights: List[CandidateInsight]
    merge_records: List[MergeRecord]
    index_map: Dict[int, int] = field(default_factory=dict)

    def __iter__(self):
        return iter((self.insights, self.merge_records))


@dataclass(frozen=True)
class QuotationReconciliationResult:
    """Result of reconciling candidate quotations."""
    quotations: List[CandidateQuotation]
    merge_records: List[MergeRecord]
    index_map: Dict[int, int] = field(default_factory=dict)

    def __iter__(self):
        return iter((self.quotations, self.merge_records))


@dataclass(frozen=True)
class PayloadReconciliationResult:
    """Result of reconciling full candidate extraction payloads."""
    payload: CandidateExtractionPayload
    report: ReconciliationReport
    merge_records: List[MergeRecord]

    def __iter__(self):
        return iter((self.payload, self.report))


class CandidateReconciler:
    """
    Deterministic, conservative candidate reconciliation engine for multi-chunk extraction.
    """

    def __init__(self, min_summary_similarity: float = 0.70) -> None:
        self.min_summary_similarity = min_summary_similarity

    # -------------------------------------------------------------------------
    # Pairwise Duplicate Evaluators
    # -------------------------------------------------------------------------

    def are_duplicate_insights(
        self, ins1: Any, ins2: Any
    ) -> Tuple[bool, str]:
        """
        Determines whether two candidate insights represent the same underlying takeaway.

        CRITERIA:
        1. Both must be CandidateInsight instances (never merge different types).
        2. Category must match under normalization (e.g. 'Operations' == 'operations').
        3. Title must match under normalization.
        4. Both must have non-empty evidence segments and share at least one evidence segment index.
        5. Substantive summaries must be compatible (exact match or truncation prefix/substring).
        6. Practical actions must be compatible (must not offer conflicting recommendations).

        If any condition is not satisfied, returns (False, reason).
        """
        if not isinstance(ins1, CandidateInsight) or not isinstance(ins2, CandidateInsight):
            return False, "Candidate types are incompatible (must both be CandidateInsight)."

        # 1. Category compatibility
        cat1 = normalize_category(ins1.category)
        cat2 = normalize_category(ins2.category)
        if cat1 != cat2:
            return False, f"Categories differ ('{ins1.category}' != '{ins2.category}')."

        # 2. Title matching
        title1 = normalize_text(ins1.title)
        title2 = normalize_text(ins2.title)
        if not title1 or not title2 or title1 != title2:
            return False, f"Titles differ ('{ins1.title}' != '{ins2.title}')."

        # 3. Meaningful evidence segment overlap
        ev1 = set(ins1.evidence_segment_indices)
        ev2 = set(ins2.evidence_segment_indices)
        if not ev1 or not ev2:
            return False, "One or both insights have empty evidence segment references."
        shared_evidence = ev1 & ev2
        if not shared_evidence:
            return False, f"No evidence segment overlap between {ins1.evidence_segment_indices} and {ins2.evidence_segment_indices}."

        # 4. Substantive claim / summary compatibility
        sum1 = normalize_text(ins1.summary)
        sum2 = normalize_text(ins2.summary)
        if sum1 != sum2:
            # Check for chunk boundary truncation (one is a substring of the other with sufficient length ratio)
            len1, len2 = len(sum1), len(sum2)
            shorter_len = min(len1, len2)
            longer_len = max(len1, len2)
            length_ratio = shorter_len / longer_len if longer_len > 0 else 0.0

            is_substring = (sum1 in sum2) or (sum2 in sum1)
            if not (is_substring and length_ratio >= self.min_summary_similarity):
                return False, "Summaries make substantively distinct or contradictory claims."

        # 5. Practical action compatibility (preserve distinctions in practical recommendations)
        act1 = normalize_text(ins1.practical_action)
        act2 = normalize_text(ins2.practical_action)
        if act1 and act2 and act1 != act2:
            # If both provide non-empty practical actions that do not match and neither is a substring,
            # they are distinct recommendations!
            if (act1 not in act2) and (act2 not in act1):
                return False, f"Practical actions are distinct ('{ins1.practical_action}' vs '{ins2.practical_action}')."

        return True, f"Normalized title and category match with shared evidence segments {sorted(list(shared_evidence))}."

    def are_duplicate_quotations(
        self, q1: Any, q2: Any
    ) -> Tuple[bool, str]:
        """
        Determines whether two candidate quotations represent the same spoken utterance.

        CRITERIA:
        1. Both must be CandidateQuotation instances.
        2. Spoken Amharic quote must match verbatim under clean_amharic_text normalization.
        3. Speaker attribution must be compatible.
        4. Source segment indices must overlap.
        5. Combined source segments must form a strictly contiguous sequence without gaps.
           Never infer continuity across disconnected segments.

        If any condition is not satisfied, returns (False, reason).
        """
        if not isinstance(q1, CandidateQuotation) or not isinstance(q2, CandidateQuotation):
            return False, "Candidate types are incompatible (must both be CandidateQuotation)."

        # 1. Exact verbatim Amharic quote matching
        quote1 = normalize_amharic_quote(q1.amharic_quote)
        quote2 = normalize_amharic_quote(q2.amharic_quote)
        if not quote1 or not quote2 or quote1 != quote2:
            return False, "Amharic quote text is not identical verbatim."

        # 2. Compatible speaker attribution
        speaker1 = normalize_text(q1.speaker)
        speaker2 = normalize_text(q2.speaker)
        if speaker1 and speaker2 and speaker1 != speaker2:
            return False, f"Speaker attribution differs ('{q1.speaker}' != '{q2.speaker}')."

        # 3. Meaningful source segment overlap
        seg1 = set(q1.source_segment_indices)
        seg2 = set(q2.source_segment_indices)
        if not seg1 or not seg2:
            return False, "One or both quotations lack source segment indices."
        shared_segments = seg1 & seg2
        if not shared_segments:
            return False, f"Disjoint transcript occurrences: segments {q1.source_segment_indices} vs {q2.source_segment_indices}."

        # 4. Continuity check: combined segments must form an unbroken contiguous sequence
        combined_segments = sorted(list(seg1 | seg2))
        is_contiguous = all(
            combined_segments[i] + 1 == combined_segments[i + 1]
            for i in range(len(combined_segments) - 1)
        )
        if not is_contiguous:
            return False, f"Merged source segment indices {combined_segments} are non-contiguous."

        return True, f"Verbatim Amharic quote and compatible speaker match with overlapping contiguous source segments {combined_segments}."

    # -------------------------------------------------------------------------
    # Canonical Tie-Breakers & Group Merge Solvers
    # -------------------------------------------------------------------------

    def _insight_canonical_sort_key(self, ins: CandidateInsight) -> Tuple[Any, ...]:
        """
        Complete deterministic sort key for CandidateInsight canonical selection.
        Encompasses all substantive and descriptive content fields to ensure stable tie-breaking.
        """
        min_ev = min(ins.evidence_segment_indices) if ins.evidence_segment_indices else 999999
        return (
            -len(ins.evidence_segment_indices),
            -round(ins.confidence_score, 4),
            -len(ins.takeaways),
            -len(ins.summary or ""),
            min_ev,
            normalize_category(ins.category),
            normalize_text(ins.title),
            normalize_text(ins.summary),
            normalize_text(ins.practical_action),
            ins.practical_action or "",
            tuple(ins.takeaways),
            tuple(sorted(ins.evidence_segment_indices)),
        )

    def _quotation_canonical_sort_key(self, q: CandidateQuotation) -> Tuple[Any, ...]:
        """
        Complete deterministic sort key for CandidateQuotation canonical selection.
        Encompasses verbatim Amharic text, speaker, and English translation to break ties safely.
        """
        min_seg = min(q.source_segment_indices) if q.source_segment_indices else 999999
        return (
            -len(q.source_segment_indices),
            0 if q.importance_rationale else 1,
            -len(q.english_translation or ""),
            q.canonical_start_ms,
            min_seg,
            normalize_amharic_quote(q.amharic_quote),
            normalize_text(q.speaker),
            normalize_text(q.english_translation),
            q.english_translation or "",
            q.speaker or "",
            q.context or "",
            q.importance_rationale or "",
            tuple(sorted(q.source_segment_indices)),
        )

    def _merge_insight_group(
        self, group: List[CandidateInsight]
    ) -> Tuple[CandidateInsight, Optional[MergeRecord]]:
        """
        Merges an unambiguous cluster of duplicate insights into a single canonical CandidateInsight.
        Preserves all valid evidence references, deduplicated in sorted ascending order.
        """
        if len(group) == 1:
            return group[0], None

        sorted_group = sorted(group, key=self._insight_canonical_sort_key)
        canonical = sorted_group[0]
        secondaries = sorted_group[1:]

        # Merge evidence segments: sorted ascending, duplicates eliminated
        all_evidence: Set[int] = set()
        for ins in group:
            for idx in ins.evidence_segment_indices:
                if isinstance(idx, int):
                    all_evidence.add(idx)
        unified_evidence = sorted(list(all_evidence))

        # Merge takeaways: start with canonical takeaways, add unique non-duplicate ones up to max 6
        seen_takeaways: Set[str] = set()
        merged_takeaways: List[str] = []
        for t in canonical.takeaways:
            norm_t = normalize_text(t)
            if norm_t and norm_t not in seen_takeaways:
                seen_takeaways.add(norm_t)
                merged_takeaways.append(t)

        for sec in secondaries:
            for t in sec.takeaways:
                if len(merged_takeaways) >= 6:
                    break
                norm_t = normalize_text(t)
                if norm_t and norm_t not in seen_takeaways:
                    seen_takeaways.add(norm_t)
                    merged_takeaways.append(t)

        # Confidence score: max across duplicates, rounded to 4 decimals
        confidence_before = [round(ins.confidence_score, 4) for ins in group]
        max_confidence = max(confidence_before)

        # Practical action: prefer canonical's, or fall back to first non-empty
        practical_action = canonical.practical_action
        if not practical_action:
            for sec in secondaries:
                if sec.practical_action:
                    practical_action = sec.practical_action
                    break

        reconciled_insight = CandidateInsight(
            title=canonical.title,
            category=canonical.category,
            summary=canonical.summary,
            takeaways=merged_takeaways,
            practical_action=practical_action,
            evidence_segment_indices=unified_evidence,
            confidence_score=max_confidence,
            display_order=canonical.display_order,
            review_status="candidate",  # Strictly preserve candidate status
        )

        record = MergeRecord(
            candidate_type="insight",
            canonical_identifier=canonical.title,
            merged_identifiers=[sec.title for sec in secondaries],
            reason=f"Merged {len(secondaries)} duplicate insight(s) across overlapping chunks with unified evidence segments {unified_evidence}.",
            evidence_segments_before=[list(ins.evidence_segment_indices) for ins in group],
            evidence_segments_after=unified_evidence,
            confidence_before=confidence_before,
            confidence_after=max_confidence,
        )

        return reconciled_insight, record

    def _merge_quotation_group(
        self, group: List[CandidateQuotation]
    ) -> Tuple[CandidateQuotation, Optional[MergeRecord]]:
        """
        Merges an unambiguous cluster of duplicate quotations into a single canonical CandidateQuotation.
        Preserves verbatim Amharic text without synthesis or rewriting.
        Preserves contiguous source segment sequence and canonical earliest timestamp.
        """
        if len(group) == 1:
            return group[0], None

        sorted_group = sorted(group, key=self._quotation_canonical_sort_key)
        canonical = sorted_group[0]
        secondaries = sorted_group[1:]

        # Merge source segment indices: sorted ascending, duplicates eliminated
        all_segments: Set[int] = set()
        for q in group:
            for s_idx in q.source_segment_indices:
                if isinstance(s_idx, int):
                    all_segments.add(s_idx)
        unified_segments = sorted(list(all_segments))

        # Earliest canonical start timestamp
        min_start_ms = min(q.canonical_start_ms for q in group)
        canonical_seconds = min_start_ms // 1000

        # Preserve verbatim Amharic quote from canonical (never rewritten)
        verbatim_amharic = canonical.amharic_quote

        # Prefer canonical English translation or longest among group
        english_translation = canonical.english_translation
        for sec in secondaries:
            if len(sec.english_translation or "") > len(english_translation or ""):
                english_translation = sec.english_translation

        # Context & Rationale
        context = canonical.context
        importance_rationale = canonical.importance_rationale
        if not importance_rationale:
            for sec in secondaries:
                if sec.importance_rationale:
                    importance_rationale = sec.importance_rationale
                    break

        # Re-evaluate discrepancy against merged canonical timestamp
        reported_ts = canonical.reported_timestamp_seconds
        has_discrepancy = (reported_ts != canonical_seconds) if reported_ts is not None else any(q.has_timestamp_discrepancy for q in group)

        reconciled_quote = CandidateQuotation(
            amharic_quote=verbatim_amharic,
            english_translation=english_translation,
            speaker=canonical.speaker,
            source_segment_indices=unified_segments,
            canonical_start_ms=min_start_ms,
            canonical_timestamp_seconds=canonical_seconds,
            context=context,
            reported_timestamp_seconds=reported_ts,
            has_timestamp_discrepancy=has_discrepancy,
            importance_rationale=importance_rationale,
            display_order=canonical.display_order,
            review_status="candidate",  # Strictly preserve candidate status
        )

        record = MergeRecord(
            candidate_type="quotation",
            canonical_identifier=f"[{canonical.speaker}]: {verbatim_amharic[:40]}...",
            merged_identifiers=[f"[{s.speaker}]: {s.amharic_quote[:40]}..." for s in secondaries],
            reason=f"Merged {len(secondaries)} duplicate quote(s) with unified source segments {unified_segments}.",
            evidence_segments_before=[list(q.source_segment_indices) for q in group],
            evidence_segments_after=unified_segments,
        )

        return reconciled_quote, record

    # -------------------------------------------------------------------------
    # List Reconciliation Algorithms (Deterministic Graph Clustering)
    # -------------------------------------------------------------------------

    def reconcile_insights(
        self, insights: Sequence[CandidateInsight]
    ) -> InsightReconciliationResult:
        """
        Reconciles a sequence of CandidateInsight items.

        DETERMINISTIC CLUSTER POLICY:
        1. Candidates are pre-sorted by a stable key prior to cluster evaluation.
        2. Pairwise duplicate edges are evaluated between all candidates.
        3. Connected components are identified.
        4. CLIQUE INVARIANT: A component is merged IF AND ONLY IF it forms a complete clique
           where every member is pairwise compatible with every other member.
        5. AMBIGUITY RESOLUTION: If A matches B and B matches C, but A does not match C
           (the component is not a clique), compatibility cannot be established across the group.
           Per Requirement 8, ambiguous bridging candidates are NOT arbitrarily merged with one side;
           all candidates in the ambiguous component are conservatively retained separately.
        """
        if not insights:
            return InsightReconciliationResult(insights=[], merge_records=[], index_map={})

        n = len(insights)
        if n == 1:
            single = insights[0]
            updated_single = CandidateInsight(
                title=single.title,
                category=single.category,
                summary=single.summary,
                takeaways=list(single.takeaways),
                practical_action=single.practical_action,
                evidence_segment_indices=list(single.evidence_segment_indices),
                confidence_score=single.confidence_score,
                display_order=0,
                review_status="candidate",
            )
            return InsightReconciliationResult(
                insights=[updated_single], merge_records=[], index_map={0: 0}
            )

        # Step 1: Pre-sort indexed items deterministically
        def pre_sort_key(item: Tuple[int, CandidateInsight]) -> Tuple[Any, ...]:
            orig_idx, ins = item
            return self._insight_canonical_sort_key(ins)

        indexed_insights = [(idx, ins) for idx, ins in enumerate(insights)]
        sorted_indexed = sorted(indexed_insights, key=pre_sort_key)

        # Step 2: Build duplicate adjacency matrix
        adj: Dict[int, Set[int]] = {i: set() for i in range(n)}
        for i in range(n):
            for j in range(i + 1, n):
                ins_i = sorted_indexed[i][1]
                ins_j = sorted_indexed[j][1]
                if self.are_duplicate_insights(ins_i, ins_j)[0]:
                    adj[i].add(j)
                    adj[j].add(i)

        # Step 3: Find connected components
        visited: Set[int] = set()
        components: List[List[int]] = []
        for i in range(n):
            if i not in visited:
                comp: List[int] = []
                queue = [i]
                visited.add(i)
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    for neighbor in sorted(adj[curr]):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)
                components.append(sorted(comp))

        # Step 4: Evaluate cliques vs ambiguous non-cliques
        clusters: List[List[Tuple[int, CandidateInsight]]] = []
        for comp in components:
            if len(comp) == 1:
                clusters.append([sorted_indexed[comp[0]]])
            else:
                # Verify clique: all pairs in component must have an edge
                is_clique = True
                for u_idx in range(len(comp)):
                    for v_idx in range(u_idx + 1, len(comp)):
                        u, v = comp[u_idx], comp[v_idx]
                        if v not in adj[u]:
                            is_clique = False
                            break
                    if not is_clique:
                        break

                if is_clique:
                    # Unambiguous duplicate cluster
                    clusters.append([sorted_indexed[k] for k in comp])
                else:
                    # Ambiguous bridge: retain candidates separately per Requirement 8
                    for k in comp:
                        clusters.append([sorted_indexed[k]])

        # Step 5: Merge clusters and collect merge records
        reconciled_clusters: List[Tuple[CandidateInsight, Optional[MergeRecord], List[int]]] = []
        for cluster in clusters:
            orig_indices = [item[0] for item in cluster]
            ins_items = [item[1] for item in cluster]
            merged_ins, record = self._merge_insight_group(ins_items)
            reconciled_clusters.append((merged_ins, record, orig_indices))

        # Step 6: Deterministic global ordering across reconciled items
        def ordering_key(entry: Tuple[CandidateInsight, Optional[MergeRecord], List[int]]) -> Tuple[Any, ...]:
            ins = entry[0]
            min_ev = min(ins.evidence_segment_indices) if ins.evidence_segment_indices else 999999
            return (
                min_ev,
                normalize_category(ins.category),
                normalize_text(ins.title),
                normalize_text(ins.summary),
                normalize_text(ins.practical_action),
            )

        sorted_reconciled = sorted(reconciled_clusters, key=ordering_key)

        final_insights: List[CandidateInsight] = []
        merge_records: List[MergeRecord] = []
        index_map: Dict[int, int] = {}

        for new_idx, (ins, record, orig_indices) in enumerate(sorted_reconciled):
            final_insights.append(
                CandidateInsight(
                    title=ins.title,
                    category=ins.category,
                    summary=ins.summary,
                    takeaways=list(ins.takeaways),
                    practical_action=ins.practical_action,
                    evidence_segment_indices=list(ins.evidence_segment_indices),
                    confidence_score=ins.confidence_score,
                    display_order=new_idx,
                    review_status="candidate",
                )
            )
            if record:
                merge_records.append(record)
            for old_idx in orig_indices:
                index_map[old_idx] = new_idx

        return InsightReconciliationResult(
            insights=final_insights, merge_records=merge_records, index_map=index_map
        )

    def reconcile_quotations(
        self, quotations: Sequence[CandidateQuotation]
    ) -> QuotationReconciliationResult:
        """
        Reconciles a sequence of CandidateQuotation items using deterministic clique-based clustering.
        """
        if not quotations:
            return QuotationReconciliationResult(quotations=[], merge_records=[], index_map={})

        n = len(quotations)
        if n == 1:
            single = quotations[0]
            updated_single = CandidateQuotation(
                amharic_quote=single.amharic_quote,
                english_translation=single.english_translation,
                speaker=single.speaker,
                source_segment_indices=list(single.source_segment_indices),
                canonical_start_ms=single.canonical_start_ms,
                canonical_timestamp_seconds=single.canonical_timestamp_seconds,
                context=single.context,
                reported_timestamp_seconds=single.reported_timestamp_seconds,
                has_timestamp_discrepancy=single.has_timestamp_discrepancy,
                importance_rationale=single.importance_rationale,
                display_order=0,
                review_status="candidate",
            )
            return QuotationReconciliationResult(
                quotations=[updated_single], merge_records=[], index_map={0: 0}
            )

        # Step 1: Pre-sort indexed quotations deterministically
        def pre_sort_key(item: Tuple[int, CandidateQuotation]) -> Tuple[Any, ...]:
            orig_idx, q = item
            return self._quotation_canonical_sort_key(q)

        indexed_quotes = [(idx, q) for idx, q in enumerate(quotations)]
        sorted_indexed = sorted(indexed_quotes, key=pre_sort_key)

        # Step 2: Build duplicate adjacency matrix
        adj: Dict[int, Set[int]] = {i: set() for i in range(n)}
        for i in range(n):
            for j in range(i + 1, n):
                q_i = sorted_indexed[i][1]
                q_j = sorted_indexed[j][1]
                if self.are_duplicate_quotations(q_i, q_j)[0]:
                    adj[i].add(j)
                    adj[j].add(i)

        # Step 3: Find connected components
        visited: Set[int] = set()
        components: List[List[int]] = []
        for i in range(n):
            if i not in visited:
                comp: List[int] = []
                queue = [i]
                visited.add(i)
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    for neighbor in sorted(adj[curr]):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)
                components.append(sorted(comp))

        # Step 4: Evaluate cliques vs ambiguous non-cliques
        clusters: List[List[Tuple[int, CandidateQuotation]]] = []
        for comp in components:
            if len(comp) == 1:
                clusters.append([sorted_indexed[comp[0]]])
            else:
                is_clique = True
                for u_idx in range(len(comp)):
                    for v_idx in range(u_idx + 1, len(comp)):
                        u, v = comp[u_idx], comp[v_idx]
                        if v not in adj[u]:
                            is_clique = False
                            break
                    if not is_clique:
                        break

                if is_clique:
                    clusters.append([sorted_indexed[k] for k in comp])
                else:
                    for k in comp:
                        clusters.append([sorted_indexed[k]])

        # Step 5: Merge clusters and collect merge records
        reconciled_clusters: List[Tuple[CandidateQuotation, Optional[MergeRecord], List[int]]] = []
        for cluster in clusters:
            orig_indices = [item[0] for item in cluster]
            q_items = [item[1] for item in cluster]
            merged_q, record = self._merge_quotation_group(q_items)
            reconciled_clusters.append((merged_q, record, orig_indices))

        # Step 6: Deterministic chronological ordering across reconciled quotations
        def ordering_key(entry: Tuple[CandidateQuotation, Optional[MergeRecord], List[int]]) -> Tuple[Any, ...]:
            q = entry[0]
            min_seg = min(q.source_segment_indices) if q.source_segment_indices else 999999
            return (
                q.canonical_start_ms,
                q.canonical_timestamp_seconds,
                min_seg,
                normalize_amharic_quote(q.amharic_quote),
                normalize_text(q.speaker),
                normalize_text(q.english_translation),
            )

        sorted_reconciled = sorted(reconciled_clusters, key=ordering_key)

        final_quotations: List[CandidateQuotation] = []
        merge_records: List[MergeRecord] = []
        index_map: Dict[int, int] = {}

        for new_idx, (q, record, orig_indices) in enumerate(sorted_reconciled):
            final_quotations.append(
                CandidateQuotation(
                    amharic_quote=q.amharic_quote,
                    english_translation=q.english_translation,
                    speaker=q.speaker,
                    source_segment_indices=list(q.source_segment_indices),
                    canonical_start_ms=q.canonical_start_ms,
                    canonical_timestamp_seconds=q.canonical_timestamp_seconds,
                    context=q.context,
                    reported_timestamp_seconds=q.reported_timestamp_seconds,
                    has_timestamp_discrepancy=q.has_timestamp_discrepancy,
                    importance_rationale=q.importance_rationale,
                    display_order=new_idx,
                    review_status="candidate",
                )
            )
            if record:
                merge_records.append(record)
            for old_idx in orig_indices:
                index_map[old_idx] = new_idx

        return QuotationReconciliationResult(
            quotations=final_quotations, merge_records=merge_records, index_map=index_map
        )

    # -------------------------------------------------------------------------
    # Full Payload Reconciliation
    # -------------------------------------------------------------------------

    def reconcile_payloads(
        self, payloads: Sequence[CandidateExtractionPayload]
    ) -> PayloadReconciliationResult:
        """
        Reconciles candidate knowledge items across multiple CandidateExtractionPayload objects.

        EVIDENCE REFERENCE PRESERVATION CONTRACT:
        - When remapping evidence references to new zero-based insight indices, existing
          claim_quote_snippet, notes, and per-reference relevance_score are strictly preserved.
        - Per-reference relevance_score is NEVER replaced with the insight confidence_score.
        - If multiple references collapse onto the same (insight_index, segment_index), a
          deterministic policy merges them:
            1. relevance_score: max non-null score across collapsed references.
            2. claim_quote_snippet: longest non-empty snippet (tie-broken by string value).
            3. notes: unique non-empty notes combined deterministically with '; '.
        """
        if not payloads:
            empty_payload = CandidateExtractionPayload(
                schema_version="1.0.0",
                episode_summary=CandidateSummary(brief="", comprehensive="", primary_themes=[]),
                guest_profile=CandidateGuestProfile(name="", title="", company="", bio="", industry=""),
                journey_milestones=[],
                insights=[],
                quotations=[],
                suggested_tags=[],
            )
            report = ReconciliationReport(
                total_insights_in=0,
                total_insights_out=0,
                insights_merged_count=0,
                total_quotations_in=0,
                total_quotations_out=0,
                quotations_merged_count=0,
                merge_records=[],
            )
            return PayloadReconciliationResult(payload=empty_payload, report=report, merge_records=[])

        all_insights: List[CandidateInsight] = []
        all_quotations: List[CandidateQuotation] = []
        all_milestones: List[CandidateMilestone] = []
        all_tags: List[str] = []

        for p in payloads:
            all_insights.extend(p.insights)
            all_quotations.extend(p.quotations)
            all_milestones.extend(p.journey_milestones)
            all_tags.extend(p.suggested_tags)

        # 1. Reconcile Insights with index mapping
        ins_result = self.reconcile_insights(all_insights)
        reconciled_insights = ins_result.insights
        insight_merge_records = ins_result.merge_records
        insight_index_map = ins_result.index_map

        # 2. Reconcile Quotations with index mapping
        q_result = self.reconcile_quotations(all_quotations)
        reconciled_quotations = q_result.quotations
        quote_merge_records = q_result.merge_records
        quote_index_map = q_result.index_map

        # 3. Remap CandidateEvidenceReferences preserving metadata
        # Group original references by (new_insight_idx, segment_index)
        grouped_refs: Dict[Tuple[int, int], List[CandidateEvidenceReference]] = defaultdict(list)
        insight_offset = 0
        for p in payloads:
            for ref in p.evidence_references:
                orig_global_idx = insight_offset + ref.insight_index
                new_ins_idx = insight_index_map.get(orig_global_idx)
                if new_ins_idx is not None:
                    grouped_refs[(new_ins_idx, ref.segment_index)].append(ref)
            insight_offset += len(p.insights)

        # Build final evidence references covering all cited segments in reconciled insights
        rebuilt_evidence: List[CandidateEvidenceReference] = []
        for new_ins_idx, ins in enumerate(reconciled_insights):
            for seg_idx in sorted(ins.evidence_segment_indices):
                matching_refs = grouped_refs.get((new_ins_idx, seg_idx), [])
                if not matching_refs:
                    # Fallback for evidence index added during merge that lacked explicit reference
                    rebuilt_evidence.append(
                        CandidateEvidenceReference(
                            insight_index=new_ins_idx,
                            segment_index=seg_idx,
                            relevance_score=None,
                            claim_quote_snippet=None,
                            notes=None,
                        )
                    )
                elif len(matching_refs) == 1:
                    r = matching_refs[0]
                    rebuilt_evidence.append(
                        CandidateEvidenceReference(
                            insight_index=new_ins_idx,
                            segment_index=seg_idx,
                            relevance_score=r.relevance_score,
                            claim_quote_snippet=r.claim_quote_snippet,
                            notes=r.notes,
                        )
                    )
                else:
                    # Deterministic collapse policy for duplicate references
                    scores = [r.relevance_score for r in matching_refs if r.relevance_score is not None]
                    best_score = max(scores) if scores else None

                    snippets = [r.claim_quote_snippet for r in matching_refs if r.claim_quote_snippet]
                    best_snippet = max(snippets, key=lambda s: (len(s), s)) if snippets else None

                    seen_notes: Set[str] = set()
                    unique_notes: List[str] = []
                    for r in matching_refs:
                        if r.notes and r.notes not in seen_notes:
                            seen_notes.add(r.notes)
                            unique_notes.append(r.notes)
                    combined_notes = "; ".join(unique_notes) if unique_notes else None

                    rebuilt_evidence.append(
                        CandidateEvidenceReference(
                            insight_index=new_ins_idx,
                            segment_index=seg_idx,
                            relevance_score=best_score,
                            claim_quote_snippet=best_snippet,
                            notes=combined_notes,
                        )
                    )

        # 4. Regenerate CandidateQuotationSegments for reconciled quotations
        rebuilt_quotation_segments: List[CandidateQuotationSegment] = []
        for new_q_idx, q in enumerate(reconciled_quotations):
            for seq_order, seg_idx in enumerate(q.source_segment_indices):
                rebuilt_quotation_segments.append(
                    CandidateQuotationSegment(
                        quotation_index=new_q_idx,
                        segment_index=seg_idx,
                        sequence_order=seq_order,
                    )
                )

        # 5. Deduplicate Milestones conservatively (matching phase_or_year + description)
        unique_milestones: List[CandidateMilestone] = []
        seen_milestone_keys: Set[Tuple[str, str]] = set()
        for m in all_milestones:
            key = (normalize_text(m.phase_or_year), normalize_text(m.milestone_description))
            if key not in seen_milestone_keys:
                seen_milestone_keys.add(key)
                unique_milestones.append(m)

        # 6. Deduplicate Suggested Tags (preserving order)
        seen_tags: Set[str] = set()
        deduped_tags: List[str] = []
        for t in all_tags:
            norm_t = normalize_text(t)
            if norm_t and norm_t not in seen_tags:
                seen_tags.add(norm_t)
                deduped_tags.append(t)

        # 7. Select canonical summary and guest profile (longest / most comprehensive)
        canonical_summary = max(
            (p.episode_summary for p in payloads),
            key=lambda s: len(s.comprehensive or "") + len(s.brief or ""),
        )
        canonical_guest = max(
            (p.guest_profile for p in payloads),
            key=lambda g: len(g.bio or "") + len(g.name or ""),
        )

        reconciled_payload = CandidateExtractionPayload(
            schema_version=payloads[0].schema_version,
            episode_summary=canonical_summary,
            guest_profile=canonical_guest,
            journey_milestones=unique_milestones,
            insights=reconciled_insights,
            quotations=reconciled_quotations,
            suggested_tags=deduped_tags,
            evidence_references=rebuilt_evidence,
            quotation_segments=rebuilt_quotation_segments,
        )

        all_merge_records = list(insight_merge_records) + list(quote_merge_records)

        report = ReconciliationReport(
            total_insights_in=len(all_insights),
            total_insights_out=len(reconciled_insights),
            insights_merged_count=len(all_insights) - len(reconciled_insights),
            total_quotations_in=len(all_quotations),
            total_quotations_out=len(reconciled_quotations),
            quotations_merged_count=len(all_quotations) - len(reconciled_quotations),
            merge_records=all_merge_records,
        )

        return PayloadReconciliationResult(
            payload=reconciled_payload, report=report, merge_records=all_merge_records
        )

    def reconcile_payload(
        self, payload: CandidateExtractionPayload
    ) -> PayloadReconciliationResult:
        """Helper to reconcile a single payload with potential internal duplicates."""
        return self.reconcile_payloads([payload])


# Global default reconciler instance and module convenience functions
_default_reconciler = CandidateReconciler()


def reconcile_insights(
    insights: Sequence[CandidateInsight],
) -> InsightReconciliationResult:
    """Convenience function dispatching to CandidateReconciler.reconcile_insights."""
    return _default_reconciler.reconcile_insights(insights)


def reconcile_quotations(
    quotations: Sequence[CandidateQuotation],
) -> QuotationReconciliationResult:
    """Convenience function dispatching to CandidateReconciler.reconcile_quotations."""
    return _default_reconciler.reconcile_quotations(quotations)


def reconcile_payloads(
    payloads: Sequence[CandidateExtractionPayload],
) -> PayloadReconciliationResult:
    """Convenience function dispatching to CandidateReconciler.reconcile_payloads."""
    return _default_reconciler.reconcile_payloads(payloads)


def reconcile_payload(
    payload: CandidateExtractionPayload,
) -> PayloadReconciliationResult:
    """Convenience function dispatching to CandidateReconciler.reconcile_payload."""
    return _default_reconciler.reconcile_payload(payload)
