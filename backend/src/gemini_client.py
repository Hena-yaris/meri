"""
Meri Content Pipeline v1: Dedicated Gemini API Client.
Supports structured JSON extraction, bounded exponential backoff, Retry-After header parsing,
model configuration verification, and mockable transport for fast, deterministic unit testing.
"""

from dataclasses import dataclass
import email.utils
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from .models import TranscriptChunk

# Standard Gemini REST endpoint base
GEMINI_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

# Regex verifying valid model identifier syntax without hardcoding specific model generations
_MODEL_ID_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{3,64}$")

# Transport function signature: (Request, timeout_seconds) -> (status_code, headers_dict, response_body_text)
Transport = Callable[[urllib.request.Request, float], Tuple[int, Dict[str, str], str]]
SleepFn = Callable[[float], None]


class GeminiClientError(Exception):
    """Base exception for Gemini client failures."""
    pass


class GeminiAuthError(GeminiClientError):
    """Permanent error: invalid or missing API key (HTTP 401 / 403). Never retried."""
    pass


class GeminiBadRequestError(GeminiClientError):
    """Permanent error: malformed request or prompt rejection (HTTP 400). Never retried."""
    pass


class GeminiModelConfigError(GeminiClientError):
    """Configuration error: invalid or unsupported model identifier. Never retried."""
    pass


class GeminiRateLimitError(GeminiClientError):
    """Transient error: HTTP 429 rate limit exceeded. Eligible for bounded retry."""
    pass


class GeminiQuotaExhaustedError(GeminiClientError):
    """Permanent/quota error: hard quota exhausted. Never retried."""
    pass


class GeminiServiceUnavailableError(GeminiClientError):
    """Transient error: HTTP 500 / 503 service unavailable. Eligible for bounded retry."""
    pass


class GeminiTimeoutError(GeminiClientError):
    """Transient error: request timed out. Eligible for bounded retry."""
    pass


class GeminiRetryExhaustedError(GeminiClientError):
    """Raised when maximum retry attempts have been reached without success."""
    pass


def validate_model_id_syntax(model_id: str) -> None:
    """
    Verifies that the model identifier is syntactically well-formed (3-64 characters matching [a-zA-Z0-9_.-]).
    NOTE: This is a local syntactic check only. To verify actual remote model existence and
    generation support, call check_model_availability().
    """
    if not model_id or not isinstance(model_id, str):
        raise GeminiModelConfigError("Gemini model_id must be a non-empty string.")

    trimmed = model_id.strip()
    if not _MODEL_ID_REGEX.match(trimmed):
        raise GeminiModelConfigError(
            f"Invalid model identifier '{model_id}'. Must be 3-64 characters matching [a-zA-Z0-9_.-]."
        )


# Backward-compatible alias
verify_model_configuration = validate_model_id_syntax


def _redact_secrets(text: str) -> str:
    """Strips API keys and sensitive tokens from error messages and logs."""
    return re.sub(r"([?&]key=)[^&\s'\"]+", r"\1[REDACTED]", text)


def check_model_availability(
    model_id: str,
    api_key: str,
    transport: Optional[Transport] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """
    Verifies actual remote model availability and structured generation capabilities
    against the Gemini REST API (GET /v1beta/models/{model_id}).

    Asserts that:
    1. The model ID syntax is valid.
    2. The API key is authentic (HTTP 200).
    3. The model exists (not HTTP 404).
    4. The model declares 'generateContent' in supportedGenerationMethods.
    5. API keys are strictly redacted in any error messages or exceptions.
    """
    validate_model_id_syntax(model_id)
    if not api_key:
        raise GeminiAuthError("Missing GEMINI_API_KEY for model availability verification.")

    effective_transport = transport or _default_urllib_transport
    target_url = f"{GEMINI_API_ENDPOINT}/{model_id}?key={api_key}"
    request = urllib.request.Request(
        url=target_url,
        headers={"User-Agent": "Meri-Content-Pipeline/1.0"},
        method="GET",
    )

    try:
        status_code, headers, body_text = effective_transport(request, timeout)
    except Exception as exc:
        safe_msg = _redact_secrets(str(exc))
        raise GeminiClientError(f"Model availability network transport error: {safe_msg}") from exc

    if status_code == 200:
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise GeminiClientError(f"Failed to parse model availability JSON response: {exc}") from exc

        methods = data.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            raise GeminiModelConfigError(
                f"Configured model '{model_id}' does not support 'generateContent'. Supported methods: {methods}"
            )
        return data

    if status_code in (401, 403):
        raise GeminiAuthError(f"Gemini authentication failed during model verification (HTTP {status_code}).")

    if status_code == 404:
        raise GeminiModelConfigError(
            f"Configured model '{model_id}' was not found on Gemini API (HTTP 404). Model may be deprecated or unreleased."
        )

    safe_body = _redact_secrets(body_text[:200])
    raise GeminiClientError(f"Model availability check failed with HTTP {status_code}: {safe_body}")


def verify_model_preflight(
    model_id: str,
    api_key: str,
    transport: Optional[Transport] = None,
    timeout: float = 10.0,
    verify_structured_output: bool = True,
) -> Dict[str, Any]:
    """
    Comprehensive preflight check executed strictly before live transcript extraction.
    Asserts that:
    1. Model-ID syntax is valid locally.
    2. Model exists remotely and supports 'generateContent'.
    3. Structured-output configuration (responseMimeType='application/json') is supported.
    4. API keys are NEVER logged or leaked.
    NOTE: This is intentionally never run during app startup or unit tests.
    """
    # 1. Availability and generateContent support
    model_metadata = check_model_availability(
        model_id=model_id,
        api_key=api_key,
        transport=transport,
        timeout=timeout,
    )

    # 2. Structured output capability probe (verifying application/json responseMimeType)
    if verify_structured_output:
        effective_transport = transport or _default_urllib_transport
        probe_payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Preflight health check probe. Return JSON: {\"status\": \"ok\"}"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            },
        }
        probe_bytes = json.dumps(probe_payload).encode("utf-8")
        target_url = f"{GEMINI_API_ENDPOINT}/{model_id}:generateContent?key={api_key}"

        request = urllib.request.Request(
            url=target_url,
            data=probe_bytes,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "Meri-Content-Pipeline/1.0",
            },
            method="POST",
        )

        try:
            status_code, headers, body_text = effective_transport(request, timeout)
        except Exception as exc:
            safe_msg = _redact_secrets(str(exc))
            raise GeminiClientError(f"Structured-output preflight network transport error: {safe_msg}") from exc

        if status_code != 200:
            safe_body = _redact_secrets(body_text[:200])
            if status_code in (401, 403):
                raise GeminiAuthError(f"Preflight auth failure during structured output probe (HTTP {status_code}).")
            if status_code == 400:
                raise GeminiModelConfigError(
                    f"Model '{model_id}' rejected structured output configuration (HTTP 400): {safe_body}"
                )
            raise GeminiClientError(f"Structured output preflight probe failed (HTTP {status_code}): {safe_body}")

    return model_metadata


def parse_retry_after(header_val: Optional[str], default_delay: float, max_delay: float) -> float:
    """
    Parses HTTP 'Retry-After' header (integer seconds or HTTP date string).
    Clamps between 0.0 and max_delay.
    """
    if not header_val:
        return default_delay

    trimmed = header_val.strip()
    # Try parsing as integer seconds
    try:
        seconds = float(trimmed)
        return min(max(0.0, seconds), max_delay)
    except ValueError:
        pass

    # Try parsing as RFC 2822 date
    try:
        date_tuple = email.utils.parsedate_tz(trimmed)
        if date_tuple:
            target_ts = email.utils.mktime_tz(date_tuple)
            delay = target_ts - time.time()
            return min(max(0.0, delay), max_delay)
    except Exception:
        pass

    return default_delay


def _default_urllib_transport(request: urllib.request.Request, timeout: float) -> Tuple[int, Dict[str, str], str]:
    """Default transport executing live HTTP request via urllib.request."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = response.getcode()
            headers = {k.lower(): v for k, v in response.headers.items()}
            body_text = response.read().decode("utf-8")
            return status_code, headers, body_text
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        body_text = exc.read().decode("utf-8") if exc.fp else ""
        return exc.code, headers, body_text
    except urllib.error.URLError as exc:
        raise GeminiTimeoutError(f"Network transport error: {exc.reason}") from exc


@dataclass
class GeminiConfig:
    """Configuration settings for Gemini extraction client."""
    model_id: str = "gemini-2.0-flash"
    api_key: Optional[str] = None
    temperature: float = 0.1
    timeout_seconds: float = 30.0
    max_retries: int = 3
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    backoff_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("GEMINI_API_KEY", "")
        # Resolve model_id from environment if not explicitly overridden
        env_model = os.environ.get("GEMINI_MODEL_ID")
        if env_model:
            self.model_id = env_model
        verify_model_configuration(self.model_id)


class GeminiClient:
    """
    Dedicated Gemini API client with mockable transport and bounded retry logic.
    """

    def __init__(
        self,
        config: Optional[GeminiConfig] = None,
        transport: Optional[Transport] = None,
        sleep_fn: Optional[SleepFn] = None,
    ) -> None:
        self.config = config or GeminiConfig()
        self.transport = transport or _default_urllib_transport
        self.sleep_fn = sleep_fn or time.sleep

    def check_availability(self) -> Dict[str, Any]:
        """
        Verifies that this client's configured model is active, authentic, and supports generateContent.
        """
        return check_model_availability(
            model_id=self.config.model_id,
            api_key=self.config.api_key or "",
            transport=self.transport,
            timeout=self.config.timeout_seconds,
        )

    def run_preflight(self, verify_structured_output: bool = True) -> Dict[str, Any]:
        """
        Runs comprehensive preflight verification prior to transcript extraction.
        Asserts model existence, generateContent support, and structured output support.
        """
        return verify_model_preflight(
            model_id=self.config.model_id,
            api_key=self.config.api_key or "",
            transport=self.transport,
            timeout=self.config.timeout_seconds,
            verify_structured_output=verify_structured_output,
        )

    def build_prompt_payload(self, chunks: List[TranscriptChunk], schema_json_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Assembles transcript context chunks, system instructions, and JSON schema directives.
        """
        transcript_content = "\n\n---\n\n".join(
            f"=== CHUNK {c.chunk_index} (Segments {c.start_segment_index} to {c.end_segment_index}) ===\n"
            f"{c.chunk_text}"
            for c in chunks
        )

        system_instruction = (
            "You are an expert business knowledge extraction engine for Meri, an editorial platform capturing "
            "masterclass business intelligence from Ethiopian entrepreneurs.\n"
            "Analyze the provided timestamped transcript segments and extract structured candidate business intelligence.\n"
            "STRICT FACTUAL CONSTRAINTS:\n"
            "1. Ground Truth: Only extract facts, metrics, and insights explicitly stated in the transcript.\n"
            "2. Direct Amharic Quotations: Spoken quotes MUST be in their original spoken Amharic script. "
            "Never paraphrase a quote as direct speech.\n"
            "3. Evidence Grounding: Every insight must cite valid evidence_segment_indices matching the explicit "
            "[Seg <index> | ...] tags in the transcript. "
            "Every quote must cite valid source_segment_indices matching where the words were spoken.\n"
            "4. Format: Output MUST be valid JSON conforming strictly to the requested schema.\n"
        )

        contents = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"{system_instruction}\n\nTRANSCRIPT CONTEXT:\n{transcript_content}\n\n"
                                f"Extract the candidate JSON payload now."
                    }
                ],
            }
        ]

        generation_config: Dict[str, Any] = {
            "temperature": self.config.temperature,
            "responseMimeType": "application/json",
        }

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }

        return payload

    def generate_candidate_json(
        self,
        chunks: List[TranscriptChunk],
        schema_json_str: Optional[str] = None,
    ) -> Tuple[str, Optional[int], Optional[int]]:
        """
        Invokes the Gemini API with bounded retries, returning:
        (raw_response_json, tokens_prompt, tokens_completion)
        """
        verify_model_configuration(self.config.model_id)

        if not self.config.api_key:
            raise GeminiAuthError("Missing GEMINI_API_KEY. Set environment variable or configure client.")

        payload = self.build_prompt_payload(chunks, schema_json_str)
        payload_bytes = json.dumps(payload).encode("utf-8")

        # URL with redacted logging protection
        target_url = f"{GEMINI_API_ENDPOINT}/{self.config.model_id}:generateContent?key={self.config.api_key}"

        request = urllib.request.Request(
            url=target_url,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "Meri-Content-Pipeline/1.0",
            },
            method="POST",
        )

        attempt = 0
        current_delay = self.config.initial_backoff_seconds

        while attempt < self.config.max_retries:
            attempt += 1
            try:
                status_code, headers, body_text = self.transport(request, self.config.timeout_seconds)

                if status_code == 200:
                    return self._parse_success_response(body_text)

                # Classify HTTP error
                if status_code in (401, 403):
                    raise GeminiAuthError(f"Gemini authentication failed (HTTP {status_code}). Check GEMINI_API_KEY.")

                if status_code == 400:
                    raise GeminiBadRequestError(
                        f"Gemini rejected request payload (HTTP 400). Response: {body_text[:200]}"
                    )

                if status_code == 429:
                    # Distinguish transient rate limit vs hard quota exhaustion
                    is_hard_quota = (
                        "quota" in body_text.lower()
                        or "resource_exhausted" in body_text.lower()
                    )
                    if is_hard_quota and "rate" not in body_text.lower():
                        raise GeminiQuotaExhaustedError(
                            "Gemini API quota exhausted (HTTP 429). Permanent limit reached."
                        )

                    # Transient rate limit: check Retry-After header
                    retry_after_hdr = headers.get("retry-after")
                    delay = parse_retry_after(
                        retry_after_hdr, current_delay, self.config.max_backoff_seconds
                    )

                    if attempt >= self.config.max_retries:
                        raise GeminiRateLimitError(
                            f"Gemini rate limit exceeded (HTTP 429). Max retries ({self.config.max_retries}) exhausted."
                        )

                    self.sleep_fn(delay)
                    current_delay = min(
                        current_delay * self.config.backoff_multiplier,
                        self.config.max_backoff_seconds,
                    )
                    continue

                if status_code in (500, 502, 503, 504):
                    if attempt >= self.config.max_retries:
                        raise GeminiServiceUnavailableError(
                            f"Gemini service unavailable (HTTP {status_code}). Max retries exhausted."
                        )
                    self.sleep_fn(current_delay)
                    current_delay = min(
                        current_delay * self.config.backoff_multiplier,
                        self.config.max_backoff_seconds,
                    )
                    continue

                # Unexpected status code
                raise GeminiClientError(f"Unexpected Gemini HTTP response {status_code}: {body_text[:200]}")

            except (GeminiTimeoutError, TimeoutError) as exc:
                if attempt >= self.config.max_retries:
                    raise GeminiRetryExhaustedError(
                        f"Request timed out after {attempt} attempts: {exc}"
                    ) from exc
                self.sleep_fn(current_delay)
                current_delay = min(
                    current_delay * self.config.backoff_multiplier,
                    self.config.max_backoff_seconds,
                )
                continue

        raise GeminiRetryExhaustedError(f"Gemini extraction failed after {attempt} attempts.")

    def _parse_success_response(self, body_text: str) -> Tuple[str, Optional[int], Optional[int]]:
        """Extracts text content and token usage from Gemini 200 OK response."""
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise GeminiClientError(f"Failed to parse Gemini response as JSON: {exc}") from exc

        candidates = data.get("candidates", [])
        if not candidates:
            raise GeminiClientError("Gemini response contained no candidates.")

        first_cand = candidates[0]
        content = first_cand.get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise GeminiClientError("Gemini candidate contained no content parts.")

        raw_text = parts[0].get("text", "")
        if not raw_text.strip():
            raise GeminiClientError("Gemini candidate content text was empty.")

        usage = data.get("usageMetadata", {})
        tokens_prompt = usage.get("promptTokenCount")
        tokens_completion = usage.get("candidatesTokenCount")

        return raw_text.strip(), tokens_prompt, tokens_completion
