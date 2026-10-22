"""
Meri Content Pipeline v1: Unit tests for Gemini API Client.
Tests configurable model IDs, mock transport, bounded retries, Retry-After header parsing,
rate limiting vs. quota exhaustion distinction, and immediate rejection of non-retryable errors.
"""

import os
import unittest
import urllib.request

from backend.src.gemini_client import (
    GeminiAuthError,
    GeminiBadRequestError,
    GeminiClient,
    GeminiConfig,
    GeminiModelConfigError,
    GeminiQuotaExhaustedError,
    GeminiRateLimitError,
    GeminiRetryExhaustedError,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
    check_model_availability,
    parse_retry_after,
    validate_model_id_syntax,
    verify_model_configuration,
)
from backend.src.models import TranscriptChunk


class TestGeminiClient(unittest.TestCase):
    """Test suite for GeminiClient and transport behaviors."""

    def setUp(self) -> None:
        self.sample_chunk = TranscriptChunk(
            chunk_index=0,
            start_segment_index=0,
            end_segment_index=1,
            start_ms=0,
            end_ms=10000,
            token_count_estimate=7,
            chunk_text="[00:00:00 - 00:00:10] Speaker: ሰላም እንኳን ደህና መጣችሁ።",
        )
        self.sleep_calls = []

        def mock_sleep(seconds: float) -> None:
            self.sleep_calls.append(seconds)

        self.mock_sleep = mock_sleep

    def test_configurable_model_id_and_validation(self) -> None:
        """Verifies model ID is configurable via config or environment, and strictly validated."""
        # Valid model identifiers
        for valid_id in ["gemini-2.0-flash", "gemini-1.5-pro-002", "custom_model.v1", "gemini-exp-1206"]:
            verify_model_configuration(valid_id)
            config = GeminiConfig(model_id=valid_id, api_key="test-key")
            self.assertEqual(config.model_id, valid_id)

        # Invalid model identifiers
        for invalid_id in ["", "   ", "m", "model with spaces", "bad@id!", "x" * 65]:
            with self.assertRaises(GeminiModelConfigError):
                verify_model_configuration(invalid_id)

        # Environment variable override
        old_env = os.environ.get("GEMINI_MODEL_ID")
        try:
            os.environ["GEMINI_MODEL_ID"] = "gemini-future-pro"
            config = GeminiConfig(api_key="test-key")
            self.assertEqual(config.model_id, "gemini-future-pro")
        finally:
            if old_env is not None:
                os.environ["GEMINI_MODEL_ID"] = old_env
            else:
                os.environ.pop("GEMINI_MODEL_ID", None)

    def test_parse_retry_after(self) -> None:
        """Verifies parsing of integer seconds and fallback behavior."""
        self.assertEqual(parse_retry_after("5", default_delay=1.0, max_delay=30.0), 5.0)
        self.assertEqual(parse_retry_after("120", default_delay=1.0, max_delay=30.0), 30.0)  # Clamped to max
        self.assertEqual(parse_retry_after(None, default_delay=2.5, max_delay=30.0), 2.5)
        self.assertEqual(parse_retry_after("invalid-header", default_delay=2.5, max_delay=30.0), 2.5)

    def test_successful_response_parsing(self) -> None:
        """Verifies parsing of standard Gemini 200 OK candidate response."""
        response_json = """{
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "{\\"schema_version\\": \\"1.0.0\\"}"}
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 512,
                "candidatesTokenCount": 128
            }
        }"""

        def mock_transport(req: urllib.request.Request, timeout: float):
            return 200, {}, response_json

        client = GeminiClient(
            config=GeminiConfig(api_key="test-key"),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        text, prompt_tokens, comp_tokens = client.generate_candidate_json([self.sample_chunk])
        self.assertEqual(text, '{"schema_version": "1.0.0"}')
        self.assertEqual(prompt_tokens, 512)
        self.assertEqual(comp_tokens, 128)
        self.assertEqual(len(self.sleep_calls), 0)

    def test_transient_rate_limit_with_exponential_backoff(self) -> None:
        """Verifies 429 transient rate limits trigger bounded retry with exponential backoff."""
        attempts = 0
        response_json = '{"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}'

        def mock_transport(req: urllib.request.Request, timeout: float):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return 429, {"retry-after": "2"}, "Resource rate limit exceeded, please backoff."
            return 200, {}, response_json

        client = GeminiClient(
            config=GeminiConfig(
                api_key="test-key",
                max_retries=3,
                initial_backoff_seconds=1.0,
                backoff_multiplier=2.0,
            ),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        text, _, _ = client.generate_candidate_json([self.sample_chunk])
        self.assertEqual(text, "{}")
        self.assertEqual(attempts, 3)
        self.assertEqual(len(self.sleep_calls), 2)
        # First retry respected Retry-After: 2s
        self.assertEqual(self.sleep_calls[0], 2.0)

    def test_quota_exhausted_raises_immediately_without_retry(self) -> None:
        """Verifies hard quota exhaustion is distinguished from rate limits and NOT retried."""
        attempts = 0

        def mock_transport(req: urllib.request.Request, timeout: float):
            nonlocal attempts
            attempts += 1
            return 429, {}, "RESOURCE_EXHAUSTED: You have exceeded your quota."

        client = GeminiClient(
            config=GeminiConfig(api_key="test-key", max_retries=3),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        with self.assertRaises(GeminiQuotaExhaustedError):
            client.generate_candidate_json([self.sample_chunk])

        # Must fail on the very first attempt without looping retries
        self.assertEqual(attempts, 1)
        self.assertEqual(len(self.sleep_calls), 0)

    def test_authentication_error_rejects_immediately(self) -> None:
        """Verifies 401/403 auth failures fail immediately without retry."""
        attempts = 0

        def mock_transport(req: urllib.request.Request, timeout: float):
            nonlocal attempts
            attempts += 1
            return 401, {}, "API key not valid."

        client = GeminiClient(
            config=GeminiConfig(api_key="bad-key", max_retries=3),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        with self.assertRaises(GeminiAuthError):
            client.generate_candidate_json([self.sample_chunk])

        self.assertEqual(attempts, 1)
        self.assertEqual(len(self.sleep_calls), 0)

    def test_bad_request_error_rejects_immediately(self) -> None:
        """Verifies 400 Bad Request fails immediately without retry."""
        attempts = 0

        def mock_transport(req: urllib.request.Request, timeout: float):
            nonlocal attempts
            attempts += 1
            return 400, {}, "Invalid JSON payload structure."

        client = GeminiClient(
            config=GeminiConfig(api_key="test-key", max_retries=3),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        with self.assertRaises(GeminiBadRequestError):
            client.generate_candidate_json([self.sample_chunk])

        self.assertEqual(attempts, 1)
        self.assertEqual(len(self.sleep_calls), 0)

    def test_service_unavailable_exhaustion(self) -> None:
        """Verifies 503 service unavailable retries up to max_retries before exhausting."""
        attempts = 0

        def mock_transport(req: urllib.request.Request, timeout: float):
            nonlocal attempts
            attempts += 1
            return 503, {}, "Service Temporarily Unavailable"

        client = GeminiClient(
            config=GeminiConfig(
                api_key="test-key",
                max_retries=3,
                initial_backoff_seconds=1.0,
                backoff_multiplier=2.0,
            ),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        with self.assertRaises(GeminiServiceUnavailableError):
            client.generate_candidate_json([self.sample_chunk])

        self.assertEqual(attempts, 3)
        self.assertEqual(len(self.sleep_calls), 2)
        self.assertEqual(self.sleep_calls, [1.0, 2.0])

    def test_timeout_retry_exhaustion(self) -> None:
        """Verifies transport timeouts trigger retries and eventually raise GeminiRetryExhaustedError."""
        attempts = 0

        def mock_transport(req: urllib.request.Request, timeout: float):
            nonlocal attempts
            attempts += 1
            raise GeminiTimeoutError("Connection timed out after 30s")

        client = GeminiClient(
            config=GeminiConfig(
                api_key="test-key",
                max_retries=3,
                initial_backoff_seconds=0.5,
                backoff_multiplier=2.0,
            ),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        with self.assertRaises(GeminiRetryExhaustedError):
            client.generate_candidate_json([self.sample_chunk])

        self.assertEqual(attempts, 3)
        self.assertEqual(len(self.sleep_calls), 2)
        self.assertEqual(self.sleep_calls, [0.5, 1.0])

    def test_syntax_validation_distinct_from_availability_check(self) -> None:
        """Verifies syntax check evaluates local string format without remote network calls."""
        # Valid syntax passes without network
        validate_model_id_syntax("gemini-2.0-flash")
        validate_model_id_syntax("future-model.v3")

        # Invalid syntax fails locally
        with self.assertRaises(GeminiModelConfigError):
            validate_model_id_syntax("bad identifier with spaces")

    def test_check_model_availability_success_with_generate_content(self) -> None:
        """Verifies remote availability check passes when model exists and supports generateContent."""
        model_metadata_json = """{
            "name": "models/gemini-2.0-flash",
            "version": "001",
            "displayName": "Gemini 2.0 Flash",
            "supportedGenerationMethods": ["generateContent", "countTokens"]
        }"""

        def mock_transport(req: urllib.request.Request, timeout: float):
            self.assertEqual(req.get_method(), "GET")
            self.assertIn("gemini-2.0-flash", req.full_url)
            return 200, {}, model_metadata_json

        client = GeminiClient(
            config=GeminiConfig(model_id="gemini-2.0-flash", api_key="test-key"),
            transport=mock_transport,
        )

        data = client.check_availability()
        self.assertEqual(data["displayName"], "Gemini 2.0 Flash")
        self.assertIn("generateContent", data["supportedGenerationMethods"])

    def test_check_model_availability_fails_on_missing_generate_content(self) -> None:
        """Rejects model that exists but does not support generateContent (e.g. embedding-only)."""
        model_metadata_json = """{
            "name": "models/text-embedding-004",
            "supportedGenerationMethods": ["embedContent"]
        }"""

        def mock_transport(req: urllib.request.Request, timeout: float):
            return 200, {}, model_metadata_json

        client = GeminiClient(
            config=GeminiConfig(model_id="text-embedding-004", api_key="test-key"),
            transport=mock_transport,
        )

        with self.assertRaises(GeminiModelConfigError) as ctx:
            client.check_availability()
        self.assertIn("does not support 'generateContent'", str(ctx.exception))

    def test_check_model_availability_fails_on_404_not_found(self) -> None:
        """Rejects unavailable or non-existent model ID with GeminiModelConfigError."""
        def mock_transport(req: urllib.request.Request, timeout: float):
            return 404, {}, '{"error": {"message": "Model not found"}}'

        client = GeminiClient(
            config=GeminiConfig(model_id="gemini-nonexistent-model", api_key="test-key"),
            transport=mock_transport,
        )

        with self.assertRaises(GeminiModelConfigError) as ctx:
            client.check_availability()
        self.assertIn("was not found on Gemini API (HTTP 404)", str(ctx.exception))

    def test_check_model_availability_fails_on_auth_error(self) -> None:
        """Rejects invalid API keys with GeminiAuthError during availability check."""
        def mock_transport(req: urllib.request.Request, timeout: float):
            return 401, {}, '{"error": {"message": "API key not valid"}}'

        client = GeminiClient(
            config=GeminiConfig(model_id="gemini-2.0-flash", api_key="bad-key"),
            transport=mock_transport,
        )

        with self.assertRaises(GeminiAuthError):
            client.check_availability()


if __name__ == "__main__":
    unittest.main()
