"""
Meri Content Pipeline v1: Extraction Orchestration Service.
Orchestrates Gemini structured extraction and executes dual-layer validation
(Layer 1 Syntactic Schema Validation and Layer 2 Semantic Evidence Grounding).
Packages outputs into auditable ExtractionRunRecord conforming to the extraction_runs DB schema.
"""

from typing import Any, Dict, List, Optional, Tuple

from .extraction_models import (
    CandidateExtractionPayload,
    ExtractionRunRecord,
    ValidationErrorCode,
    ValidationErrorItem,
    ValidationSeverity,
    ValidationStatus,
)
from .gemini_client import GeminiClient, GeminiConfig
from .models import NormalizedSegment, TranscriptChunk
from .semantic_validator import SemanticEvidenceValidator
from .syntactic_validator import SyntacticValidator

DEFAULT_PROMPT_VERSION = "1.0.0"
DEFAULT_SCHEMA_VERSION = "1.0.0"


class ExtractionService:
    """
    Orchestration service for extracting candidate business knowledge from transcript chunks.
    Coordinates Gemini invocation, syntactic schema validation, and semantic evidence verification.
    """

    def __init__(
        self,
        gemini_client: Optional[GeminiClient] = None,
        syntactic_validator: Optional[SyntacticValidator] = None,
        semantic_validator: Optional[SemanticEvidenceValidator] = None,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        schema_version: str = DEFAULT_SCHEMA_VERSION,
    ) -> None:
        self.gemini_client = gemini_client or GeminiClient()
        self.syntactic_validator = syntactic_validator or SyntacticValidator()
        self.semantic_validator = semantic_validator or SemanticEvidenceValidator()
        self.prompt_version = prompt_version
        self.schema_version = schema_version

    def extract_and_validate(
        self,
        segments: List[NormalizedSegment],
        chunks: List[TranscriptChunk],
        job_id: Optional[str] = None,
        episode_id: Optional[str] = None,
        run_number: int = 1,
    ) -> ExtractionRunRecord:
        """
        End-to-end extraction workflow:
        1. Invokes GeminiClient with transcript chunks to produce candidate JSON.
        2. Applies Layer 1 Syntactic Validation against schema.
        3. Applies Layer 2 Semantic Evidence Validation against source segments.
        4. Packages results into ExtractionRunRecord.
        """
        raw_json_str, tokens_prompt, tokens_completion = self.gemini_client.generate_candidate_json(chunks)

        return self.validate_candidate_json(
            raw_json_str=raw_json_str,
            segments=segments,
            model_id=self.gemini_client.config.model_id,
            job_id=job_id,
            episode_id=episode_id,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            run_number=run_number,
        )

    def validate_candidate_json(
        self,
        raw_json_str: str,
        segments: List[NormalizedSegment],
        model_id: Optional[str] = None,
        job_id: Optional[str] = None,
        episode_id: Optional[str] = None,
        tokens_prompt: Optional[int] = None,
        tokens_completion: Optional[int] = None,
        run_number: int = 1,
    ) -> ExtractionRunRecord:
        """
        Dual-layer validation without external API invocation:
        Evaluates pre-generated or mocked candidate JSON through Layer 1 and Layer 2 validation.
        """
        effective_model_id = model_id or (self.gemini_client.config.model_id if self.gemini_client else "gemini-2.0-flash")

        # Layer 1: Syntactic Schema Validation
        parsed_data, syntactic_errors = self.syntactic_validator.validate_raw_json(raw_json_str)

        all_errors: List[ValidationErrorItem] = list(syntactic_errors)

        # Fatal syntactic errors prevent semantic evaluation
        fatal_syntactic = [e for e in syntactic_errors if e.severity == ValidationSeverity.ERROR]
        if parsed_data is None or fatal_syntactic:
            return ExtractionRunRecord(
                model_id=effective_model_id,
                prompt_version=self.prompt_version,
                schema_version=self.schema_version,
                validation_status=ValidationStatus.FAILED,
                validation_errors=all_errors,
                raw_response_json=raw_json_str,
                candidate_payload=None,
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_completion,
                run_number=run_number,
                job_id=job_id,
                episode_id=episode_id,
            )

        # Layer 2: Semantic Evidence Validation
        candidate_payload, semantic_errors, semantic_status = self.semantic_validator.validate_and_assemble(
            data=parsed_data,
            segments=segments,
        )

        all_errors.extend(semantic_errors)

        # Overall status is determined by semantic evaluation and any syntactic warnings/errors
        overall_status = semantic_status

        return ExtractionRunRecord(
            model_id=effective_model_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            validation_status=overall_status,
            validation_errors=all_errors,
            raw_response_json=raw_json_str,
            candidate_payload=candidate_payload,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            run_number=run_number,
            job_id=job_id,
            episode_id=episode_id,
        )
