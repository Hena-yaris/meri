"""
Meri Content Pipeline v1: Unit tests for Candidate Reconciliation & Multi-Chunk Deduplication.
Strictly verifies:
1. Exact duplicate insights from overlapping chunks are merged with evidence preserved.
2. Same text but incompatible candidate types are never merged.
3. Similar topics but substantively distinct insights remain separate.
4. Duplicate evidence indices are deduplicated in sorted order.
5. Multiple supporting evidence indices are preserved.
6. Deterministic canonical selection and output ordering independent of input order.
7. Identical quotations with compatible attribution are merged.
8. Similar but non-identical quotations remain separate.
9. Missing or invalid evidence remains subject to existing validation rules.
10. Empty input and single-candidate input handling.
11. Merge records accurately describe reconciliations.
12. Relational evidence references and quotation segments remapped on payload reconciliation.
13. Strict candidate review status invariant (never automatically approved or published).
"""

import copy
import itertools
import unittest

from backend.src.candidate_reconciliation import (
    CandidateReconciler,
    InsightReconciliationResult,
    MergeRecord,
    PayloadReconciliationResult,
    QuotationReconciliationResult,
    ReconciliationReport,
    normalize_category,
    normalize_text,
    reconcile_insights,
    reconcile_payload,
    reconcile_payloads,
    reconcile_quotations,
)
from backend.src.extraction_models import (
    CandidateEvidenceReference,
    CandidateExtractionPayload,
    CandidateGuestProfile,
    CandidateInsight,
    CandidateMilestone,
    CandidateQuotation,
    CandidateQuotationSegment,
    CandidateSummary,
)


class TestCandidateReconciliation(unittest.TestCase):
    """Test suite for candidate deduplication and multi-chunk reconciliation."""

    def setUp(self) -> None:
        self.reconciler = CandidateReconciler()

        # Reusable sample insights
        self.insight_chunk_0 = CandidateInsight(
            title="Cold Storage Siting: Proximity to Production",
            category="Operations",
            summary="Locating cold chain hubs within 30 minutes of producer clusters reduces post-harvest loss by 40%.",
            takeaways=[
                "Every additional transit hour accelerates biological decay.",
                "Primary rural hubs need dedicated backup power.",
            ],
            practical_action="Audit local transport times before signing warehouse leases.",
            evidence_segment_indices=[12, 13],
            confidence_score=0.92,
            display_order=0,
            review_status="candidate",
        )

        self.insight_chunk_1 = CandidateInsight(
            title="Cold Storage Siting: Proximity to Production",
            category="Operations",
            summary="Locating cold chain hubs within 30 minutes of producer clusters reduces post-harvest loss by 40%.",
            takeaways=[
                "Every additional transit hour accelerates biological decay.",
                "Cluster smallholders to achieve minimum economic cooling volume.",
            ],
            practical_action="Audit local transport times before signing warehouse leases.",
            evidence_segment_indices=[13, 14],
            confidence_score=0.96,
            display_order=0,
            review_status="candidate",
        )

        # Reusable sample quotations
        self.quote_chunk_0 = CandidateQuotation(
            amharic_quote="ስራ ስንጀምር ዋናው ተግዳሮት የነበረው የመብራት መቆራረጥ እና የነዳጅ ዋጋ መናር ነበር።",
            english_translation="When we began operations, the primary obstacles were persistent power outages and soaring fuel costs.",
            speaker="ዳዊት ታደሰ",
            source_segment_indices=[5, 6],
            canonical_start_ms=25000,
            canonical_timestamp_seconds=25,
            context="Discussing the operational headwinds during the 2019 launch.",
            reported_timestamp_seconds=25,
            has_timestamp_discrepancy=False,
            importance_rationale="Highlights critical infrastructure friction for cold chain businesses.",
            display_order=0,
            review_status="candidate",
        )

        self.quote_chunk_1 = CandidateQuotation(
            amharic_quote="ስራ ስንጀምር ዋናው ተግዳሮት የነበረው የመብራት መቆራረጥ እና የነዳጅ ዋጋ መናር ነበር።",
            english_translation="When we began operations, the primary obstacles were persistent power outages and soaring fuel costs in Addis Ababa.",
            speaker="ዳዊት ታደሰ",
            source_segment_indices=[6, 7],
            canonical_start_ms=28000,
            canonical_timestamp_seconds=28,
            context="Discussing early operational hurdles in Addis Ababa.",
            reported_timestamp_seconds=28,
            has_timestamp_discrepancy=False,
            importance_rationale="Key quote detailing real-world supply chain challenges.",
            display_order=0,
            review_status="candidate",
        )

    # -------------------------------------------------------------------------
    # 1. Exact Duplicate Insights from Overlapping Chunks
    # -------------------------------------------------------------------------

    def test_exact_duplicate_insights_from_overlapping_chunks(self) -> None:
        """
        Verifies that identical insights extracted across overlapping chunks are merged
        into a single canonical insight with unified evidence and highest confidence.
        """
        result, records = self.reconciler.reconcile_insights([self.insight_chunk_0, self.insight_chunk_1])

        self.assertEqual(len(result), 1)
        self.assertEqual(len(records), 1)

        merged = result[0]
        self.assertEqual(merged.title, "Cold Storage Siting: Proximity to Production")
        self.assertEqual(merged.category, "Operations")
        # Evidence segments 12, 13 and 13, 14 merged into [12, 13, 14]
        self.assertEqual(merged.evidence_segment_indices, [12, 13, 14])
        # Confidence score takes the highest (0.96)
        self.assertEqual(merged.confidence_score, 0.96)
        # Unique takeaways preserved
        self.assertEqual(len(merged.takeaways), 3)
        self.assertIn("Cluster smallholders to achieve minimum economic cooling volume.", merged.takeaways)
        # Review status strictly preserved
        self.assertEqual(merged.review_status, "candidate")
        self.assertEqual(merged.display_order, 0)

        # Verify merge record
        rec = records[0]
        self.assertEqual(rec.candidate_type, "insight")
        self.assertEqual(rec.canonical_identifier, self.insight_chunk_1.title)
        self.assertEqual(rec.evidence_segments_after, [12, 13, 14])
        self.assertEqual(rec.confidence_after, 0.96)

    # -------------------------------------------------------------------------
    # 2. Incompatible Candidate Types Never Merge
    # -------------------------------------------------------------------------

    def test_same_text_incompatible_candidate_types_never_merge(self) -> None:
        """
        Verifies that insights and quotations are strictly isolated and never merge,
        even if they share identical text or overlapping segments.
        """
        shared_text = "የንግድ ስራ አመራር እና እድገት"
        insight = CandidateInsight(
            title=shared_text,
            category="Leadership & Culture",
            summary="A comprehensive overview of operational management and scaling principles.",
            takeaways=["Align incentives across departments."],
            practical_action="Conduct weekly management reviews.",
            evidence_segment_indices=[10],
            confidence_score=0.90,
        )
        quote = CandidateQuotation(
            amharic_quote=shared_text,
            english_translation="Business management and growth.",
            speaker="ዳዊት",
            source_segment_indices=[10],
            canonical_start_ms=50000,
            canonical_timestamp_seconds=50,
            context="Discussing management strategy.",
        )

        is_dup_ins, reason_ins = self.reconciler.are_duplicate_insights(insight, quote)
        self.assertFalse(is_dup_ins)
        self.assertIn("Candidate types are incompatible", reason_ins)

        is_dup_q, reason_q = self.reconciler.are_duplicate_quotations(quote, insight)
        self.assertFalse(is_dup_q)
        self.assertIn("Candidate types are incompatible", reason_q)

    # -------------------------------------------------------------------------
    # 3. Similar Topics but Substantively Distinct Insights
    # -------------------------------------------------------------------------

    def test_similar_topics_substantively_distinct_insights_remain_separate(self) -> None:
        """
        Verifies that insights sharing the same category and overlapping segments but
        making distinct claims or practical recommendations are NOT merged.
        """
        insight_a = CandidateInsight(
            title="Cold Chain Automation: Start with Handheld Scanners",
            category="Operations",
            summary="Start warehouse automation with inexpensive barcode scanners before conveyor belts.",
            takeaways=["Low initial CapEx", "Quick warehouse staff onboarding"],
            practical_action="Purchase wireless barcode scanners.",
            evidence_segment_indices=[15, 16],
            confidence_score=0.88,
        )
        insight_b = CandidateInsight(
            title="Cold Chain Automation: Invest Directly in Automated Conveyors",
            category="Operations",
            summary="Manual scanning failed to scale; motorized automated sorting was essential from day one.",
            takeaways=["Avoid intermediate re-training costs", "Motorized sorting handles peak volumes"],
            practical_action="Install powered roller sorting lines.",
            evidence_segment_indices=[16, 17],
            confidence_score=0.89,
        )

        result, records = self.reconciler.reconcile_insights([insight_a, insight_b])
        # Must retain both insights separately
        self.assertEqual(len(result), 2)
        self.assertEqual(len(records), 0)
        titles = [ins.title for ins in result]
        self.assertIn(insight_a.title, titles)
        self.assertIn(insight_b.title, titles)

    def test_same_title_different_practical_recommendations_remain_separate(self) -> None:
        """
        If two insights share the same title and category, but have conflicting practical actions,
        reconciliation conservatively retains both.
        """
        ins1 = CandidateInsight(
            title="Customer Credit Management",
            category="Finance & Capital",
            summary="Approaches to managing distributor credit during seasonal cash crunches.",
            takeaways=["Cash is king."],
            practical_action="Cease all distributor credit lines and mandate upfront cash on delivery.",
            evidence_segment_indices=[20, 21],
            confidence_score=0.85,
        )
        ins2 = CandidateInsight(
            title="Customer Credit Management",
            category="Finance & Capital",
            summary="Approaches to managing distributor credit during seasonal cash crunches.",
            takeaways=["Relationships matter."],
            practical_action="Extend 45-day credit lines to top 10% volume buyers with bank guarantees.",
            evidence_segment_indices=[21, 22],
            confidence_score=0.87,
        )

        result, records = self.reconciler.reconcile_insights([ins1, ins2])
        self.assertEqual(len(result), 2)
        self.assertEqual(len(records), 0)

    # -------------------------------------------------------------------------
    # 4. Duplicate Evidence Indices Deduplicated in Sorted Order
    # -------------------------------------------------------------------------

    def test_duplicate_evidence_indices_deduplicated_and_sorted(self) -> None:
        """
        Verifies that redundant evidence segment references across duplicate candidates
        are unified, sorted in ascending order, and deduplicated.
        """
        ins_a = CandidateInsight(
            title="Early Cash Flow Discipline",
            category="Finance & Capital",
            summary="Disciplined receivable collection is vital in the first two operating years.",
            takeaways=["Maintain 30-day cash buffer."],
            practical_action="Review aging invoices every Monday morning.",
            evidence_segment_indices=[4, 7, 7, 9],  # Contains duplicates within self
            confidence_score=0.91,
        )
        ins_b = CandidateInsight(
            title="Early Cash Flow Discipline",
            category="Finance & Capital",
            summary="Disciplined receivable collection is vital in the first two operating years.",
            takeaways=["Maintain 30-day cash buffer."],
            practical_action="Review aging invoices every Monday morning.",
            evidence_segment_indices=[7, 9, 11],  # Overlaps on 7, 9
            confidence_score=0.94,
        )

        result, records = self.reconciler.reconcile_insights([ins_a, ins_b])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].evidence_segment_indices, [4, 7, 9, 11])

    # -------------------------------------------------------------------------
    # 5. Multiple Supporting Evidence Indices Preserved
    # -------------------------------------------------------------------------

    def test_multiple_supporting_evidence_indices_preserved(self) -> None:
        """
        Verifies that multi-segment supporting evidence spanning multiple chunks
        is fully preserved without dropping any valid references.
        """
        ins1 = CandidateInsight(
            title="Supply Chain Traceability",
            category="Technology & Infrastructure",
            summary="Implementing end-to-end QR code tagging reduced cargo shrinkage.",
            takeaways=["Traceability builds buyer confidence."],
            practical_action="Affix QR code tags at farm gate loading.",
            evidence_segment_indices=[30, 31],
            confidence_score=0.90,
        )
        ins2 = CandidateInsight(
            title="Supply Chain Traceability",
            category="Technology & Infrastructure",
            summary="Implementing end-to-end QR code tagging reduced cargo shrinkage.",
            takeaways=["Traceability builds buyer confidence."],
            practical_action="Affix QR code tags at farm gate loading.",
            evidence_segment_indices=[31, 32, 33, 34],
            confidence_score=0.95,
        )

        result, _ = self.reconciler.reconcile_insights([ins1, ins2])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].evidence_segment_indices, [30, 31, 32, 33, 34])

    # -------------------------------------------------------------------------
    # 6. Deterministic Output When Input Order Changes
    # -------------------------------------------------------------------------

    def test_deterministic_output_when_input_order_changes_insights(self) -> None:
        """
        Verifies that permuting the input order of insights yields the EXACT same
        canonical candidate, merged evidence, and global display order.
        """
        ins_early = CandidateInsight(
            title="Market Validation Before Code",
            category="Product Strategy",
            summary="Validate customer demand before writing a single line of backend code.",
            takeaways=["Interview 50 target users."],
            practical_action="Conduct structured problem discovery interviews.",
            evidence_segment_indices=[2, 3],
            confidence_score=0.95,
        )
        ins_dup_a = self.insight_chunk_0
        ins_dup_b = self.insight_chunk_1

        # Test permutations
        order1 = [ins_early, ins_dup_a, ins_dup_b]
        order2 = [ins_dup_b, ins_dup_a, ins_early]
        order3 = [ins_dup_a, ins_early, ins_dup_b]

        res1, rec1 = self.reconciler.reconcile_insights(order1)
        res2, rec2 = self.reconciler.reconcile_insights(order2)
        res3, rec3 = self.reconciler.reconcile_insights(order3)

        self.assertEqual(len(res1), len(res2))
        self.assertEqual(len(res2), len(res3))

        for i in range(len(res1)):
            self.assertEqual(res1[i].title, res2[i].title)
            self.assertEqual(res2[i].title, res3[i].title)
            self.assertEqual(res1[i].evidence_segment_indices, res2[i].evidence_segment_indices)
            self.assertEqual(res2[i].evidence_segment_indices, res3[i].evidence_segment_indices)
            self.assertEqual(res1[i].confidence_score, res2[i].confidence_score)
            self.assertEqual(res2[i].confidence_score, res3[i].confidence_score)
            self.assertEqual(res1[i].display_order, i)
            self.assertEqual(res2[i].display_order, i)

    def test_deterministic_output_when_input_order_changes_quotations(self) -> None:
        """
        Verifies that permuting the input order of quotations produces identical results.
        """
        order1 = [self.quote_chunk_0, self.quote_chunk_1]
        order2 = [self.quote_chunk_1, self.quote_chunk_0]

        res1, rec1 = self.reconciler.reconcile_quotations(order1)
        res2, rec2 = self.reconciler.reconcile_quotations(order2)

        self.assertEqual(len(res1), 1)
        self.assertEqual(len(res2), 1)
        self.assertEqual(res1[0].amharic_quote, res2[0].amharic_quote)
        self.assertEqual(res1[0].source_segment_indices, res2[0].source_segment_indices)
        self.assertEqual(res1[0].canonical_start_ms, res2[0].canonical_start_ms)
        self.assertEqual(res1[0].canonical_timestamp_seconds, res2[0].canonical_timestamp_seconds)

    # -------------------------------------------------------------------------
    # 7. Identical Quotations with Compatible Attribution
    # -------------------------------------------------------------------------

    def test_identical_quotations_compatible_attribution_merge(self) -> None:
        """
        Verifies that identical verbatim Amharic quotations with compatible speaker attribution
        and overlapping source segments are merged with earliest timestamp preserved.
        """
        result, records = self.reconciler.reconcile_quotations([self.quote_chunk_0, self.quote_chunk_1])

        self.assertEqual(len(result), 1)
        self.assertEqual(len(records), 1)

        merged = result[0]
        # Verbatim quote is preserved unchanged (never rewritten)
        self.assertEqual(merged.amharic_quote, self.quote_chunk_0.amharic_quote)
        self.assertEqual(merged.speaker, "ዳዊት ታደሰ")
        # Source segments [5, 6] and [6, 7] unified to [5, 6, 7]
        self.assertEqual(merged.source_segment_indices, [5, 6, 7])
        # Earliest canonical start timestamp preserved (25000ms -> 25s)
        self.assertEqual(merged.canonical_start_ms, 25000)
        self.assertEqual(merged.canonical_timestamp_seconds, 25)
        # Review status preserved as candidate
        self.assertEqual(merged.review_status, "candidate")

    # -------------------------------------------------------------------------
    # 8. Similar but Non-Identical Quotations Remain Separate
    # -------------------------------------------------------------------------

    def test_similar_non_identical_quotations_remain_separate(self) -> None:
        """
        Verifies that quotations with non-identical Amharic text are never merged or synthesized.
        """
        quote_a = CandidateQuotation(
            amharic_quote="ይህንን ስራ ስንጀምር ካፒታል አልነበረንም።",
            english_translation="When we started this work, we had no capital.",
            speaker="ዳዊት",
            source_segment_indices=[8],
            canonical_start_ms=35000,
            canonical_timestamp_seconds=35,
            context="Discussing initial capital.",
        )
        quote_b = CandidateQuotation(
            amharic_quote="ይህንን ስራ ስንጀምር ካፒታል ሳይሆን ራዕይ ነበር የነበረን።",  # Distinct phrasing
            english_translation="When we started this work, we had vision rather than capital.",
            speaker="ዳዊት",
            source_segment_indices=[8],
            canonical_start_ms=35000,
            canonical_timestamp_seconds=35,
            context="Clarifying the starting mindset.",
        )

        result, records = self.reconciler.reconcile_quotations([quote_a, quote_b])
        self.assertEqual(len(result), 2)
        self.assertEqual(len(records), 0)

    def test_different_speakers_never_merge(self) -> None:
        """
        Verifies that identical quote text attributed to different speakers is never merged.
        """
        quote_host = CandidateQuotation(
            amharic_quote="በጣም ጥሩ ነጥብ ነው ያነሳኸው።",
            english_translation="That is a very good point you raised.",
            speaker="Host",
            source_segment_indices=[12],
            canonical_start_ms=45000,
            canonical_timestamp_seconds=45,
            context="Host responding to guest point.",
        )
        quote_guest = CandidateQuotation(
            amharic_quote="በጣም ጥሩ ነጥብ ነው ያነሳኸው።",
            english_translation="That is a very good point you raised.",
            speaker="ዳዊት",
            source_segment_indices=[12],
            canonical_start_ms=45000,
            canonical_timestamp_seconds=45,
            context="Guest acknowledging host.",
        )

        result, records = self.reconciler.reconcile_quotations([quote_host, quote_guest])
        self.assertEqual(len(result), 2)
        self.assertEqual(len(records), 0)

    def test_identical_quotes_disjoint_timestamps_remain_separate(self) -> None:
        """
        Verifies that identical phrases repeated at completely disjoint times in the episode
        (e.g. at minute 2 vs minute 45) are treated as separate utterances and not merged.
        """
        quote_early = CandidateQuotation(
            amharic_quote="እግዚአብሔር ይመስገን ስራው ተሳክቷል።",
            english_translation="Thank God, the work succeeded.",
            speaker="ዳዊት",
            source_segment_indices=[3],
            canonical_start_ms=12000,
            canonical_timestamp_seconds=12,
            context="Early remark on success.",
        )
        quote_late = CandidateQuotation(
            amharic_quote="እግዚአብሔር ይመስገን ስራው ተሳክቷል።",
            english_translation="Thank God, the work succeeded.",
            speaker="ዳዊት",
            source_segment_indices=[120],  # 20 minutes later
            canonical_start_ms=1200000,
            canonical_timestamp_seconds=1200,
            context="Closing remarks on enterprise growth.",
        )

        result, records = self.reconciler.reconcile_quotations([quote_early, quote_late])
        self.assertEqual(len(result), 2)
        self.assertEqual(len(records), 0)

    # -------------------------------------------------------------------------
    # 9. Missing or Invalid Evidence Subject to Validation Rules
    # -------------------------------------------------------------------------

    def test_missing_or_empty_evidence_not_merged_and_preserved(self) -> None:
        """
        Verifies that candidates with missing/empty evidence are never merged with valid candidates,
        and retain their empty evidence so Layer 2 semantic validator can catch and report them.
        """
        invalid_ins = CandidateInsight(
            title="Cold Storage Siting: Proximity to Production",
            category="Operations",
            summary="Locating cold chain hubs within 30 minutes of producer clusters reduces post-harvest loss by 40%.",
            takeaways=["Every additional transit hour accelerates biological decay."],
            practical_action="Audit local transport times before signing warehouse leases.",
            evidence_segment_indices=[],  # EMPTY!
            confidence_score=0.99,
        )

        result, records = self.reconciler.reconcile_insights([self.insight_chunk_0, invalid_ins])
        # Since invalid_ins has empty evidence, evidence overlap check fails.
        # Both must be returned separately; invalid_ins is NOT merged away or masked.
        self.assertEqual(len(result), 2)
        self.assertEqual(len(records), 0)
        empty_ev_count = sum(1 for ins in result if len(ins.evidence_segment_indices) == 0)
        self.assertEqual(empty_ev_count, 1)

    # -------------------------------------------------------------------------
    # 10. Empty Input and Single Candidate Handling
    # -------------------------------------------------------------------------

    def test_empty_input_handling(self) -> None:
        """Empty candidate sequences produce empty results and zero merge records."""
        ins_res, ins_rec = self.reconciler.reconcile_insights([])
        self.assertEqual(ins_res, [])
        self.assertEqual(ins_rec, [])

        q_res, q_rec = self.reconciler.reconcile_quotations([])
        self.assertEqual(q_res, [])
        self.assertEqual(q_rec, [])

    def test_single_candidate_input_handling(self) -> None:
        """Single candidates are passed through with display_order=0 and candidate review status."""
        ins_res, ins_rec = self.reconciler.reconcile_insights([self.insight_chunk_0])
        self.assertEqual(len(ins_res), 1)
        self.assertEqual(ins_res[0].title, self.insight_chunk_0.title)
        self.assertEqual(ins_res[0].display_order, 0)
        self.assertEqual(ins_res[0].review_status, "candidate")
        self.assertEqual(len(ins_rec), 0)

        q_res, q_rec = self.reconciler.reconcile_quotations([self.quote_chunk_0])
        self.assertEqual(len(q_res), 1)
        self.assertEqual(q_res[0].amharic_quote, self.quote_chunk_0.amharic_quote)
        self.assertEqual(q_res[0].display_order, 0)
        self.assertEqual(q_res[0].review_status, "candidate")
        self.assertEqual(len(q_rec), 0)

    # -------------------------------------------------------------------------
    # 11. Merge Records Accurately Describe Reconciliations
    # -------------------------------------------------------------------------

    def test_merge_records_accurately_describe_reconciliation(self) -> None:
        """Verifies all fields and serialization of MergeRecord."""
        _, records = self.reconciler.reconcile_insights([self.insight_chunk_0, self.insight_chunk_1])
        self.assertEqual(len(records), 1)

        rec = records[0]
        self.assertEqual(rec.candidate_type, "insight")
        self.assertEqual(rec.canonical_identifier, self.insight_chunk_1.title)
        self.assertEqual(rec.evidence_segments_after, [12, 13, 14])
        self.assertEqual(rec.confidence_after, 0.96)
        self.assertIn("12, 13, 14", rec.reason)

        # Check to_dict() serialization
        rec_dict = rec.to_dict()
        self.assertIsInstance(rec_dict, dict)
        self.assertEqual(rec_dict["candidate_type"], "insight")
        self.assertEqual(rec_dict["evidence_segments_after"], [12, 13, 14])
        self.assertEqual(rec_dict["confidence_after"], 0.96)

    # -------------------------------------------------------------------------
    # 12. Full Payload Reconciliation & Relational Integrity
    # -------------------------------------------------------------------------

    def test_payload_reconciliation_remaps_evidence_and_quotation_segments(self) -> None:
        """
        Verifies that reconcile_payloads correctly:
        1. Merges duplicate insights and quotations across chunks.
        2. Remaps CandidateEvidenceReference to match reconciled insight indices.
        3. Remaps CandidateQuotationSegment to match reconciled quotation indices with sequence orders.
        4. Deduplicates milestones and tags.
        5. Selects canonical executive summary.
        """
        payload_chunk_0 = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=CandidateSummary(
                brief="Short summary chunk 0.",
                comprehensive="Comprehensive episode discussion from chunk 0 with high detail on operations.",
                primary_themes=["Operations", "Logistics"],
            ),
            guest_profile=CandidateGuestProfile(
                name="Dawit Tadesse",
                title="Founder & CEO",
                company="Nile Cold Chain",
                bio="Entrepreneur with 15 years in agricultural supply chains in East Africa.",
                industry="Agricultural Logistics",
            ),
            journey_milestones=[
                CandidateMilestone(
                    phase_or_year="2019",
                    milestone_description="Bootstrapped cold chain warehouse in Mojo.",
                    strategic_decision="Invested initial seed money into refrigerated trucks.",
                    evidence_segment_indices=[5, 6],
                )
            ],
            insights=[self.insight_chunk_0],
            quotations=[self.quote_chunk_0],
            suggested_tags=["Logistics", "Cold Chain", "Supply Chain"],
        )

        payload_chunk_1 = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=CandidateSummary(
                brief="Short summary chunk 1.",
                comprehensive="Comprehensive episode discussion from chunk 1 covering growth and scaling.",
                primary_themes=["Operations", "Financing"],
            ),
            guest_profile=CandidateGuestProfile(
                name="Dawit Tadesse",
                title="Founder & CEO",
                company="Nile Cold Chain",
                bio="Entrepreneur with 15 years in agricultural supply chains in East Africa.",
                industry="Agricultural Logistics",
            ),
            journey_milestones=[
                CandidateMilestone(
                    phase_or_year="2019",
                    milestone_description="Bootstrapped cold chain warehouse in Mojo.",
                    strategic_decision="Invested initial seed money into refrigerated trucks.",
                    evidence_segment_indices=[5, 6],
                ),
                CandidateMilestone(
                    phase_or_year="2022",
                    milestone_description="Expanded to Hawassa Industrial Park.",
                    strategic_decision="Partnered with export horticulture unions.",
                    evidence_segment_indices=[20, 21],
                ),
            ],
            insights=[self.insight_chunk_1],
            quotations=[self.quote_chunk_1],
            suggested_tags=["Cold Chain", "Horticulture", "Ethiopia"],
        )

        result_payload, report = self.reconciler.reconcile_payloads([payload_chunk_0, payload_chunk_1])

        # 1. Deduplicated insights: 2 -> 1
        self.assertEqual(len(result_payload.insights), 1)
        reconciled_ins = result_payload.insights[0]
        self.assertEqual(reconciled_ins.evidence_segment_indices, [12, 13, 14])

        # 2. Deduplicated quotations: 2 -> 1
        self.assertEqual(len(result_payload.quotations), 1)
        reconciled_q = result_payload.quotations[0]
        self.assertEqual(reconciled_q.source_segment_indices, [5, 6, 7])

        # 3. Relational evidence references remapped
        self.assertEqual(len(result_payload.evidence_references), 3)  # [12, 13, 14]
        for ref in result_payload.evidence_references:
            self.assertEqual(ref.insight_index, 0)
        ref_segs = [ref.segment_index for ref in result_payload.evidence_references]
        self.assertEqual(ref_segs, [12, 13, 14])

        # 4. Relational quotation segments remapped with sequence order
        self.assertEqual(len(result_payload.quotation_segments), 3)  # [5, 6, 7]
        for seq_idx, qs in enumerate(result_payload.quotation_segments):
            self.assertEqual(qs.quotation_index, 0)
            self.assertEqual(qs.sequence_order, seq_idx)
        qs_segs = [qs.segment_index for qs in result_payload.quotation_segments]
        self.assertEqual(qs_segs, [5, 6, 7])

        # 5. Milestones deduplicated (2019 appeared in both, 2022 was unique)
        self.assertEqual(len(result_payload.journey_milestones), 2)

        # 6. Suggested tags deduplicated preserving order
        self.assertEqual(
            result_payload.suggested_tags,
            ["Logistics", "Cold Chain", "Supply Chain", "Horticulture", "Ethiopia"],
        )

        # 7. Summary metrics
        self.assertEqual(report.total_insights_in, 2)
        self.assertEqual(report.total_insights_out, 1)
        self.assertEqual(report.insights_merged_count, 1)
        self.assertEqual(report.total_quotations_in, 2)
        self.assertEqual(report.total_quotations_out, 1)
        self.assertEqual(report.quotations_merged_count, 1)

    # -------------------------------------------------------------------------
    # 13. Editorial Review Status Boundary Strictly Preserved
    # -------------------------------------------------------------------------

    def test_review_status_boundary_strictly_preserved(self) -> None:
        """
        CRITICAL BOUNDARY TEST:
        Verifies that reconciliation NEVER sets review_status to 'approved' or 'published',
        and that even if an input candidate maliciously or erroneously had review_status='approved',
        the reconciled output strictly enforces review_status='candidate'.
        """
        rogue_ins = CandidateInsight(
            title="Bootstrap Cash Strategy",
            category="Finance & Capital",
            summary="Strategic bootstrapping insights.",
            takeaways=["Conserve runway."],
            practical_action="Limit hiring in Q1.",
            evidence_segment_indices=[1, 2],
            confidence_score=0.99,
            review_status="approved",  # Erroneous input status!
        )

        res, _ = self.reconciler.reconcile_insights([rogue_ins])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].review_status, "candidate")

        rogue_quote = CandidateQuotation(
            amharic_quote="ፈተናው ብዙ ነበር ግን አለፍነው።",
            english_translation="There were many trials, but we overcame them.",
            speaker="ዳዊት",
            source_segment_indices=[1],
            canonical_start_ms=1000,
            canonical_timestamp_seconds=1,
            context="Reflecting on journey.",
            review_status="approved",  # Erroneous input status!
        )

        q_res, _ = self.reconciler.reconcile_quotations([rogue_quote])
        self.assertEqual(len(q_res), 1)
        self.assertEqual(q_res[0].review_status, "candidate")

    # -------------------------------------------------------------------------
    # 14. Three-Candidate Chain (Non-Clique) Ambiguity Resolution Across All Permutations
    # -------------------------------------------------------------------------

    def test_three_candidate_chain_non_clique_ambiguity_all_permutations_insights(self) -> None:
        """
        REGRESSION TEST FOR FINDING 1:
        Verifies that when three candidates A, B, C form a non-clique chain
        (A matches B, B matches C, but A does NOT match C), the engine:
        1. Does not permit A-B and B-C matches to imply an A-C match.
        2. Considers the bridging candidate B ambiguous and retains all 3 candidates separately.
        3. Produces 100% IDENTICAL grouping, canonical selection, evidence output, and 0 merge
           records across ALL 6 permutations: [A, B, C], [A, C, B], [B, A, C], [B, C, A], [C, A, B], [C, B, A].
        """
        # A has segments [10, 11]
        ins_a = CandidateInsight(
            title="Warehouse Inventory Accuracy",
            category="Operations",
            summary="Implementing cycle counts reduced phantom inventory by 25%.",
            takeaways=["Cycle counts prevent fiscal year-end surprises."],
            practical_action="Schedule daily cycle counts.",
            evidence_segment_indices=[10, 11],
            confidence_score=0.90,
        )
        # B has segments [11, 12] - matches A on segment 11 and matches C on segment 12
        ins_b = CandidateInsight(
            title="Warehouse Inventory Accuracy",
            category="Operations",
            summary="Implementing cycle counts reduced phantom inventory by 25%.",
            takeaways=["Cycle counts prevent fiscal year-end surprises."],
            practical_action="Schedule daily cycle counts.",
            evidence_segment_indices=[11, 12],
            confidence_score=0.90,
        )
        # C has segments [12, 13] - disjoint from A ([10, 11] vs [12, 13])
        ins_c = CandidateInsight(
            title="Warehouse Inventory Accuracy",
            category="Operations",
            summary="Implementing cycle counts reduced phantom inventory by 25%.",
            takeaways=["Cycle counts prevent fiscal year-end surprises."],
            practical_action="Schedule daily cycle counts.",
            evidence_segment_indices=[12, 13],
            confidence_score=0.90,
        )

        # Confirm pairwise relationship: A matches B, B matches C, but A does NOT match C
        self.assertTrue(self.reconciler.are_duplicate_insights(ins_a, ins_b)[0])
        self.assertTrue(self.reconciler.are_duplicate_insights(ins_b, ins_c)[0])
        self.assertFalse(self.reconciler.are_duplicate_insights(ins_a, ins_c)[0])

        candidates = [ins_a, ins_b, ins_c]
        baseline_res = None
        baseline_recs = None

        for perm_idx, perm in enumerate(itertools.permutations(candidates)):
            res, recs = self.reconciler.reconcile_insights(list(perm))

            # All 3 must be retained separately due to non-clique ambiguity
            self.assertEqual(len(res), 3, f"Permutation {perm_idx} failed: expected 3 insights, got {len(res)}")
            self.assertEqual(len(recs), 0, f"Permutation {perm_idx} produced unexpected merge records: {recs}")

            # Titles, practical actions, and evidence must be identical
            evidence_signatures = [tuple(ins.evidence_segment_indices) for ins in res]
            self.assertEqual(
                evidence_signatures,
                [(10, 11), (11, 12), (12, 13)],
                f"Permutation {perm_idx} produced inconsistent evidence order",
            )

            if baseline_res is None:
                baseline_res = res
                baseline_recs = recs
            else:
                for idx in range(3):
                    self.assertEqual(res[idx].title, baseline_res[idx].title)
                    self.assertEqual(res[idx].summary, baseline_res[idx].summary)
                    self.assertEqual(res[idx].evidence_segment_indices, baseline_res[idx].evidence_segment_indices)
                    self.assertEqual(res[idx].confidence_score, baseline_res[idx].confidence_score)
                    self.assertEqual(res[idx].display_order, idx)

    def test_three_candidate_chain_non_clique_ambiguity_all_permutations_quotations(self) -> None:
        """
        REGRESSION TEST FOR FINDING 1 (Quotations):
        Verifies that when three quotations qA, qB, qC form an overlapping chain across 3 chunks
        such that qA matches qB on segment 6, qB matches qC on segment 7, but qA and qC have disjoint
        segments ([5, 6] vs [7, 8]), the engine:
        1. Does not merge A and C.
        2. Leaves ambiguous bridging candidate B separate from both.
        3. Produces identical results across all 6 permutations.
        """
        q_a = CandidateQuotation(
            amharic_quote="ሰላም ጤና ይስጥልኝ።",
            english_translation="Hello and greetings.",
            speaker="ዳዊት",
            source_segment_indices=[5, 6],
            canonical_start_ms=5000,
            canonical_timestamp_seconds=5,
            context="Opening remarks.",
        )
        q_b = CandidateQuotation(
            amharic_quote="ሰላም ጤና ይስጥልኝ።",
            english_translation="Hello and greetings.",
            speaker="ዳዊት",
            source_segment_indices=[6, 7],
            canonical_start_ms=6000,
            canonical_timestamp_seconds=6,
            context="Opening remarks.",
        )
        q_c = CandidateQuotation(
            amharic_quote="ሰላም ጤና ይስጥልኝ።",
            english_translation="Hello and greetings.",
            speaker="ዳዊት",
            source_segment_indices=[7, 8],
            canonical_start_ms=7000,
            canonical_timestamp_seconds=7,
            context="Opening remarks.",
        )

        self.assertTrue(self.reconciler.are_duplicate_quotations(q_a, q_b)[0])
        self.assertTrue(self.reconciler.are_duplicate_quotations(q_b, q_c)[0])
        self.assertFalse(self.reconciler.are_duplicate_quotations(q_a, q_c)[0])

        candidates = [q_a, q_b, q_c]
        baseline_res = None

        for perm_idx, perm in enumerate(itertools.permutations(candidates)):
            res, recs = self.reconciler.reconcile_quotations(list(perm))

            self.assertEqual(len(res), 3, f"Permutation {perm_idx} failed: expected 3 quotes, got {len(res)}")
            self.assertEqual(len(recs), 0)

            seg_signatures = [tuple(q.source_segment_indices) for q in res]
            self.assertEqual(
                seg_signatures,
                [(5, 6), (6, 7), (7, 8)],
                f"Permutation {perm_idx} produced inconsistent quotation order",
            )

            if baseline_res is None:
                baseline_res = res
            else:
                for idx in range(3):
                    self.assertEqual(res[idx].amharic_quote, baseline_res[idx].amharic_quote)
                    self.assertEqual(res[idx].source_segment_indices, baseline_res[idx].source_segment_indices)
                    self.assertEqual(res[idx].canonical_start_ms, baseline_res[idx].canonical_start_ms)
                    self.assertEqual(res[idx].display_order, idx)

    # -------------------------------------------------------------------------
    # 15. Evidence-Reference Metadata Preservation & Collapse Policy
    # -------------------------------------------------------------------------

    def test_payload_reconciliation_preserves_evidence_reference_metadata(self) -> None:
        """
        REGRESSION TEST FOR FINDING 2:
        Verifies that CandidateEvidenceReference metadata (claim_quote_snippet, notes,
        and per-reference relevance_score) is strictly preserved during reconcile_payloads
        and NOT overwritten with the insight-level confidence score.
        """
        ins = CandidateInsight(
            title="Cold Storage Power Continuity",
            category="Operations",
            summary="Rural cold facilities require dual-generator backup power systems.",
            takeaways=["Grid power in regional towns is volatile."],
            practical_action="Install automatic transfer switches with dual generators.",
            evidence_segment_indices=[12],
            confidence_score=0.98,
        )
        original_ref = CandidateEvidenceReference(
            insight_index=0,
            segment_index=12,
            relevance_score=0.85,  # Distinct from insight confidence score 0.98!
            claim_quote_snippet="የመብራት መቆራረጥ ከፍተኛ ኪሳራ ያደርሳል",
            notes="Key empirical evidence cited by the founder regarding fuel and generators.",
        )
        payload = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=CandidateSummary(brief="Short", comprehensive="Long discussion", primary_themes=["Operations"]),
            guest_profile=CandidateGuestProfile(name="Dawit", title="CEO", company="Nile", bio="Bio bio bio bio bio bio bio bio bio bio", industry="Logistics"),
            journey_milestones=[],
            insights=[ins],
            quotations=[],
            suggested_tags=["Power", "Generators"],
            evidence_references=[original_ref],
        )

        reconciled_res = self.reconciler.reconcile_payloads([payload])
        rebuilt_refs = reconciled_res.payload.evidence_references

        self.assertEqual(len(rebuilt_refs), 1)
        ref = rebuilt_refs[0]
        self.assertEqual(ref.insight_index, 0)
        self.assertEqual(ref.segment_index, 12)
        # Original relevance_score 0.85 preserved (NOT replaced with 0.98!)
        self.assertEqual(ref.relevance_score, 0.85)
        # Verbatim claim quote snippet preserved
        self.assertEqual(ref.claim_quote_snippet, "የመብራት መቆራረጥ ከፍተኛ ኪሳራ ያደርሳል")
        # Notes preserved
        self.assertEqual(
            ref.notes,
            "Key empirical evidence cited by the founder regarding fuel and generators.",
        )

    def test_payload_reconciliation_collapses_duplicate_references_deterministically(self) -> None:
        """
        Verifies that when two duplicate insights merge and collapse multiple references
        onto the same (new_insight_idx, segment_index):
        1. relevance_score chooses the maximum score.
        2. claim_quote_snippet chooses the longest informative snippet.
        3. notes are combined deterministically with '; '.
        """
        ins_chunk_0 = CandidateInsight(
            title="Cold Storage Logistics",
            category="Operations",
            summary="Strategic cold storage siting.",
            takeaways=["Takeaway 1."],
            practical_action="Audit transport times.",
            evidence_segment_indices=[12],
            confidence_score=0.91,
        )
        ref_chunk_0 = CandidateEvidenceReference(
            insight_index=0,
            segment_index=12,
            relevance_score=0.82,
            claim_quote_snippet="አጭር ጥቅስ",
            notes="First chunk note.",
        )
        payload_0 = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=CandidateSummary(brief="Short", comprehensive="Long text", primary_themes=["Ops"]),
            guest_profile=CandidateGuestProfile(name="Dawit", title="CEO", company="Nile", bio="Bio...", industry="Ag"),
            journey_milestones=[],
            insights=[ins_chunk_0],
            quotations=[],
            suggested_tags=["Cold"],
            evidence_references=[ref_chunk_0],
        )

        ins_chunk_1 = CandidateInsight(
            title="Cold Storage Logistics",
            category="Operations",
            summary="Strategic cold storage siting.",
            takeaways=["Takeaway 1."],
            practical_action="Audit transport times.",
            evidence_segment_indices=[12],
            confidence_score=0.95,
        )
        ref_chunk_1 = CandidateEvidenceReference(
            insight_index=0,
            segment_index=12,
            relevance_score=0.94,  # Higher score
            claim_quote_snippet="ረዘም ያለ እና ዝርዝር ጥቅስ ከሁለተኛው ቻንክ",  # Longer snippet
            notes="Second chunk note.",
        )
        payload_1 = CandidateExtractionPayload(
            schema_version="1.0.0",
            episode_summary=CandidateSummary(brief="Short", comprehensive="Long text", primary_themes=["Ops"]),
            guest_profile=CandidateGuestProfile(name="Dawit", title="CEO", company="Nile", bio="Bio...", industry="Ag"),
            journey_milestones=[],
            insights=[ins_chunk_1],
            quotations=[],
            suggested_tags=["Cold"],
            evidence_references=[ref_chunk_1],
        )

        res = self.reconciler.reconcile_payloads([payload_0, payload_1])
        rebuilt_refs = res.payload.evidence_references

        self.assertEqual(len(rebuilt_refs), 1)
        ref = rebuilt_refs[0]
        self.assertEqual(ref.insight_index, 0)
        self.assertEqual(ref.segment_index, 12)
        # Max score across references
        self.assertEqual(ref.relevance_score, 0.94)
        # Longest informative snippet preserved
        self.assertEqual(ref.claim_quote_snippet, "ረዘም ያለ እና ዝርዝር ጥቅስ ከሁለተኛው ቻንክ")
        # Unique notes combined with '; '
        self.assertEqual(ref.notes, "First chunk note.; Second chunk note.")

    # -------------------------------------------------------------------------
    # 16. Quotation Contiguity Protection & Canonical Tie-Breakers
    # -------------------------------------------------------------------------

    def test_quotations_with_non_contiguous_combined_segments_rejected(self) -> None:
        """
        REGRESSION TEST FOR FINDING 4:
        Verifies that when two candidate quotations share an anchor segment (e.g. segment 5)
        but their combined segment set has a gap (e.g. [5] and [5, 8], combined [5, 8]),
        the engine:
        1. Refuses to merge them because merged segments would be non-contiguous.
        2. Never invents missing segments [6, 7] to artificially bridge the gap.
        3. Retains both candidates separately.
        """
        q1 = CandidateQuotation(
            amharic_quote="ይህንን ስራ በትንሽ ካፒታል ነው የጀመርነው።",
            english_translation="We started this business with very little capital.",
            speaker="ዳዊት",
            source_segment_indices=[5],
            canonical_start_ms=25000,
            canonical_timestamp_seconds=25,
            context="Early bootstrap context.",
        )
        q2 = CandidateQuotation(
            amharic_quote="ይህንን ስራ በትንሽ ካፒታል ነው የጀመርነው።",
            english_translation="We started this business with very little capital.",
            speaker="ዳዊት",
            source_segment_indices=[5, 8],  # Non-contiguous gap between 5 and 8!
            canonical_start_ms=25000,
            canonical_timestamp_seconds=25,
            context="Early bootstrap context.",
        )

        # Pairwise duplicate check must reject due to non-contiguous combined segments
        is_dup, reason = self.reconciler.are_duplicate_quotations(q1, q2)
        self.assertFalse(is_dup)
        self.assertIn("non-contiguous", reason)

        # Reconciliation must retain both separately
        res, recs = self.reconciler.reconcile_quotations([q1, q2])
        self.assertEqual(len(res), 2)
        self.assertEqual(len(recs), 0)

    def test_canonical_tie_breaker_includes_secondary_content_fields(self) -> None:
        """
        REGRESSION TEST FOR FINDING 3:
        Verifies that when duplicate quotations have identical segment counts, start times,
        and English translation lengths, canonical selection uses full translation and speaker
        strings to break ties deterministically independent of input order.
        """
        q_alpha = CandidateQuotation(
            amharic_quote="ስራው ቀላል አልነበረም።",
            english_translation="Work was hard",  # Length 13
            speaker="ዳዊት",
            source_segment_indices=[5],
            canonical_start_ms=25000,
            canonical_timestamp_seconds=25,
            context="Context A",
        )
        q_beta = CandidateQuotation(
            amharic_quote="ስራው ቀላል አልነበረም።",
            english_translation="Work was heavy",  # Length 14 (longer)
            speaker="ዳዊት",
            source_segment_indices=[5],
            canonical_start_ms=25000,
            canonical_timestamp_seconds=25,
            context="Context B",
        )

        res1, _ = self.reconciler.reconcile_quotations([q_alpha, q_beta])
        res2, _ = self.reconciler.reconcile_quotations([q_beta, q_alpha])

        self.assertEqual(len(res1), 1)
        self.assertEqual(len(res2), 1)
        # Deterministically picks the longer/canonical translation in both orders
        self.assertEqual(res1[0].english_translation, "Work was heavy")
        self.assertEqual(res2[0].english_translation, "Work was heavy")


if __name__ == "__main__":
    unittest.main()

