"""
Meri Content Pipeline v1: Layer 1 Syntactic Schema Validator.
Validates raw Gemini JSON output against structural, type, length, and enum constraints
specified in backend/schemas/gemini_extraction_schema.v1.json.
"""

import json
from typing import Any, Dict, List, Optional, Tuple, Union

from .extraction_models import (
    CandidateGuestProfile,
    CandidateInsight,
    CandidateMilestone,
    CandidateQuotation,
    CandidateSummary,
    ValidationErrorCode,
    ValidationErrorItem,
    ValidationSeverity,
)

# Canonical business domain taxonomy strictly matching schema enum
VALID_BUSINESS_CATEGORIES = {
    "Operations",
    "Fintech",
    "Technology & Infrastructure",
    "Leadership & Culture",
    "Sales & Marketing",
    "Finance & Capital",
    "Legal & Regulatory",
    "Product Strategy",
    "Export & Trade",
}

REQUIRED_TOP_LEVEL_KEYS = [
    "schema_version",
    "episode_summary",
    "guest_profile",
    "insights",
    "quotations",
    "suggested_tags",
]


class SyntacticValidator:
    """
    Validates that candidate JSON adheres to structural, type, and field-boundary rules.
    """

    def validate_raw_json(
        self, raw_json_str: str
    ) -> Tuple[Optional[Dict[str, Any]], List[ValidationErrorItem]]:
        """Parses and validates a raw JSON string."""
        if not raw_json_str or not raw_json_str.strip():
            return None, [
                ValidationErrorItem(
                    item_type="root",
                    field="payload",
                    error_code=ValidationErrorCode.MALFORMED_JSON,
                    message="Extraction response payload is empty.",
                )
            ]

        try:
            data = json.loads(raw_json_str)
        except json.JSONDecodeError as exc:
            return None, [
                ValidationErrorItem(
                    item_type="root",
                    field="payload",
                    error_code=ValidationErrorCode.MALFORMED_JSON,
                    message=f"JSON decoding failed: {exc}",
                )
            ]

        if not isinstance(data, dict):
            return None, [
                ValidationErrorItem(
                    item_type="root",
                    field="payload",
                    error_code=ValidationErrorCode.TYPE_MISMATCH,
                    message="Top-level payload must be a JSON object.",
                )
            ]

        errors = self.validate_dict(data)
        return data, errors

    def validate_dict(self, data: Dict[str, Any]) -> List[ValidationErrorItem]:
        """Validates an already-parsed dictionary against schema constraints."""
        errors: List[ValidationErrorItem] = []

        # 1. Required top-level keys
        for key in REQUIRED_TOP_LEVEL_KEYS:
            if key not in data:
                errors.append(
                    ValidationErrorItem(
                        item_type="root",
                        field=key,
                        error_code=ValidationErrorCode.MISSING_REQUIRED_KEY,
                        message=f"Missing required top-level key: '{key}'",
                    )
                )

        # 2. Schema version constant
        schema_version = data.get("schema_version")
        if schema_version != "1.0.0":
            errors.append(
                ValidationErrorItem(
                    item_type="root",
                    field="schema_version",
                    error_code=ValidationErrorCode.SCHEMA_VIOLATION,
                    message=f"Invalid schema_version '{schema_version}'. Expected '1.0.0'.",
                )
            )

        # 3. Episode summary
        summary = data.get("episode_summary")
        if isinstance(summary, dict):
            for f in ("brief", "comprehensive", "primary_themes"):
                if f not in summary:
                    errors.append(
                        ValidationErrorItem(
                            item_type="summary",
                            field=f"episode_summary.{f}",
                            error_code=ValidationErrorCode.MISSING_REQUIRED_KEY,
                            message=f"episode_summary missing required field '{f}'",
                        )
                    )

            brief = summary.get("brief")
            if isinstance(brief, str):
                if not (30 <= len(brief) <= 320):
                    errors.append(
                        ValidationErrorItem(
                            item_type="summary",
                            field="episode_summary.brief",
                            error_code=ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                            message=f"brief summary length ({len(brief)}) must be 30-320 chars.",
                        )
                    )
            elif brief is not None:
                errors.append(
                    ValidationErrorItem(
                        item_type="summary",
                        field="episode_summary.brief",
                        error_code=ValidationErrorCode.TYPE_MISMATCH,
                        message="episode_summary.brief must be a string.",
                    )
                )

            comprehensive = summary.get("comprehensive")
            if isinstance(comprehensive, str):
                if len(comprehensive) < 120:
                    errors.append(
                        ValidationErrorItem(
                            item_type="summary",
                            field="episode_summary.comprehensive",
                            error_code=ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                            message=f"comprehensive summary length ({len(comprehensive)}) must be >= 120 chars.",
                        )
                    )
            elif comprehensive is not None:
                errors.append(
                    ValidationErrorItem(
                        item_type="summary",
                        field="episode_summary.comprehensive",
                        error_code=ValidationErrorCode.TYPE_MISMATCH,
                        message="episode_summary.comprehensive must be a string.",
                    )
                )

            themes = summary.get("primary_themes")
            if isinstance(themes, list):
                if not (2 <= len(themes) <= 8):
                    errors.append(
                        ValidationErrorItem(
                            item_type="summary",
                            field="episode_summary.primary_themes",
                            error_code=ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS,
                            message=f"primary_themes count ({len(themes)}) must be 2-8 items.",
                        )
                    )
            elif themes is not None:
                errors.append(
                    ValidationErrorItem(
                        item_type="summary",
                        field="episode_summary.primary_themes",
                        error_code=ValidationErrorCode.TYPE_MISMATCH,
                        message="episode_summary.primary_themes must be an array.",
                    )
                )
        elif summary is not None:
            errors.append(
                ValidationErrorItem(
                    item_type="summary",
                    field="episode_summary",
                    error_code=ValidationErrorCode.TYPE_MISMATCH,
                    message="episode_summary must be an object.",
                )
            )

        # 4. Guest profile
        guest = data.get("guest_profile")
        if isinstance(guest, dict):
            for f in ("name", "title", "company", "bio", "industry"):
                if f not in guest:
                    errors.append(
                        ValidationErrorItem(
                            item_type="guest",
                            field=f"guest_profile.{f}",
                            error_code=ValidationErrorCode.MISSING_REQUIRED_KEY,
                            message=f"guest_profile missing required field '{f}'",
                        )
                    )

            name = guest.get("name")
            if isinstance(name, str):
                if not (2 <= len(name) <= 100):
                    errors.append(
                        ValidationErrorItem(
                            item_type="guest",
                            field="guest_profile.name",
                            error_code=ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                            message="guest name must be 2-100 characters.",
                        )
                    )

            bio = guest.get("bio")
            if isinstance(bio, str):
                if len(bio) < 50:
                    errors.append(
                        ValidationErrorItem(
                            item_type="guest",
                            field="guest_profile.bio",
                            error_code=ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                            message=f"guest bio length ({len(bio)}) must be >= 50 characters.",
                        )
                    )
        elif guest is not None:
            errors.append(
                ValidationErrorItem(
                    item_type="guest",
                    field="guest_profile",
                    error_code=ValidationErrorCode.TYPE_MISMATCH,
                    message="guest_profile must be an object.",
                )
            )

        # 5. Insights
        insights = data.get("insights")
        if isinstance(insights, list):
            if len(insights) < 1:
                errors.append(
                    ValidationErrorItem(
                        item_type="insight",
                        field="insights",
                        error_code=ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS,
                        message="insights array must contain at least 1 insight.",
                    )
                )

            for idx, item in enumerate(insights):
                if not isinstance(item, dict):
                    errors.append(
                        ValidationErrorItem(
                            item_type="insight",
                            item_index=idx,
                            field="insights",
                            error_code=ValidationErrorCode.TYPE_MISMATCH,
                            message=f"insight at index {idx} must be an object.",
                        )
                    )
                    continue

                for f in ("title", "category", "summary", "takeaways", "practical_action", "evidence_segment_indices", "confidence_score"):
                    if f not in item:
                        errors.append(
                            ValidationErrorItem(
                                item_type="insight",
                                item_index=idx,
                                field=f"insights[{idx}].{f}",
                                error_code=ValidationErrorCode.MISSING_REQUIRED_KEY,
                                message=f"insight at index {idx} missing required field '{f}'",
                            )
                        )

                # Validate category against the 9 domain enums
                cat = item.get("category")
                if cat not in VALID_BUSINESS_CATEGORIES:
                    errors.append(
                        ValidationErrorItem(
                            item_type="insight",
                            item_index=idx,
                            field="category",
                            error_code=ValidationErrorCode.INVALID_CATEGORY,
                            message=f"insight at index {idx} has invalid category '{cat}'. "
                                    f"Must be one of: {sorted(VALID_BUSINESS_CATEGORIES)}",
                        )
                    )

                # String bounds
                title = item.get("title")
                if isinstance(title, str) and not (5 <= len(title) <= 140):
                    errors.append(
                        ValidationErrorItem(
                            item_type="insight",
                            item_index=idx,
                            field="title",
                            error_code=ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                            message=f"insight title length ({len(title)}) must be 5-140 chars.",
                        )
                    )

                summary_text = item.get("summary")
                if isinstance(summary_text, str) and len(summary_text) < 30:
                    errors.append(
                        ValidationErrorItem(
                            item_type="insight",
                            item_index=idx,
                            field="summary",
                            error_code=ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                            message=f"insight summary length ({len(summary_text)}) must be >= 30 chars.",
                        )
                    )

                takeaways = item.get("takeaways")
                if isinstance(takeaways, list):
                    if not (1 <= len(takeaways) <= 6):
                        errors.append(
                            ValidationErrorItem(
                                item_type="insight",
                                item_index=idx,
                                field="takeaways",
                                error_code=ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS,
                                message=f"takeaways count ({len(takeaways)}) must be 1-6 items.",
                            )
                        )
                elif takeaways is not None:
                    errors.append(
                        ValidationErrorItem(
                            item_type="insight",
                            item_index=idx,
                            field="takeaways",
                            error_code=ValidationErrorCode.TYPE_MISMATCH,
                            message="takeaways must be an array of strings.",
                        )
                    )

                evidence = item.get("evidence_segment_indices")
                if isinstance(evidence, list):
                    if len(evidence) < 1:
                        errors.append(
                            ValidationErrorItem(
                                item_type="insight",
                                item_index=idx,
                                field="evidence_segment_indices",
                                error_code=ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS,
                                message="evidence_segment_indices must cite at least 1 segment index.",
                            )
                        )
                    for e_idx in evidence:
                        if not isinstance(e_idx, int) or e_idx < 0:
                            errors.append(
                                ValidationErrorItem(
                                    item_type="insight",
                                    item_index=idx,
                                    field="evidence_segment_indices",
                                    error_code=ValidationErrorCode.TYPE_MISMATCH,
                                    message=f"evidence segment index '{e_idx}' must be a non-negative integer.",
                                )
                            )

                confidence = item.get("confidence_score")
                if isinstance(confidence, (int, float)):
                    if not (0.0 <= confidence <= 1.0):
                        errors.append(
                            ValidationErrorItem(
                                item_type="insight",
                                item_index=idx,
                                field="confidence_score",
                                error_code=ValidationErrorCode.SCHEMA_VIOLATION,
                                message=f"confidence_score ({confidence}) must be between 0.0 and 1.0.",
                            )
                        )
        elif insights is not None:
            errors.append(
                ValidationErrorItem(
                    item_type="insight",
                    field="insights",
                    error_code=ValidationErrorCode.TYPE_MISMATCH,
                    message="insights must be an array.",
                )
            )

        # 6. Quotations
        quotations = data.get("quotations")
        if isinstance(quotations, list):
            if len(quotations) < 1:
                errors.append(
                    ValidationErrorItem(
                        item_type="quotation",
                        field="quotations",
                        error_code=ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS,
                        message="quotations array must contain at least 1 quotation.",
                    )
                )

            for idx, q in enumerate(quotations):
                if not isinstance(q, dict):
                    errors.append(
                        ValidationErrorItem(
                            item_type="quotation",
                            item_index=idx,
                            field="quotations",
                            error_code=ValidationErrorCode.TYPE_MISMATCH,
                            message=f"quotation at index {idx} must be an object.",
                        )
                    )
                    continue

                for f in ("amharic_quote", "english_translation", "speaker", "timestamp_seconds", "context"):
                    if f not in q:
                        errors.append(
                            ValidationErrorItem(
                                item_type="quotation",
                                item_index=idx,
                                field=f"quotations[{idx}].{f}",
                                error_code=ValidationErrorCode.MISSING_REQUIRED_KEY,
                                message=f"quotation at index {idx} missing required field '{f}'",
                            )
                        )

                # Require source_segment_index (int) OR source_segment_indices (list of ints)
                has_single = "source_segment_index" in q
                has_multi = "source_segment_indices" in q
                if not has_single and not has_multi:
                    errors.append(
                        ValidationErrorItem(
                            item_type="quotation",
                            item_index=idx,
                            field="source_segment_index",
                            error_code=ValidationErrorCode.MISSING_REQUIRED_KEY,
                            message=f"quotation at index {idx} must declare 'source_segment_index' or 'source_segment_indices'.",
                        )
                    )

                quote_text = q.get("amharic_quote")
                if isinstance(quote_text, str) and len(quote_text) < 10:
                    errors.append(
                        ValidationErrorItem(
                            item_type="quotation",
                            item_index=idx,
                            field="amharic_quote",
                            error_code=ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                            message=f"amharic_quote length ({len(quote_text)}) must be >= 10 chars.",
                        )
                    )

                translation = q.get("english_translation")
                if isinstance(translation, str) and len(translation) < 10:
                    errors.append(
                        ValidationErrorItem(
                            item_type="quotation",
                            item_index=idx,
                            field="english_translation",
                            error_code=ValidationErrorCode.STRING_LENGTH_OUT_OF_BOUNDS,
                            message=f"english_translation length ({len(translation)}) must be >= 10 chars.",
                        )
                    )

                ts = q.get("timestamp_seconds")
                if isinstance(ts, int) and ts < 0:
                    errors.append(
                        ValidationErrorItem(
                            item_type="quotation",
                            item_index=idx,
                            field="timestamp_seconds",
                            error_code=ValidationErrorCode.SCHEMA_VIOLATION,
                            message=f"timestamp_seconds ({ts}) cannot be negative.",
                        )
                    )
        elif quotations is not None:
            errors.append(
                ValidationErrorItem(
                    item_type="quotation",
                    field="quotations",
                    error_code=ValidationErrorCode.TYPE_MISMATCH,
                    message="quotations must be an array.",
                )
            )

        # 7. Suggested tags
        tags = data.get("suggested_tags")
        if isinstance(tags, list):
            if not (2 <= len(tags) <= 10):
                errors.append(
                    ValidationErrorItem(
                        item_type="tag",
                        field="suggested_tags",
                        error_code=ValidationErrorCode.ARRAY_COUNT_OUT_OF_BOUNDS,
                        message=f"suggested_tags count ({len(tags)}) must be 2-10 items.",
                    )
                )
        elif tags is not None:
            errors.append(
                ValidationErrorItem(
                    item_type="tag",
                    field="suggested_tags",
                    error_code=ValidationErrorCode.TYPE_MISMATCH,
                    message="suggested_tags must be an array of strings.",
                )
            )

        return errors
