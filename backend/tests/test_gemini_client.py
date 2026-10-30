"""
Meri Content Pipeline v1: Unit tests for Gemini API Client.
Tests configurable model IDs, mock transport, bounded retries, Retry-After header parsing,
rate limiting vs. quota exhaustion distinction, and immediate rejection of non-retryable errors.
"""

import json
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
    _redact_secrets,
    check_model_availability,
    parse_retry_after,
    validate_model_id_syntax,
    verify_model_configuration,
    verify_model_preflight,
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

    def test_service_unavailable_respects_retry_after_and_captures_body(self) -> None:
        """Verifies HTTP 503 respects Retry-After header and captures sanitized error message."""
        attempts = 0
        error_json = json.dumps({
            "error": {
                "code": 503,
                "message": "The model is overloaded. Please try again later.",
                "status": "UNAVAILABLE",
            }
        })

        def mock_transport(req: urllib.request.Request, timeout: float):
            nonlocal attempts
            attempts += 1
            return 503, {"retry-after": "5"}, error_json

        client = GeminiClient(
            config=GeminiConfig(
                api_key="test-key",
                max_retries=3,
                initial_backoff_seconds=1.0,
            ),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        with self.assertRaises(GeminiServiceUnavailableError) as ctx:
            client.generate_candidate_json([self.sample_chunk])

        self.assertEqual(attempts, 3)
        # Should sleep for 5.0 seconds each retry due to Retry-After: 5 header
        self.assertEqual(self.sleep_calls, [5.0, 5.0])
        err_msg = str(ctx.exception)
        self.assertIn("The model is overloaded. Please try again later.", err_msg)
        self.assertIn("HTTP 503", err_msg)
        self.assertIn("3 attempts", err_msg)

    def test_service_unavailable_sanitizes_body_secrets(self) -> None:
        """Verifies error responses containing secrets are strictly redacted in exception message."""
        sensitive_body = '{"error": {"message": "Capacity exceeded for key AIzaSyTestSecretKey1234567890123456789"}}'

        def mock_transport(req: urllib.request.Request, timeout: float):
            return 503, {}, sensitive_body

        client = GeminiClient(
            config=GeminiConfig(api_key="test-key", max_retries=1),
            transport=mock_transport,
            sleep_fn=self.mock_sleep,
        )

        with self.assertRaises(GeminiServiceUnavailableError) as ctx:
            client.generate_candidate_json([self.sample_chunk])

        err_msg = str(ctx.exception)
        self.assertNotIn("AIzaSyTestSecretKey1234567890123456789", err_msg)
        self.assertIn("[REDACTED_API_KEY]", err_msg)

    def test_gemini_config_timeout_precedence_explicit_over_env(self) -> None:
        """Verifies explicit constructor timeout_seconds has higher precedence than GEMINI_TIMEOUT_SECONDS."""
        old_timeout = os.environ.get("GEMINI_TIMEOUT_SECONDS")
        try:
            os.environ["GEMINI_TIMEOUT_SECONDS"] = "45.0"
            # Explicit constructor value of 90.0 should NOT be overwritten by 45.0
            config = GeminiConfig(api_key="test-key", timeout_seconds=90.0)
            self.assertEqual(config.timeout_seconds, 90.0)
        finally:
            if old_timeout is not None:
                os.environ["GEMINI_TIMEOUT_SECONDS"] = old_timeout
            else:
                os.environ.pop("GEMINI_TIMEOUT_SECONDS", None)

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

    def test_verify_model_preflight_success_with_structured_output(self) -> None:
        """Verifies preflight confirms both model existence and structured output support."""
        model_metadata_json = """{
            "name": "models/gemini-2.0-flash",
            "displayName": "Gemini 2.0 Flash",
            "supportedGenerationMethods": ["generateContent"]
        }"""
        probe_response_json = """{
            "candidates": [{"content": {"parts": [{"text": "{\\"status\\": \\"ok\\"}"}]}}]
        }"""

        calls = []

        def mock_transport(req: urllib.request.Request, timeout: float):
            calls.append(req.get_method())
            if req.get_method() == "GET":
                return 200, {}, model_metadata_json
            elif req.get_method() == "POST":
                # Verify structured output payload was requested
                req_data = json.loads(req.data.decode("utf-8"))
                self.assertEqual(req_data["generationConfig"]["responseMimeType"], "application/json")
                return 200, {}, probe_response_json
            return 500, {}, "Unknown"

        meta = verify_model_preflight(
            model_id="gemini-2.0-flash",
            api_key="secret-key-12345",
            transport=mock_transport,
            verify_structured_output=True,
        )

        self.assertEqual(meta["displayName"], "Gemini 2.0 Flash")
        self.assertEqual(calls, ["GET", "POST"])

    def test_verify_model_preflight_rejects_unsupported_structured_output(self) -> None:
        """Verifies preflight fails if the model rejects structured output (HTTP 400)."""
        model_metadata_json = """{
            "name": "models/gemini-legacy",
            "supportedGenerationMethods": ["generateContent"]
        }"""

        def mock_transport(req: urllib.request.Request, timeout: float):
            if req.get_method() == "GET":
                return 200, {}, model_metadata_json
            return 400, {}, '{"error": {"message": "Structured output not supported"}}'

        with self.assertRaises(GeminiModelConfigError) as ctx:
            verify_model_preflight(
                model_id="gemini-legacy",
                api_key="secret-key-12345",
                transport=mock_transport,
                verify_structured_output=True,
            )
        self.assertIn("rejected structured output configuration", str(ctx.exception))

    def test_run_preflight_method_on_client(self) -> None:
        """Verifies client.run_preflight() delegates cleanly to verify_model_preflight."""
        model_metadata_json = """{
            "name": "models/gemini-2.0-flash",
            "supportedGenerationMethods": ["generateContent"]
        }"""
        probe_response_json = '{"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}'

        def mock_transport(req: urllib.request.Request, timeout: float):
            if req.get_method() == "GET":
                return 200, {}, model_metadata_json
            return 200, {}, probe_response_json

        client = GeminiClient(
            config=GeminiConfig(model_id="gemini-2.0-flash", api_key="secret-key"),
            transport=mock_transport,
        )
        meta = client.run_preflight()
        self.assertIn("generateContent", meta["supportedGenerationMethods"])

    def test_api_key_never_logged_or_exposed_in_exceptions(self) -> None:
        """Verifies that API keys are strictly redacted in any transport errors or URL logs."""
        raw_key = "super-secret-api-key-99999"

        # Test URL redaction helper directly
        raw_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash?key={raw_key}&other=val"
        redacted = _redact_secrets(raw_url)
        self.assertNotIn(raw_key, redacted)
        self.assertIn("key=[REDACTED]", redacted)

        # Test transport error redaction
        def mock_failing_transport(req: urllib.request.Request, timeout: float):
            raise urllib.error.URLError(f"Connection failed to {req.full_url}")

        with self.assertRaises(Exception) as ctx:
            check_model_availability(
                model_id="gemini-2.0-flash",
                api_key=raw_key,
                transport=mock_failing_transport,
            )
        self.assertNotIn(raw_key, str(ctx.exception))
        self.assertIn("[REDACTED]", str(ctx.exception))

    def test_gemini_config_timeout_env_and_default(self) -> None:
        """Verifies timeout defaults to 60.0s and is configurable via GEMINI_TIMEOUT_SECONDS."""
        # Default timeout
        config_default = GeminiConfig(api_key="test-key")
        self.assertEqual(config_default.timeout_seconds, 60.0)

        # Environment variable override
        old_timeout = os.environ.get("GEMINI_TIMEOUT_SECONDS")
        try:
            os.environ["GEMINI_TIMEOUT_SECONDS"] = "45.5"
            config_env = GeminiConfig(api_key="test-key")
            self.assertEqual(config_env.timeout_seconds, 45.5)

            # Invalid env value should not crash; falls back to default
            os.environ["GEMINI_TIMEOUT_SECONDS"] = "invalid_not_a_number"
            config_invalid = GeminiConfig(api_key="test-key")
            self.assertEqual(config_invalid.timeout_seconds, 60.0)
        finally:
            if old_timeout is not None:
                os.environ["GEMINI_TIMEOUT_SECONDS"] = old_timeout
            else:
                os.environ.pop("GEMINI_TIMEOUT_SECONDS", None)

    def test_timeout_error_message_includes_timeout_duration(self) -> None:
        """Verifies GeminiRetryExhaustedError clearly reports the configured timeout duration."""
        def mock_timing_out_transport(req: urllib.request.Request, timeout: float):
            raise GeminiTimeoutError("The read operation timed out")

        client = GeminiClient(
            config=GeminiConfig(api_key="test-key", max_retries=2, timeout_seconds=45.0),
            transport=mock_timing_out_transport,
            sleep_fn=self.mock_sleep,
        )

        with self.assertRaises(GeminiRetryExhaustedError) as ctx:
            client.generate_candidate_json([self.sample_chunk])

        err_str = str(ctx.exception)
        self.assertIn("timeout=45.0s", err_str)
        self.assertIn("2 attempts", err_str)
        self.assertIn("The read operation timed out", err_str)


    def test_build_prompt_payload_embeds_canonical_schema_and_contract(self) -> None:
        """Verifies build_prompt_payload embeds the canonical schema and required field taxonomy."""
        client = GeminiClient(config=GeminiConfig(api_key="test-key"))
        payload = client.build_prompt_payload([self.sample_chunk])

        self.assertIn("contents", payload)
        self.assertIn("generationConfig", payload)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")

        prompt_text = payload["contents"][0]["parts"][0]["text"]

        # Assert required top-level keys are explicitly mandated in prompt text
        self.assertIn("schema_version", prompt_text)
        self.assertIn("1.0.0", prompt_text)
        self.assertIn("episode_summary", prompt_text)
        self.assertIn("guest_profile", prompt_text)
        self.assertIn("journey_milestones", prompt_text)
        self.assertIn("insights", prompt_text)
        self.assertIn("quotations", prompt_text)
        self.assertIn("suggested_tags", prompt_text)

        # Assert insight categories and constraints
        self.assertIn("Operations", prompt_text)
        self.assertIn("Fintech", prompt_text)
        self.assertIn("Technology & Infrastructure", prompt_text)
        self.assertIn("evidence_segment_indices", prompt_text)
        self.assertIn("source_segment_indices", prompt_text)
        self.assertIn("amharic_quote", prompt_text)

        # Assert JSON schema specification is embedded
        self.assertIn("JSON SCHEMA SPECIFICATION:", prompt_text)
        self.assertIn("https://meri.et/schemas/gemini_extraction_schema.v1.json", prompt_text)

    def test_build_prompt_payload_uses_explicit_schema_json_str(self) -> None:
        """Verifies that an explicitly provided schema_json_str is embedded instead of default."""
        client = GeminiClient(config=GeminiConfig(api_key="test-key"))
        custom_schema = '{"title": "CustomTestSchema", "type": "object"}'
        payload = client.build_prompt_payload([self.sample_chunk], schema_json_str=custom_schema)

        prompt_text = payload["contents"][0]["parts"][0]["text"]
        self.assertIn("CustomTestSchema", prompt_text)
        self.assertNotIn("https://meri.et/schemas/gemini_extraction_schema.v1.json", prompt_text)


if __name__ == "__main__":
    unittest.main()
