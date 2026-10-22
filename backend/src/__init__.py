"""
Meri Content Pipeline v1: Transcript Ingestion, Normalization, Chunking & Candidate Extraction Engine.
"""

from .candidate_persistence import (
    CandidatePersistenceService,
    CrossEpisodeIntegrityError,
    EditorialAuthorizationError,
)
from .chunker import TranscriptChunker, estimate_token_count, format_chunk_text
from .extraction_models import (
    CandidateEvidenceReference,
    CandidateExtractionPayload,
    CandidateGuestProfile,
    CandidateInsight,
    CandidateMilestone,
    CandidateQuotation,
    CandidateQuotationSegment,
    CandidateSummary,
    ExtractionRunRecord,
    ValidationErrorCode,
    ValidationErrorItem,
    ValidationSeverity,
    ValidationStatus,
)
from .extraction_service import ExtractionService
from .gemini_client import (
    GeminiAuthError,
    GeminiBadRequestError,
    GeminiClient,
    GeminiClientError,
    GeminiConfig,
    GeminiModelConfigError,
    GeminiQuotaExhaustedError,
    GeminiRateLimitError,
    GeminiRetryExhaustedError,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
    _redact_secrets,
    check_model_availability,
    parse_retry_after,
    validate_model_id_syntax,
    verify_model_configuration,
    verify_model_preflight,
)
from .models import (
    InvalidTimestampError,
    InvalidYouTubeUrlError,
    MalformedCueError,
    NormalizedSegment,
    OverlapPolicy,
    RawCue,
    TranscriptAcquisitionMethod,
    TranscriptChunk,
    TranscriptOverlapError,
    TranscriptPipelineError,
)
from .semantic_validator import SemanticEvidenceValidator
from .syntactic_validator import SyntacticValidator
from .transcript_normalizer import TranscriptNormalizer, clean_amharic_text
from .transcript_parser import (
    parse_json_transcript,
    parse_srt_transcript,
    parse_timestamp_string_to_ms,
    parse_transcript,
    parse_webvtt_transcript,
)
from .youtube_validator import validate_and_extract_youtube_video_id

__all__ = [
    # Transcript Ingestion & Normalization
    "validate_and_extract_youtube_video_id",
    "parse_transcript",
    "parse_json_transcript",
    "parse_srt_transcript",
    "parse_webvtt_transcript",
    "parse_timestamp_string_to_ms",
    "clean_amharic_text",
    "TranscriptNormalizer",
    "TranscriptChunker",
    "estimate_token_count",
    "format_chunk_text",
    "RawCue",
    "NormalizedSegment",
    "TranscriptChunk",
    "TranscriptAcquisitionMethod",
    "OverlapPolicy",
    "TranscriptPipelineError",
    "InvalidYouTubeUrlError",
    "MalformedCueError",
    "InvalidTimestampError",
    "TranscriptOverlapError",
    # Extraction Models
    "ValidationStatus",
    "ValidationSeverity",
    "ValidationErrorCode",
    "ValidationErrorItem",
    "CandidateSummary",
    "CandidateGuestProfile",
    "CandidateMilestone",
    "CandidateInsight",
    "CandidateQuotation",
    "CandidateQuotationSegment",
    "CandidateEvidenceReference",
    "CandidateExtractionPayload",
    "ExtractionRunRecord",
    # Candidate Persistence & Editorial Boundaries (Milestone 3)
    "CandidatePersistenceService",
    "EditorialAuthorizationError",
    "CrossEpisodeIntegrityError",
    # Gemini Client
    "GeminiClient",
    "GeminiConfig",
    "GeminiClientError",
    "GeminiAuthError",
    "GeminiBadRequestError",
    "GeminiModelConfigError",
    "GeminiRateLimitError",
    "GeminiQuotaExhaustedError",
    "GeminiServiceUnavailableError",
    "GeminiTimeoutError",
    "GeminiRetryExhaustedError",
    "validate_model_id_syntax",
    "verify_model_configuration",
    "check_model_availability",
    "verify_model_preflight",
    "_redact_secrets",
    "parse_retry_after",
    # Validators & Orchestration
    "SyntacticValidator",
    "SemanticEvidenceValidator",
    "ExtractionService",
]