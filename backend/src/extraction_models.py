"""
Meri Content Pipeline v1: Data models and validation structures for candidate knowledge extraction.
Strictly reflects PostgreSQL tables: extraction_runs, insights, quotations, and insight_evidence.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ValidationStatus(str, Enum):
    """
    Validation status for Gemini candidate extraction runs.
    Strictly matches PostgreSQL CHECK constraint on extraction_runs:
    CHECK (validation_status IN ('passed', 'failed', 'partial'))
    """
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"


class ValidationSeverity(str, Enum):
    """Severity of a validation finding."""
    ERROR = "error"
    WARNING = "warning"


class ValidationErrorCode(str, Enum):
    """Standardized, actionable validation error codes."""
    # Syntactic / Schema errors
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    MISSING_REQUIRED_KEY = "MISSING_REQUIRED_KEY"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    INVALID_CATEGORY = "INVALID_CATEGORY"
    STRING_LENGTH_OUT_OF_BOUNDS = "STRING_LENGTH_OUT_OF_BOUNDS"
    ARRAY_COUNT_OUT_OF_BOUNDS = "ARRAY_COUNT_OUT_OF_BOUNDS"
    MALFORMED_JSON = "MALFORMED_JSON"

    # Semantic / Grounding errors
    SEGMENT_NOT_FOUND = "SEGMENT_NOT_FOUND"
    NON_CONTIGUOUS_SEGMENTS = "NON_CONTIGUOUS_SEGMENTS"
    EMPTY_EVIDENCE = "EMPTY_EVIDENCE"
    TIMESTAMP_OUT_OF_BOUNDS = "TIMESTAMP_OUT_OF_BOUNDS"
    DISCREPANT_TIMESTAMP = "DISCREPANT_TIMESTAMP"
    QUOTE_NOT_IN_SOURCE = "QUOTE_NOT_IN_SOURCE"
    PARAPHRASE_DETECTED = "PARAPHRASE_DETECTED"
    UNVERIFIED_MODEL_OUTPUT = "UNVERIFIED_MODEL_OUTPUT"


@dataclass(frozen=True)
class ValidationErrorItem:
    """Represents a specific syntactic or semantic validation issue."""
    item_type: str  # 'summary', 'guest', 'insight', 'quotation', 'milestone', 'tag'
    field: str
    error_code: ValidationErrorCode
    message: str
    item_index: Optional[int] = None
    severity: ValidationSeverity = ValidationSeverity.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_type": self.item_type,
            "item_index": self.item_index,
            "field": self.field,
            "error_code": self.error_code.value,
            "message": self.message,
            "severity": self.severity.value,
        }


@dataclass(frozen=True)
class CandidateSummary:
    """
    Candidate executive summary.
    In-memory: retains both brief and comprehensive representations.
    Intended DB mapping: comprehensive -> episodes.summary; brief -> preview metadata.
    """
    brief: str
    comprehensive: str
    primary_themes: List[str]


@dataclass(frozen=True)
class CandidateGuestProfile:
    """
    Candidate guest profile.
    Intended DB mapping: fields map to table: guests.
    """
    name: str
    title: str
    company: str
    bio: str
    industry: str
    journey_summary: Optional[str] = None


@dataclass(frozen=True)
class CandidateMilestone:
    """
    Candidate founder journey milestone.
    Intended DB mapping: founder journey timeline with segment evidence references.
    """
    phase_or_year: str
    milestone_description: str
    strategic_decision: str
    evidence_segment_indices: List[int]


@dataclass(frozen=True)
class CandidateInsight:
    """
    Candidate business insight extracted by AI.

    SEMANTIC EVIDENCE CONTRACT:
    - Valid `evidence_segment_indices` establish PROVENANCE ONLY: they document which
      specific transcript cues the model referenced to formulate this insight.
    - Automated validation of segment indices verifies that the referenced segments exist
      in the transcript, but DOES NOT prove or guarantee that the substantive business claim,
      takeaways, or strategic assertions are factually true or sound.
    - Factual verification and substantive approval require human editorial review in Milestone 3.
    - `review_status` is ALWAYS initialized to 'candidate'. Automated validation passing NEVER
      promotes an insight to 'approved' and NEVER authorizes publication.

    Intended DB mapping: table: insights (review_status='candidate').
    """
    title: str
    category: str
    summary: str
    takeaways: List[str]
    practical_action: str
    evidence_segment_indices: List[int]
    confidence_score: float
    display_order: int = 0
    review_status: str = "candidate"

    def to_db_dict(self, episode_id: Optional[str] = None, extraction_run_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "category": self.category,
            "title": self.title,
            "summary": self.summary,
            "takeaways": self.takeaways,
            "practical_action": self.practical_action,
            "display_order": self.display_order,
            "review_status": self.review_status,
        }
        if episode_id:
            payload["episode_id"] = episode_id
        if extraction_run_id:
            payload["extraction_run_id"] = extraction_run_id
        return payload


@dataclass(frozen=True)
class CandidateQuotation:
    """
    Candidate spoken quotation.

    CROSS-SEGMENT PERSISTENCE MAPPING:
    - In-Memory Representation: `source_segment_indices` retains the complete, ordered list
      of contiguous transcript segments spanned by this quotation (e.g. [3, 4]).
    - Database Constraint (Supabase 20261020000001): The current `quotations` table schema has
      a singular foreign key column: `segment_id UUID REFERENCES transcript_segments(id)`.
    - Current Database Mapping: Under this schema, `segment_id` maps to the PRIMARY STARTING
      segment (i.e. `source_segment_indices[0]`), which also anchors `canonical_timestamp_seconds`.
    - Future Persistence Options (Requiring Architectural Approval):
        Option 1: Add a `quotation_segments` bridge table (analogous to `insight_evidence`)
                  for full relational M:N linking of multi-segment quotes.
        Option 2: Add an array column `segment_ids UUID[]` to `quotations`.
        Option 3: Store full segment indices in audit metadata while retaining anchor in `segment_id`.
    - In this milestone, full segment provenance is preserved in memory and in `raw_response_json`.

    Canonical timestamps are kept in milliseconds internally, and converted to
    canonical seconds at output boundaries.
    """
    amharic_quote: str
    english_translation: str
    speaker: str
    source_segment_indices: List[int]
    canonical_start_ms: int
    canonical_timestamp_seconds: int
    context: str
    reported_timestamp_seconds: Optional[int] = None
    has_timestamp_discrepancy: bool = False
    importance_rationale: Optional[str] = None
    display_order: int = 0
    review_status: str = "candidate"

    def to_db_dict(
        self,
        episode_id: Optional[str] = None,
        extraction_run_id: Optional[str] = None,
        segment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Maps to table: quotations.
        `segment_id` represents the primary starting segment anchor under the current schema.
        """
        payload: Dict[str, Any] = {
            "amharic_quote": self.amharic_quote,
            "english_translation": self.english_translation,
            "speaker": self.speaker,
            "timestamp_seconds": self.canonical_timestamp_seconds,
            "context": self.context,
            "display_order": self.display_order,
            "review_status": self.review_status,
        }
        if episode_id:
            payload["episode_id"] = episode_id
        if extraction_run_id:
            payload["extraction_run_id"] = extraction_run_id
        if segment_id:
            payload["segment_id"] = segment_id
        return payload


@dataclass(frozen=True)
class CandidateEvidenceReference:
    """
    Relational linkage connecting a candidate insight to a supporting transcript segment.
    Intended DB mapping: table: insight_evidence.
    """
    insight_index: int
    segment_index: int
    relevance_score: Optional[float] = None
    claim_quote_snippet: Optional[str] = None
    notes: Optional[str] = None

    def to_db_dict(self, insight_id: Optional[str] = None, segment_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "relevance_score": self.relevance_score,
            "claim_quote_snippet": self.claim_quote_snippet,
            "notes": self.notes,
        }
        if insight_id:
            payload["insight_id"] = insight_id
        if segment_id:
            payload["segment_id"] = segment_id
        return payload


@dataclass
class CandidateExtractionPayload:
    """Complete structured candidate extraction payload."""
    schema_version: str
    episode_summary: CandidateSummary
    guest_profile: CandidateGuestProfile
    journey_milestones: List[CandidateMilestone]
    insights: List[CandidateInsight]
    quotations: List[CandidateQuotation]
    suggested_tags: List[str]
    evidence_references: List[CandidateEvidenceReference] = field(default_factory=list)


@dataclass
class ExtractionRunRecord:
    """
    Auditable extraction run output.
    Strictly conforms to PostgreSQL table: extraction_runs.
    """
    model_id: str
    prompt_version: str
    schema_version: str
    validation_status: ValidationStatus
    validation_errors: List[ValidationErrorItem]
    raw_response_json: Optional[str] = None
    candidate_payload: Optional[CandidateExtractionPayload] = None
    tokens_prompt: Optional[int] = None
    tokens_completion: Optional[int] = None
    run_number: int = 1
    job_id: Optional[str] = None
    episode_id: Optional[str] = None

    def to_db_dict(self) -> Dict[str, Any]:
        """Maps to extraction_runs table columns."""
        payload: Dict[str, Any] = {
            "run_number": self.run_number,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "raw_response_json": self.raw_response_json,
            "validation_status": self.validation_status.value,
            "validation_errors": [err.to_dict() for err in self.validation_errors],
            "tokens_prompt": self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
        }
        if self.job_id:
            payload["job_id"] = self.job_id
        if self.episode_id:
            payload["episode_id"] = self.episode_id
        return payload
