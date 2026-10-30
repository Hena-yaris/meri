"""
Meri Content Pipeline v1: Unit and Integration Tests for Isolated Extraction Validation CLI.

Milestone 7.3: Isolated Gemini Extraction Validation Test Suite:
1. Synthetic transcript successfully parses and normalizes.
2. Deterministic fake extraction produces a valid local report (exit code 0).
3. Missing explicit network opt-in rejects Gemini selection before provider invocation (exit code 2).
4. Missing API key rejects Gemini selection before provider invocation (exit code 2).
5. Fake provider never makes network requests (assert 0 HTTP/socket calls).
6. Invalid structured output is reported as a validation failure (exit code 1).
7. Invalid evidence references or unsupported quotations are rejected (exit code 1).
8. Provider errors produce safe diagnostics without leaking secrets (exit code 2).
9. Command never constructs a database connection.
10. Command never calls ingestion worker or persistence functions.
11. Exit codes distinguish success (0), validation failure (1), and configuration/provider failure (2).
12. Output file generation and transcript source classification safety.
"""

import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List
import unittest
from unittest.mock import MagicMock, patch

from backend.src.candidate_persistence import CandidatePersistenceService
from backend.src.chunker import TranscriptChunker
from backend.src.extraction_models import (
    CandidateExtractionPayload,
    ExtractionRunRecord,
    ValidationErrorCode,
    ValidationErrorItem,
    ValidationSeverity,
    ValidationStatus,
)
from backend.src.extraction_service import ExtractionService
from backend.src.gemini_client import (
    GeminiClient,
    GeminiConfig,
    GeminiTimeoutError,
)
from backend.src.pipeline_cli import (
    build_parser,
    classify_transcript_source,
    main,
    run_validate_extraction,
)
from backend.src.transcript_normalizer import TranscriptNormalizer
from backend.src.transcript_parser import parse_transcript
from backend.tests.fake_extraction_provider import (
    DeterministicFakeExtractor,
    create_deterministic_synthetic_payload,
)

FIXTURE_PATH = "backend/tests/fixtures/sample_transcript.json"


class TestValidateExtractionCli(unittest.TestCase):
    """Test suite for Milestone 7.3 validate-extraction CLI command."""

    def setUp(self) -> None:
        self.parser = build_parser()
        self.fixture_file = Path(FIXTURE_PATH)
        self.assertTrue(self.fixture_file.is_file(), f"Fixture file not found: {FIXTURE_PATH}")

    # 1. Synthetic transcript successfully parses and normalizes
    def test_synthetic_transcript_parses_and_normalizes(self) -> None:
        raw_content = self.fixture_file.read_text(encoding="utf-8")
        cues = parse_transcript(raw_content)
        self.assertEqual(len(cues), 4)

        normalizer = TranscriptNormalizer()
        segments = normalizer.normalize(cues)
        self.assertEqual(len(segments), 4)

        chunker = TranscriptChunker()
        chunks = chunker.chunk(segments)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertIn("Dawit Tadesse", chunks[0].chunk_text)
        self.assertIn("የቀዝቃዛ ሰንሰለት ሎጂስቲክስ", chunks[0].chunk_text)

    # 2. Deterministic fake extraction produces a valid report
    def test_deterministic_fake_extraction_produces_valid_report(self) -> None:
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
            ])

        self.assertEqual(exit_code, 0)
        output = stdout_buf.getvalue()
        report = json.loads(output)

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["run_mode"], "offline_fake")
        self.assertEqual(report["transcript_source"], "synthetic_test_fixture")
        self.assertEqual(report["provider"], "fake")
        self.assertEqual(report["model_id"], "gemini-2.0-flash")

        # Counts
        counts = report["counts"]
        self.assertEqual(counts["segments"], 4)
        self.assertEqual(counts["chunks"], 1)
        self.assertEqual(counts["insights"], 2)
        self.assertEqual(counts["quotations"], 2)
        self.assertEqual(counts["evidence_references"], 2)
        self.assertEqual(counts["quotation_segments"], 2)
        self.assertEqual(counts["milestones"], 2)
        self.assertTrue(counts["has_episode_summary"])
        self.assertTrue(counts["has_guest_profile"])

        # Validation status
        validation = report["validation"]
        self.assertTrue(validation["schema_valid"])
        self.assertTrue(validation["evidence_grounded"])
        self.assertTrue(validation["provenance_valid"])
        self.assertEqual(validation["error_count"], 0)
        self.assertEqual(validation["warning_count"], 0)
        self.assertEqual(validation["errors"], [])

        # Disclaimer
        self.assertIn("successful structural and evidence validation does not prove factual accuracy", report["disclaimer"].lower())

    # 3. Missing explicit network opt-in rejects Gemini selection before provider invocation
    def test_missing_network_opt_in_rejects_gemini(self) -> None:
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "gemini",
            ])

        self.assertEqual(exit_code, 2)
        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["run_mode"], "gemini_live")
        self.assertEqual(report["validation"]["errors"][0]["error_code"], "NETWORK_OPT_IN_REQUIRED")
        self.assertIn("--allow-network", report["validation"]["errors"][0]["message"])

    # 4. Missing API key rejects Gemini selection before provider invocation
    @patch("backend.src.pipeline_cli.load_env_file", return_value=False)
    @patch("urllib.request.urlopen")
    def test_missing_api_key_rejects_gemini(
        self,
        mock_urlopen: MagicMock,
        mock_load_env: MagicMock,
    ) -> None:
        stdout_buf = io.StringIO()
        env_without_gemini = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with patch.dict(os.environ, env_without_gemini, clear=True), patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "gemini",
                "--allow-network",
            ])

        self.assertEqual(exit_code, 2)
        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["run_mode"], "gemini_live")
        self.assertEqual(report["validation"]["errors"][0]["error_code"], "MISSING_GEMINI_API_KEY")
        self.assertIn("GEMINI_API_KEY", report["validation"]["errors"][0]["message"])
        mock_urlopen.assert_not_called()

    # 5. The fake provider never makes network requests
    @patch("urllib.request.urlopen")
    @patch("http.client.HTTPConnection.connect")
    def test_fake_provider_never_makes_network_requests(
        self,
        mock_http_connect: MagicMock,
        mock_urlopen: MagicMock,
    ) -> None:
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
            ])

        self.assertEqual(exit_code, 0)
        mock_urlopen.assert_not_called()
        mock_http_connect.assert_not_called()

    # 6. Invalid structured output is reported as a validation failure
    def test_invalid_structured_output_reported_as_validation_failure(self) -> None:
        extractor = DeterministicFakeExtractor(failure_mode="invalid_json")
        fake_service = extractor.create_extraction_service()

        args = self.parser.parse_args([
            "validate-extraction",
            "--transcript-file", str(self.fixture_file),
            "--provider", "fake",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=fake_service)

        self.assertEqual(exit_code, 1)
        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "validation_failed")
        self.assertFalse(report["validation"]["schema_valid"])
        self.assertGreater(report["validation"]["error_count"], 0)
        error_codes = [e["error_code"] for e in report["validation"]["errors"]]
        self.assertIn(ValidationErrorCode.MALFORMED_JSON.value, error_codes)

    # 7. Unsupported quotations are rejected
    def test_unsupported_quotations_rejected(self) -> None:
        extractor = DeterministicFakeExtractor(failure_mode="semantic_error")
        fake_service = extractor.create_extraction_service()

        args = self.parser.parse_args([
            "validate-extraction",
            "--transcript-file", str(self.fixture_file),
            "--provider", "fake",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=fake_service)

        self.assertEqual(exit_code, 1)
        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "validation_failed")
        self.assertFalse(report["validation"]["evidence_grounded"])
        error_codes = [e["error_code"] for e in report["validation"]["errors"]]
        self.assertIn(ValidationErrorCode.QUOTE_NOT_IN_SOURCE.value, error_codes)
        error_messages = [e["message"] for e in report["validation"]["errors"]]
        self.assertTrue(any("not found verbatim" in m for m in error_messages))

    # 7b. Invalid evidence segment reference is rejected
    def test_invalid_evidence_segment_reference_rejected(self) -> None:
        payload_data = create_deterministic_synthetic_payload(
            evidence_segment_indices_insight_0=[999],
        )
        fake_client = MagicMock()
        fake_client.generate_candidate_json.return_value = (json.dumps(payload_data), 100, 100)
        fake_client.config = GeminiConfig(model_id="gemini-2.0-flash", api_key="synthetic-test-key")
        service = ExtractionService(gemini_client=fake_client)

        args = self.parser.parse_args([
            "validate-extraction",
            "--transcript-file", str(self.fixture_file),
            "--provider", "fake",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=service)

        self.assertEqual(exit_code, 1)
        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "validation_failed")
        error_codes = [e["error_code"] for e in report["validation"]["errors"]]
        self.assertIn(ValidationErrorCode.SEGMENT_NOT_FOUND.value, error_codes)

    # 8. Provider errors produce safe diagnostics without leaking secrets
    def test_provider_errors_produce_safe_diagnostics_without_leaking_secrets(self) -> None:
        secret_key = "AIzaSySecretApiKeyThatMustNeverLeak1234"
        sensitive_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={secret_key}"
        fake_client = MagicMock()
        fake_client.generate_candidate_json.side_effect = GeminiTimeoutError(
            f"Network transport error calling {sensitive_url}"
        )
        fake_client.config = GeminiConfig(model_id="gemini-2.0-flash", api_key="test-key")
        service = ExtractionService(gemini_client=fake_client)

        args = self.parser.parse_args([
            "validate-extraction",
            "--transcript-file", str(self.fixture_file),
            "--provider", "fake",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=service)

        self.assertEqual(exit_code, 2)
        raw_output = stdout_buf.getvalue()
        self.assertNotIn(secret_key, raw_output)
        self.assertIn("[REDACTED]", raw_output)

        report = json.loads(raw_output)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["validation"]["errors"][0]["error_code"], "PROVIDER_ERROR")

    # 9. The command never constructs a database connection
    @patch("backend.src.pipeline_cli.create_connection_factory")
    def test_command_never_constructs_database_connection(
        self,
        mock_create_conn: MagicMock,
    ) -> None:
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
            ])

        self.assertEqual(exit_code, 0)
        mock_create_conn.assert_not_called()

    # 10. The command never calls normal ingestion worker or persistence functions
    @patch("backend.src.pipeline_cli.JobWorker")
    @patch.object(CandidatePersistenceService, "persist_candidate_extraction")
    def test_command_never_calls_ingestion_worker_or_persistence(
        self,
        mock_persist: MagicMock,
        mock_worker: MagicMock,
    ) -> None:
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
            ])

        self.assertEqual(exit_code, 0)
        mock_worker.assert_not_called()
        mock_persist.assert_not_called()

    # 11. Command's exit codes distinguish success (0), validation failure (1), and config error (2)
    def test_exit_codes_distinguish_outcomes(self) -> None:
        # Success -> 0
        with patch("sys.stdout", io.StringIO()):
            code_success = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
            ])
        self.assertEqual(code_success, 0)

        # Validation failure (malformed cues / non-json) -> 1
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{ invalid json non-cue content }")
            invalid_file = f.name
        try:
            with patch("sys.stdout", io.StringIO()):
                code_val_fail = main([
                    "validate-extraction",
                    "--transcript-file", invalid_file,
                    "--provider", "fake",
                ])
            self.assertEqual(code_val_fail, 1)
        finally:
            os.unlink(invalid_file)

        # Config / provider error (missing file) -> 2
        with patch("sys.stdout", io.StringIO()):
            code_cfg_error = main([
                "validate-extraction",
                "--transcript-file", "non_existent_file_path_123.json",
                "--provider", "fake",
            ])
        self.assertEqual(code_cfg_error, 2)

    # 12. Output file generation and unverified source classification
    def test_output_file_and_unverified_source_classification(self) -> None:
        test_content = json.dumps({
            "format": "segments_json",
            "language": "am",
            "segments": [
                {
                    "segmentIndex": 0,
                    "startMs": 0,
                    "endMs": 10000,
                    "speakerLabel": "Custom Speaker",
                    "text": "ይህ የአዲስ አበባ ከተማ ንግድ ምክር ቤት መድረክ ነው።",
                }
            ],
        })

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(test_content)
            temp_transcript = f.name

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as out_f:
            report_file = out_f.name

        try:
            stdout_buf = io.StringIO()
            with patch("sys.stdout", stdout_buf):
                exit_code = main([
                    "validate-extraction",
                    "--transcript-file", temp_transcript,
                    "--provider", "fake",
                    "--output-file", report_file,
                ])

            self.assertTrue(Path(report_file).is_file())
            saved_report = json.loads(Path(report_file).read_text(encoding="utf-8"))

            self.assertEqual(saved_report["transcript_source"], "unverified_local_transcript")
            self.assertIn("Notice: Successful structural and evidence validation does not prove factual accuracy", saved_report["disclaimer"])
        finally:
            if os.path.exists(temp_transcript):
                os.unlink(temp_transcript)
            if os.path.exists(report_file):
                os.unlink(report_file)

    # 13. Invalid --request-timeout rejected
    def test_invalid_request_timeout_flag_rejected(self) -> None:
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
                "--request-timeout", "-5.0",
            ])

        self.assertEqual(exit_code, 2)
        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["validation"]["errors"][0]["error_code"], "INVALID_TIMEOUT")

    # 14. Gemini preflight availability check catches non-existent model (404) before extraction
    @patch("backend.src.pipeline_cli.GeminiClient.check_availability")
    def test_gemini_preflight_availability_check_catches_404_model(
        self,
        mock_check_availability: MagicMock,
    ) -> None:
        from backend.src.gemini_client import GeminiModelConfigError
        mock_check_availability.side_effect = GeminiModelConfigError(
            "Configured model 'gemini-3.8-flash' was not found on Gemini API (HTTP 404)."
        )

        stdout_buf = io.StringIO()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-synthetic"}), patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "gemini",
                "--allow-network",
                "--model-id", "gemini-3.8-flash",
                "--request-timeout", "45.0",
            ])

        self.assertEqual(exit_code, 2)
        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["validation"]["errors"][0]["error_code"], "MODEL_AVAILABILITY_ERROR")
        self.assertIn("gemini-3.8-flash", report["validation"]["errors"][0]["message"])
        self.assertIn("HTTP 404", report["validation"]["errors"][0]["message"])


    # 15. Validation report captures redacted raw model responses for debugging
    def test_validation_report_captures_redacted_raw_model_responses(self) -> None:
        """Verifies report includes raw_responses and redacts any secrets."""
        secret_key = "AIzaSyTestApiKeyInsideRawResponse9999"
        raw_model_output = f'{{"insights": [{{"summary": "Test insight with key {secret_key}", "evidence_segment_indices": [1]}}]}}'

        fake_client = MagicMock()
        fake_client.generate_candidate_json.return_value = (raw_model_output, 100, 50)
        fake_client.config = GeminiConfig(model_id="gemini-2.0-flash", api_key="synthetic-test-key")
        service = ExtractionService(gemini_client=fake_client)

        args = self.parser.parse_args([
            "validate-extraction",
            "--transcript-file", str(self.fixture_file),
            "--provider", "fake",
            "--include-raw-responses",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=service)

        self.assertEqual(exit_code, 1)  # Schema validation fails due to missing keys
        report = json.loads(stdout_buf.getvalue())
        self.assertIn("raw_responses", report)
        self.assertEqual(len(report["raw_responses"]), 1)
        # Verify secret was redacted
        self.assertNotIn(secret_key, report["raw_responses"][0])
        self.assertIn("[REDACTED_API_KEY]", report["raw_responses"][0])

    # 16. Validate-extraction CLI supports --reconstruct-rolling flag
    def test_validate_extraction_supports_reconstruct_rolling_flag(self) -> None:
        """Verifies CLI flag --reconstruct-rolling enables RollingCaptionReconstructor."""
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
                "--reconstruct-rolling",
            ])

        self.assertEqual(exit_code, 0)
        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["counts"]["segments"], 4)

    # 17. Default report protects transcript-derived data
    def test_default_validation_report_omits_raw_responses(self) -> None:
        """Verifies that raw model responses are omitted from default report to protect transcript data."""
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
            ])

        self.assertEqual(exit_code, 0)
        report = json.loads(stdout_buf.getvalue())
        self.assertNotIn("raw_responses", report)
        self.assertIn("disclaimer", report)
        self.assertIn("Successful structural and evidence validation does not prove factual accuracy", report["disclaimer"])

    # 18. Validate-extraction with valid --chunk-index 0
    def test_validate_extraction_with_valid_chunk_index(self) -> None:
        """Verifies that selecting chunk 0 executes extraction for exactly that one chunk and reports boundaries."""
        fake_extractor = DeterministicFakeExtractor()
        service = fake_extractor.create_extraction_service()
        service.extract_and_validate = MagicMock(wraps=service.extract_and_validate)

        args = self.parser.parse_args([
            "validate-extraction",
            "--transcript-file", str(self.fixture_file),
            "--provider", "fake",
            "--chunk-index", "0",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=service)

        self.assertEqual(exit_code, 0)
        # Verify extraction service was called exactly once
        self.assertEqual(service.extract_and_validate.call_count, 1)

        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "passed")
        self.assertIsNotNone(report["selected_chunk"])
        sc = report["selected_chunk"]
        self.assertEqual(sc["chunk_index"], 0)
        self.assertEqual(sc["start_segment_index"], 0)
        self.assertGreaterEqual(sc["end_segment_index"], 0)
        self.assertIn("start_ms", sc)
        self.assertIn("end_ms", sc)
        self.assertIn("start_seconds", sc)
        self.assertIn("end_seconds", sc)
        self.assertEqual(report["counts"]["evaluated_chunks"], 1)

    # 19. Negative chunk index is rejected before extraction
    def test_negative_chunk_index_rejected_before_extraction(self) -> None:
        """Verifies negative chunk index exits with code 2 and makes zero extraction calls."""
        mock_service = MagicMock()
        args = self.parser.parse_args([
            "validate-extraction",
            "--transcript-file", str(self.fixture_file),
            "--provider", "fake",
            "--chunk-index", "-1",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=mock_service)

        self.assertEqual(exit_code, 2)
        mock_service.extract_and_validate.assert_not_called()

        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "error")
        errors = report["validation"]["errors"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_code"], "INVALID_CHUNK_INDEX")
        self.assertIn("-1", errors[0]["message"])

    # 20. Out-of-bounds chunk index is rejected before extraction
    def test_out_of_bounds_chunk_index_rejected_before_extraction(self) -> None:
        """Verifies out-of-bounds chunk index exits with code 2 and makes zero extraction calls."""
        mock_service = MagicMock()
        args = self.parser.parse_args([
            "validate-extraction",
            "--transcript-file", str(self.fixture_file),
            "--provider", "fake",
            "--chunk-index", "999",
        ])

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = run_validate_extraction(args, extraction_service=mock_service)

        self.assertEqual(exit_code, 2)
        mock_service.extract_and_validate.assert_not_called()

        report = json.loads(stdout_buf.getvalue())
        self.assertEqual(report["status"], "error")
        errors = report["validation"]["errors"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_code"], "INVALID_CHUNK_INDEX")
        self.assertIn("999", errors[0]["message"])

    # 21. Invalid chunk index rejects before remote Gemini preflight availability check
    def test_invalid_chunk_index_rejects_before_gemini_preflight(self) -> None:
        """Verifies that an invalid chunk index aborts before Gemini check_availability() is called."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-12345"}), \
             patch("backend.src.pipeline_cli.GeminiClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            args = self.parser.parse_args([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "gemini",
                "--allow-network",
                "--chunk-index", "-5",
            ])

            stdout_buf = io.StringIO()
            with patch("sys.stdout", stdout_buf):
                exit_code = run_validate_extraction(args)

            self.assertEqual(exit_code, 2)
            # Assert GeminiClient was never even instantiated and availability was never checked
            mock_client_cls.assert_not_called()
            mock_client.check_availability.assert_not_called()

    # 22. Omitting --chunk-index preserves all-chunks behavior
    def test_omitting_chunk_index_preserves_all_chunks(self) -> None:
        """Verifies that omitting --chunk-index sets selected_chunk to None and processes all chunks."""
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            exit_code = main([
                "validate-extraction",
                "--transcript-file", str(self.fixture_file),
                "--provider", "fake",
            ])

        self.assertEqual(exit_code, 0)
        report = json.loads(stdout_buf.getvalue())
        self.assertIsNone(report["selected_chunk"])
        self.assertEqual(report["counts"]["evaluated_chunks"], report["counts"]["chunks"])


if __name__ == "__main__":
    unittest.main()
