"""
Meri Content Pipeline v1: Test-Only Deterministic Fake Extraction Provider.

Milestone 7.2 Synthetic Pipeline Integration Test component:
1. Requires no Gemini API key.
2. Performs zero external network requests.
3. Produces schema-valid, deterministic candidate knowledge grounded in synthetic transcript segments.
4. Generates stable, explicit test values (2 insights and 2 quotations).
5. Produces exact evidence references and quotation-to-segment provenance mappings.
6. Supports controlled failure modes for error-handling and rollback testing.
7. Strictly isolated to test suite—never replaces production defaults.
"""

from dataclasses import dataclass
import json
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.request

from backend.src.extraction_models import (
    CandidateEvidenceReference,
    CandidateExtractionPayload,
    CandidateGuestProfile,
    CandidateInsight,
    CandidateMilestone,
    CandidateQuotation,
    CandidateQuotationSegment,
    CandidateSummary,
    ExtractionRunRecord,
    ValidationStatus,
)
from backend.src.extraction_service import ExtractionService
from backend.src.gemini_client import (
    GeminiClient,
    GeminiConfig,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
)
from backend.src.models import NormalizedSegment, TranscriptChunk

SYNTHETIC_MODEL_ID = "gemini-2.0-flash"
SYNTHETIC_PROMPT_VERSION = "1.0.0"
SYNTHETIC_SCHEMA_VERSION = "1.0.0"
SYNTHETIC_MOCK_KEY = "synthetic-test-key-no-external-calls"


def create_deterministic_synthetic_payload(
    evidence_segment_indices_insight_0: Optional[List[int]] = None,
    evidence_segment_indices_insight_1: Optional[List[int]] = None,
    source_segment_indices_quote_0: Optional[List[int]] = None,
    source_segment_indices_quote_1: Optional[List[int]] = None,
    source_segment_index_quote_0: Optional[int] = None,
    source_segment_index_quote_1: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Builds a deterministic, schema-valid synthetic candidate extraction payload
    grounded in sample_transcript.json segments:
    - Segment 1: "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።"
    - Segment 3: "መጀመሪያ ላይ የራሳችንን መኪና ከመግዛት ይልቅ ያሉትን የጭነት መኪናዎች በመከራየት እና በማሻሻል ጀመርን።"
    """
    ev_0 = evidence_segment_indices_insight_0 if evidence_segment_indices_insight_0 is not None else [1]
    ev_1 = evidence_segment_indices_insight_1 if evidence_segment_indices_insight_1 is not None else [3]

    if source_segment_indices_quote_0 is not None:
        q_0_indices = source_segment_indices_quote_0
    elif source_segment_index_quote_0 is not None:
        q_0_indices = [source_segment_index_quote_0]
    else:
        q_0_indices = [1]

    if source_segment_indices_quote_1 is not None:
        q_1_indices = source_segment_indices_quote_1
    elif source_segment_index_quote_1 is not None:
        q_1_indices = [source_segment_index_quote_1]
    else:
        q_1_indices = [3]

    return {
        "schema_version": SYNTHETIC_SCHEMA_VERSION,
        "episode_summary": {
            "brief": "ውይይት ስለ ኢትዮጵያ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ እና የገበሬዎች ምርት አያያዝ።",
            "comprehensive": (
                "ዳዊት ታደሰ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ በኢትዮጵያ ያለውን ተግዳሮት እና መፍትሄዎች በሰፊው ያብራራል። "
                "በመንገድ ላይ የሚባክነውን የገበሬዎች ምርት ለመቀነስ የተከተሏቸውን ዘዴዎች እና የቴክኖሎጂ አጠቃቀም ይተነትናል።"
            ),
            "primary_themes": ["Logistics", "Cold Chain", "Agriculture"],
        },
        "guest_profile": {
            "name": "Dawit Tadesse",
            "title": "Founder & Managing Director",
            "company": "Nile Cold Chain Logistics",
            "bio": "Mechanical engineer turned logistics entrepreneur who spent 8 years designing modular refrigerated containers.",
            "industry": "Agricultural Logistics & Cold Storage",
            "journey_summary": "Pivoted from pure engineering consultancy into logistics after witnessing harvest spoilage.",
        },
        "journey_milestones": [
            {
                "phase_or_year": "2020",
                "milestone_description": "የመጀመሪያው የቀዝቃዛ መኪና ሙከራ ተጀመረ።",
                "strategic_decision": "የነባር መኪናዎችን ማሻሻል ተመረጠ።",
                "evidence_segment_indices": [1],
            },
            {
                "phase_or_year": "2022",
                "milestone_description": "የጭነት መኪናዎች ኪራይ እና ማሻሻያ አሰራር ተዘረጋ።",
                "strategic_decision": "ካፒታልን በኪራይ አማካኝነት ማዳን ተመረጠ።",
                "evidence_segment_indices": [3],
            },
        ],
        "insights": [
            {
                "title": "የሎጂስቲክስ ስራ እና የመንገድ ላይ ብክነት",
                "category": "Operations",
                "summary": "መኪና ከመግዛት ይልቅ በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ዋናው ቁልፍ ነው።",
                "takeaways": [
                    "የምርት ብክነትን በሰከንድ መለካት ወሳኝ ነው።",
                    "የነባር ተሽከርካሪዎችን አቅም ማሳደግ ካፒታልን ይቆጥባል።",
                ],
                "practical_action": "በመጓጓዣ መስመሮች ላይ ያለውን የሙቀት መጠን እና ብክነት በየጊዜው መመዝገብ።",
                "evidence_segment_indices": ev_0,
                "confidence_score": 0.95,
            },
            {
                "title": "የካፒታል አጠቃቀም እና የጭነት መኪና ኪራይ",
                "category": "Finance & Capital",
                "summary": "መጀመሪያ ላይ የራሳችንን መኪና ከመግዛት ይልቅ ያሉትን የጭነት መኪናዎች በመከራየት እና በማሻሻል መጀመር ካፒታልን ይቆጥባል።",
                "takeaways": [
                    "የነባር የጭነት መኪናዎችን አቅም ማሻሻል ይቻላል።",
                    "የመጀመሪያ ካፒታልን በኪራይ አማካኝነት ማዳን ይቻላል።",
                ],
                "practical_action": "ያሉትን የትራንስፖርት አማራጮች አወዳድሮ መከራየት።",
                "evidence_segment_indices": ev_1,
                "confidence_score": 0.92,
            },
        ],
        "quotations": [
            {
                "amharic_quote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
                "english_translation": "The greatest test in logistics isn't buying trucks; it's calculating the value of wasted produce.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": q_0_indices,
                "timestamp_seconds": 14,
                "context": "ስለ ሎጂስቲክስ ስራ ፈተናዎች ሲያብራራ የተናገረው።",
                "importance_rationale": "የንግዱን ዋና ፍልስፍና ያሳያል።",
            },
            {
                "amharic_quote": "መጀመሪያ ላይ የራሳችንን መኪና ከመግዛት ይልቅ ያሉትን የጭነት መኪናዎች በመከራየት እና በማሻሻል ጀመርን።",
                "english_translation": "Initially, rather than purchasing our own vehicles, we began by renting and upgrading existing trucks.",
                "speaker": "Dawit Tadesse",
                "source_segment_indices": q_1_indices,
                "timestamp_seconds": 58,
                "context": "ስለ መጀመሪያ ስትራቴጂ ሲያብራራ የተናገረው።",
                "importance_rationale": "የካፒታል አጠቃቀም ጥበብን ያሳያል።",
            },
        ],
        "suggested_tags": ["Logistics", "Ethiopia", "Supply Chain", "Agriculture"],
    }


class DeterministicFakeExtractor:
    """
    Test-only deterministic fake extractor and mock Gemini provider.

    Guarantees:
    - Zero external network connections.
    - Zero Gemini API key required.
    - Deterministic, repeatable candidate extraction outputs.
    - Grounded verbatim in synthetic transcript fixtures.
    - Supports controlled failure modes for robust testing of error and rollback paths.
    """

    def __init__(
        self,
        failure_mode: Optional[str] = None,
        tokens_prompt: int = 500,
        tokens_completion: int = 250,
        model_id: str = SYNTHETIC_MODEL_ID,
    ) -> None:
        """
        Args:
            failure_mode: None (success), 'network_error', 'invalid_json',
                          'semantic_error', 'empty_payload', or 'rate_limit'.
            tokens_prompt: Deterministic prompt token count.
            tokens_completion: Deterministic completion token count.
            model_id: Deterministic model identifier.
        """
        self.failure_mode = failure_mode
        self.tokens_prompt = tokens_prompt
        self.tokens_completion = tokens_completion
        self.model_id = model_id
        self._call_count = 0
        self._timeline: List[str] = []

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def timeline(self) -> List[str]:
        return list(self._timeline)

    def _mock_transport(self, req: urllib.request.Request, timeout: float) -> Tuple[int, Dict[str, str], str]:
        """Mock HTTP transport returning deterministic JSON without network access."""
        self._call_count += 1
        self._timeline.append(f"fake_transport_invocation_{self._call_count}")

        if self.failure_mode == "network_error":
            raise GeminiTimeoutError("Simulated deterministic network timeout in fake extraction provider.")
        elif self.failure_mode == "rate_limit":
            raise GeminiServiceUnavailableError("Simulated deterministic rate limit (HTTP 429) in fake provider.")
        elif self.failure_mode == "invalid_json":
            raw_text = "INVALID_NON_JSON_SYNTACTIC_ERROR_CONTENT {"
        elif self.failure_mode == "semantic_error":
            # Fabricated quotation that is never spoken in sample transcript
            payload = create_deterministic_synthetic_payload()
            payload["quotations"][0]["amharic_quote"] = "ይህ በጭራሽ በቪዲዮው ያልተነገረ የተፈጠረ ንግግር ነው።"
            raw_text = json.dumps(payload)
        elif self.failure_mode == "empty_payload":
            payload = create_deterministic_synthetic_payload()
            payload["insights"] = []
            payload["quotations"] = []
            raw_text = json.dumps(payload)
        else:
            payload = create_deterministic_synthetic_payload()
            raw_text = json.dumps(payload)

        gemini_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": raw_text}],
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": self.tokens_prompt,
                "candidatesTokenCount": self.tokens_completion,
            },
        }
        return 200, {}, json.dumps(gemini_response)

    def create_gemini_client(self) -> GeminiClient:
        """Returns a configured GeminiClient using the deterministic mock transport."""
        return GeminiClient(
            config=GeminiConfig(
                model_id=self.model_id,
                api_key=SYNTHETIC_MOCK_KEY,
            ),
            transport=self._mock_transport,
        )

    def create_extraction_service(self) -> ExtractionService:
        """Returns an ExtractionService backed by the deterministic fake GeminiClient."""
        client = self.create_gemini_client()
        return ExtractionService(
            gemini_client=client,
            prompt_version=SYNTHETIC_PROMPT_VERSION,
            schema_version=SYNTHETIC_SCHEMA_VERSION,
        )

    def extract_and_validate(
        self,
        segments: List[NormalizedSegment],
        chunks: List[TranscriptChunk],
        job_id: Optional[str] = None,
        episode_id: Optional[str] = None,
        run_number: int = 1,
    ) -> ExtractionRunRecord:
        """Direct extraction interface conforming to ExtractionService.extract_and_validate."""
        service = self.create_extraction_service()
        return service.extract_and_validate(
            segments=segments,
            chunks=chunks,
            job_id=job_id,
            episode_id=episode_id,
            run_number=run_number,
        )
