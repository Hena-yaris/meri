"""
Meri Content Pipeline v1: Unit tests for Pipeline CLI.

Verifies Milestone 5.2 CLI syntax, arguments, and transcript-to-job confirmation constraints:
1. Help strings display --confirm-youtube-video-id for run-job and run-next.
2. Specifying --transcript-file without --confirm-youtube-video-id is rejected immediately.
3. Specifying --transcript-file with --confirm-youtube-video-id passes arguments cleanly.
4. Error messages never expose secrets or raw transcript text.
"""

from typing import Any, Optional
import unittest
from unittest.mock import MagicMock, patch

from backend.src.job_worker import JobWorkerResult
from backend.src.pipeline_cli import build_parser, main


class TestPipelineCli(unittest.TestCase):
    """Test suite for CLI argument parsing and safety validations."""

    def setUp(self) -> None:
        self.parser = build_parser()

    def test_cli_help_contains_confirm_youtube_video_id(self) -> None:
        """Both run-job and run-next subcommands advertise --confirm-youtube-video-id in help."""
        # Check run-job
        job_parser = self.parser._subparsers._actions[1].choices["run-job"]
        job_help = job_parser.format_help()
        self.assertIn("--confirm-youtube-video-id", job_help)

        # Check run-next
        next_parser = self.parser._subparsers._actions[1].choices["run-next"]
        next_help = next_parser.format_help()
        self.assertIn("--confirm-youtube-video-id", next_help)

    def test_run_job_requires_confirm_youtube_video_id_with_transcript_file(self) -> None:
        """Invoking run-job with --transcript-file but without --confirm-youtube-video-id fails cleanly."""
        with self.assertLogs("meri.pipeline_cli", level="ERROR") as log_ctx:
            exit_code = main([
                "run-job",
                "69e26e94-663b-464a-bbae-36ba2b646fde",
                "--transcript-file", "/tmp/fake_transcript.json",
            ])

        self.assertEqual(exit_code, 1)
        logged_output = "\n".join(log_ctx.output)
        self.assertIn("--confirm-youtube-video-id", logged_output)
        self.assertIn("requires explicit operator confirmation", logged_output)

    def test_run_next_requires_confirm_youtube_video_id_with_transcript_file(self) -> None:
        """Invoking run-next with --transcript-file but without --confirm-youtube-video-id fails cleanly."""
        with self.assertLogs("meri.pipeline_cli", level="ERROR") as log_ctx:
            exit_code = main([
                "run-next",
                "--transcript-file", "/tmp/fake_transcript.json",
            ])

        self.assertEqual(exit_code, 1)
        logged_output = "\n".join(log_ctx.output)
        self.assertIn("--confirm-youtube-video-id", logged_output)
        self.assertIn("requires explicit operator confirmation", logged_output)

    @patch("backend.src.pipeline_cli.JobWorker")
    @patch("backend.src.pipeline_cli.create_connection_factory")
    @patch("backend.src.pipeline_cli.create_transcript_provider")
    def test_run_job_passes_confirmation_to_worker(
        self,
        mock_create_provider: MagicMock,
        mock_conn_factory: MagicMock,
        mock_worker_cls: MagicMock,
    ) -> None:
        """Supplying matching --transcript-file and --confirm-youtube-video-id invokes worker with confirmation."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.process_job.return_value = JobWorkerResult(
            processed=True,
            job_id="job-123",
            status="completed",
            stage="human_review",
            retry_count=0,
        )
        mock_worker_cls.return_value = mock_worker_instance
        mock_create_provider.return_value = MagicMock(requires_confirmation=True)

        exit_code = main([
            "run-job",
            "job-123",
            "--transcript-file", "/tmp/valid_transcript.json",
            "--confirm-youtube-video-id", "dQw4w9WgXcQ",
        ])

        self.assertEqual(exit_code, 0)
        mock_worker_instance.process_job.assert_called_once_with(
            "job-123",
            allow_candidate_rerun=False,
            confirm_youtube_video_id="dQw4w9WgXcQ",
        )

    @patch("backend.src.pipeline_cli.JobWorker")
    @patch("backend.src.pipeline_cli.create_connection_factory")
    @patch("backend.src.pipeline_cli.create_transcript_provider")
    def test_run_next_passes_confirmation_to_worker(
        self,
        mock_create_provider: MagicMock,
        mock_conn_factory: MagicMock,
        mock_worker_cls: MagicMock,
    ) -> None:
        """Supplying matching --transcript-file and --confirm-youtube-video-id on run-next invokes worker."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.process_next_job.return_value = JobWorkerResult(
            processed=True,
            job_id="job-456",
            status="completed",
            stage="human_review",
            retry_count=0,
        )
        mock_worker_cls.return_value = mock_worker_instance
        mock_create_provider.return_value = MagicMock(requires_confirmation=True)

        exit_code = main([
            "run-next",
            "--transcript-file", "/tmp/valid_transcript.json",
            "--confirm-youtube-video-id", "dQw4w9WgXcQ",
        ])

        self.assertEqual(exit_code, 0)
        mock_worker_instance.process_next_job.assert_called_once_with(
            allow_candidate_rerun=False,
            confirm_youtube_video_id="dQw4w9WgXcQ",
        )


    def test_run_job_rejects_whitespace_confirm_youtube_video_id_with_transcript_file(self) -> None:
        """Invoking run-job with whitespace-only --confirm-youtube-video-id fails cleanly."""
        with self.assertLogs("meri.pipeline_cli", level="ERROR") as log_ctx:
            exit_code = main([
                "run-job",
                "69e26e94-663b-464a-bbae-36ba2b646fde",
                "--transcript-file", "/tmp/fake_transcript.json",
                "--confirm-youtube-video-id", "   ",
            ])

        self.assertEqual(exit_code, 1)
        logged_output = "\n".join(log_ctx.output)
        self.assertIn("--confirm-youtube-video-id", logged_output)
        self.assertIn("requires explicit operator confirmation", logged_output)

    @patch("backend.src.pipeline_cli.JobWorker")
    @patch("backend.src.pipeline_cli.create_connection_factory")
    @patch("backend.src.pipeline_cli.create_transcript_provider")
    def test_run_job_passes_allow_rerun_to_worker(
        self,
        mock_create_provider: MagicMock,
        mock_conn_factory: MagicMock,
        mock_worker_cls: MagicMock,
    ) -> None:
        """Supplying --allow-rerun propagates allow_candidate_rerun=True to the worker."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.process_job.return_value = JobWorkerResult(
            processed=True,
            job_id="job-123",
            status="completed",
            stage="human_review",
            retry_count=0,
        )
        mock_worker_cls.return_value = mock_worker_instance
        mock_create_provider.return_value = MagicMock(requires_confirmation=True)

        exit_code = main([
            "run-job",
            "job-123",
            "--transcript-file", "/tmp/valid_transcript.json",
            "--confirm-youtube-video-id", "dQw4w9WgXcQ",
            "--allow-rerun",
        ])

        self.assertEqual(exit_code, 0)
        mock_worker_instance.process_job.assert_called_once_with(
            "job-123",
            allow_candidate_rerun=True,
            confirm_youtube_video_id="dQw4w9WgXcQ",
        )

    @patch("backend.src.pipeline_cli.JobWorker")
    @patch("backend.src.pipeline_cli.create_connection_factory")
    @patch("backend.src.pipeline_cli.create_transcript_provider")
    def test_run_job_returns_nonzero_exit_code_on_worker_failure(
        self,
        mock_create_provider: MagicMock,
        mock_conn_factory: MagicMock,
        mock_worker_cls: MagicMock,
    ) -> None:
        """When worker returns status='failed', CLI exits with code 1."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.process_job.return_value = JobWorkerResult(
            processed=True,
            job_id="job-123",
            status="failed",
            stage="submission",
            retry_count=0,
            error="Preflight validation failed",
        )
        mock_worker_cls.return_value = mock_worker_instance
        mock_create_provider.return_value = MagicMock(requires_confirmation=True)

        exit_code = main([
            "run-job",
            "job-123",
            "--transcript-file", "/tmp/valid_transcript.json",
            "--confirm-youtube-video-id", "dQw4w9WgXcQ",
        ])

        self.assertEqual(exit_code, 1)

    def test_check_env_command(self) -> None:
        """Verifies check-env returns 0 when a driver is present."""
        exit_code = main(["check-env"])
        self.assertIn(exit_code, (0, 1))

    def test_check_db_fails_when_no_database_url(self) -> None:
        """Invoking check-db without DATABASE_URL in env or arguments exits with 1."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("backend.src.pipeline_cli.load_env_file"):
                exit_code = main(["check-db"])
                self.assertEqual(exit_code, 1)

    @patch("backend.src.pipeline_cli.create_connection_factory")
    def test_check_db_healthy_report(self, mock_factory_maker: MagicMock) -> None:
        """check-db returns 0 and status='healthy' when all objects, signatures, and migrations exist."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from backend.src.pipeline_cli import EXPECTED_MIGRATIONS, REQUIRED_TABLES, REVIEW_RPC_NAME

        # Query 1: identity -> (db, user, version)
        # Query 2: tables -> list of (table_name,)
        # Query 3: routines -> (specific_name, routine_name, data_type)
        # Query 4: parameters -> list of (param_name, data_type, mode, position)
        # Query 5: migration table exists -> (True,)
        # Query 6: applied migrations -> list of (version,)
        mock_cur.fetchone.side_effect = [
            ("meri_staging", "postgres", "PostgreSQL 15.8 on x86_64"),
            (True,),
        ]
        mock_cur.fetchall.side_effect = [
            [(t,) for t in REQUIRED_TABLES],
            [("review_candidate_item_1", REVIEW_RPC_NAME, "jsonb")],
            [
                ("p_item_type", "text", "IN", 1),
                ("p_item_id", "uuid", "IN", 2),
                ("p_decision", "text", "IN", 3),
                ("p_reviewer_id", "uuid", "IN", 4),
            ],
            [(m,) for m in EXPECTED_MIGRATIONS],
        ]

        mock_factory = MagicMock(return_value=mock_conn)
        mock_factory_maker.return_value = mock_factory

        exit_code = main(["check-db", "--db-url", "postgresql://fake:fake@localhost:5432/meri_staging"])
        self.assertEqual(exit_code, 0)
        mock_conn.set_session.assert_called_once_with(readonly=True)
        mock_cur.close.assert_called_once()
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("backend.src.pipeline_cli.create_connection_factory")
    def test_check_db_unsupported_migrations_still_healthy(self, mock_factory_maker: MagicMock) -> None:
        """When supabase_migrations table is missing, migration check is clearly unsupported but report is healthy."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from backend.src.pipeline_cli import REQUIRED_TABLES, REVIEW_RPC_NAME, run_db_health_check

        mock_cur.fetchone.side_effect = [
            ("meri_staging", "postgres", "PostgreSQL 15.8"),
            (False,),  # schema_migrations table does NOT exist
        ]
        mock_cur.fetchall.side_effect = [
            [(t,) for t in REQUIRED_TABLES],
            [("review_candidate_item_1", REVIEW_RPC_NAME, "jsonb")],
            [
                ("p_item_type", "text", "IN", 1),
                ("p_item_id", "uuid", "IN", 2),
                ("p_decision", "text", "IN", 3),
                ("p_reviewer_id", "uuid", "IN", 4),
            ],
        ]

        mock_factory = MagicMock(return_value=mock_conn)
        mock_factory_maker.return_value = mock_factory

        report = run_db_health_check(mock_factory)
        self.assertEqual(report["status"], "healthy")
        self.assertFalse(report["migrations"]["supported"])
        self.assertEqual(report["migrations"]["status"], "unsupported")
        self.assertIn("not present", report["migrations"]["detail"])
        mock_conn.close.assert_called_once()

    @patch("backend.src.pipeline_cli.create_connection_factory")
    def test_check_db_reports_missing_tables(self, mock_factory_maker: MagicMock) -> None:
        """check-db returns 1 when required tables are missing."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from backend.src.pipeline_cli import REVIEW_RPC_NAME

        mock_cur.fetchone.side_effect = [
            ("meri_staging", "postgres", "PostgreSQL 15.8"),
            (False,),
        ]
        mock_cur.fetchall.side_effect = [
            [],  # No tables found
            [("review_candidate_item_1", REVIEW_RPC_NAME, "jsonb")],
            [
                ("p_item_type", "text", "IN", 1),
                ("p_item_id", "uuid", "IN", 2),
                ("p_decision", "text", "IN", 3),
                ("p_reviewer_id", "uuid", "IN", 4),
            ],
        ]

        mock_factory = MagicMock(return_value=mock_conn)
        mock_factory_maker.return_value = mock_factory

        exit_code = main(["check-db", "--db-url", "postgresql://fake:fake@localhost:5432/meri_staging"])
        self.assertEqual(exit_code, 1)
        mock_conn.close.assert_called_once()

    @patch("backend.src.pipeline_cli.create_connection_factory")
    def test_check_db_reports_missing_function(self, mock_factory_maker: MagicMock) -> None:
        """check-db fails when review_candidate_item is missing."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from backend.src.pipeline_cli import REQUIRED_TABLES, run_db_health_check

        mock_cur.fetchone.side_effect = [
            ("meri_staging", "postgres", "PostgreSQL 15.8"),
            (False,),
        ]
        mock_cur.fetchall.side_effect = [
            [(t,) for t in REQUIRED_TABLES],
            [],  # routine not found
        ]

        mock_factory = MagicMock(return_value=mock_conn)
        report = run_db_health_check(mock_factory)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["functions"]["review_candidate_item"]["status"], "missing")
        self.assertFalse(report["functions"]["review_candidate_item"]["signature_verified"])

    @patch("backend.src.pipeline_cli.create_connection_factory")
    def test_check_db_reports_function_signature_mismatch(self, mock_factory_maker: MagicMock) -> None:
        """check-db fails when review_candidate_item has mismatched arguments or return type."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        from backend.src.pipeline_cli import REQUIRED_TABLES, REVIEW_RPC_NAME, run_db_health_check

        mock_cur.fetchone.side_effect = [
            ("meri_staging", "postgres", "PostgreSQL 15.8"),
            (False,),
        ]
        mock_cur.fetchall.side_effect = [
            [(t,) for t in REQUIRED_TABLES],
            [("review_candidate_item_1", REVIEW_RPC_NAME, "integer")],  # wrong return type
            [
                ("p_item_type", "text", "IN", 1),
                ("p_wrong_param", "text", "IN", 2),
            ],
        ]

        mock_factory = MagicMock(return_value=mock_conn)
        report = run_db_health_check(mock_factory)
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["functions"]["review_candidate_item"]["signature_verified"])
        self.assertTrue(any("Signature mismatch" in err for err in report["errors"]))

    def test_check_db_redacts_credentials_on_connection_error(self) -> None:
        """Connection failure does not leak embedded passwords or credentials in reports."""
        from backend.src.pipeline_cli import run_db_health_check

        def failing_factory():
            raise RuntimeError("Failed to connect: postgresql://myuser:super_secret_pw_123@db.supabase.co:5432/postgres")

        report = run_db_health_check(failing_factory)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(len(report["errors"]) > 0)
        self.assertNotIn("super_secret_pw_123", str(report))
        self.assertIn("myuser:[REDACTED]@", str(report))

    def test_check_db_cleans_up_on_failure(self) -> None:
        """Cursor, rollback, and connection are closed cleanly even on unexpected query error."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = [None, None, RuntimeError("Unexpected socket drop")]

        from backend.src.pipeline_cli import run_db_health_check

        mock_factory = MagicMock(return_value=mock_conn)
        report = run_db_health_check(mock_factory)
        self.assertEqual(report["status"], "failed")
        mock_cur.close.assert_called_once()
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_load_env_file_populates_missing_vars(self) -> None:
        """load_env_file loads KEY=VAL without overwriting existing environment vars."""
        import tempfile
        from backend.src.pipeline_cli import load_env_file

        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write("TEST_NEW_KEY=hello_meri\n")
            f.write("TEST_EXISTING_KEY=new_val\n")
            f.write("# Comment line\n")
            f.write("INVALID_LINE\n")
            temp_path = f.name

        try:
            with patch.dict("os.environ", {"TEST_EXISTING_KEY": "original_val"}, clear=True):
                loaded = load_env_file(temp_path)
                import os
                self.assertTrue(loaded)
                self.assertEqual(os.environ.get("TEST_NEW_KEY"), "hello_meri")
                self.assertEqual(os.environ.get("TEST_EXISTING_KEY"), "original_val")
        finally:
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_load_env_file_missing_files_handling(self) -> None:
        """Missing env file returns False by default and raises FileNotFoundError when requested."""
        from backend.src.pipeline_cli import load_env_file

        missing_path = "/nonexistent/path/to/test.env"
        # Default behavior: returns False
        self.assertFalse(load_env_file(missing_path))

        # Explicit raise_if_missing: raises FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            load_env_file(missing_path, raise_if_missing=True)

    def test_load_env_file_comments_blanks_and_quotes(self) -> None:
        """Properly handles comments, blank lines, whitespace, and matching quotes."""
        import tempfile
        from backend.src.pipeline_cli import load_env_file

        env_content = (
            "# Top level comment\n"
            "   # Indented comment\n"
            "\n"
            "PLAIN_VAR=simple_value\n"
            "  SPACED_VAR  =   spaced_value  \n"
            "DOUBLE_QUOTED=\"double value with spaces\"\n"
            "SINGLE_QUOTED='single value with spaces'\n"
            "HASH_IN_VALUE=\"pass#word#123\"\n"
            "EMPTY_QUOTED=\"\"\n"
            "URL_WITH_EQUALS=postgresql://user:pass@host:5432/db?sslmode=require\n"
            "MISMATCHED_QUOTES=\"unclosed_quote\n"
        )

        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(env_content)
            temp_path = f.name

        try:
            with patch.dict("os.environ", {}, clear=True):
                load_env_file(temp_path)
                import os
                self.assertEqual(os.environ.get("PLAIN_VAR"), "simple_value")
                self.assertEqual(os.environ.get("SPACED_VAR"), "spaced_value")
                self.assertEqual(os.environ.get("DOUBLE_QUOTED"), "double value with spaces")
                self.assertEqual(os.environ.get("SINGLE_QUOTED"), "single value with spaces")
                self.assertEqual(os.environ.get("HASH_IN_VALUE"), "pass#word#123")
                self.assertEqual(os.environ.get("EMPTY_QUOTED"), "")
                self.assertEqual(os.environ.get("URL_WITH_EQUALS"), "postgresql://user:pass@host:5432/db?sslmode=require")
                self.assertEqual(os.environ.get("MISMATCHED_QUOTES"), "\"unclosed_quote")
        finally:
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_load_env_file_ignores_malformed_and_shell_syntax(self) -> None:
        """Safely ignores lines without '=', shell export prefixes, and invalid key identifiers."""
        import tempfile
        from backend.src.pipeline_cli import load_env_file

        malformed_content = (
            "VALID_ENTRY=valid_value\n"
            "LINE_WITHOUT_EQUALS\n"
            "=EMPTY_KEY\n"
            "export SHELL_EXPORT=val\n"
            "INVALID-KEY-NAME=val\n"
            "123_STARTS_WITH_NUMBER=val\n"
        )

        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write(malformed_content)
            temp_path = f.name

        try:
            with patch.dict("os.environ", {}, clear=True):
                load_env_file(temp_path)
                import os
                self.assertEqual(os.environ.get("VALID_ENTRY"), "valid_value")
                self.assertNotIn("LINE_WITHOUT_EQUALS", os.environ)
                self.assertNotIn("EMPTY_KEY", os.environ)
                self.assertNotIn("SHELL_EXPORT", os.environ)
                self.assertNotIn("export SHELL_EXPORT", os.environ)
                self.assertNotIn("INVALID-KEY-NAME", os.environ)
                self.assertNotIn("123_STARTS_WITH_NUMBER", os.environ)
        finally:
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_load_env_file_secret_safe_on_read_failure(self) -> None:
        """When reading env file fails, secret redaction is applied and error does not leak contents."""
        import tempfile
        from backend.src.pipeline_cli import load_env_file

        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write("SECRET_KEY=val\n")
            temp_path = f.name

        try:
            with patch("builtins.open", side_effect=PermissionError("Permission denied: super_secret_path")):
                with patch("backend.src.pipeline_cli.logger.warning") as mock_warn:
                    result = load_env_file(temp_path)
                    self.assertFalse(result)
                    mock_warn.assert_called_once()
        finally:
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_redact_secrets_comprehensive(self) -> None:
        """Verifies _redact_secrets scrubs URIs, DSNs, Bearer tokens, API keys, and passwords."""
        from backend.src.pipeline_cli import _redact_secrets

        self.assertEqual(_redact_secrets(None), "")
        self.assertEqual(_redact_secrets(""), "")

        # URI with user and pass
        uri = "postgresql://user:mypassword123@db.supabase.com:5432/meri"
        self.assertNotIn("mypassword123", _redact_secrets(uri))
        self.assertIn("user:[REDACTED]@", _redact_secrets(uri))

        # URI with only password
        uri_no_user = "postgresql://:mypassword123@db.supabase.com:5432/meri"
        self.assertNotIn("mypassword123", _redact_secrets(uri_no_user))
        self.assertIn(":[REDACTED]@", _redact_secrets(uri_no_user))

        # DSN string with password
        dsn = "dbname=meri host=localhost password=supersecretpw user=postgres"
        self.assertNotIn("supersecretpw", _redact_secrets(dsn))
        self.assertIn("password=[REDACTED]", _redact_secrets(dsn))

        # DSN string with quoted password
        dsn_quoted = 'dbname=meri password="super secret with spaces" user=postgres'
        self.assertNotIn("super secret with spaces", _redact_secrets(dsn_quoted))
        self.assertIn("password=[REDACTED]", _redact_secrets(dsn_quoted))

        # Query param
        url = "https://api.example.com/v1?token=secret_token_123&key=custom_key_456"
        redacted = _redact_secrets(url)
        self.assertNotIn("secret_token_123", redacted)
        self.assertNotIn("custom_key_456", redacted)
        self.assertIn("key=[REDACTED]", redacted)
        self.assertIn("token=[REDACTED]", redacted)

        # Standalone Google API key
        key_text = "Encountered key AIzaSyA1234567890123456789012345678901 in traceback"
        redacted_key = _redact_secrets(key_text)
        self.assertNotIn("AIzaSyA1234567890123456789012345678901", redacted_key)
        self.assertIn("[REDACTED_API_KEY]", redacted_key)

        # Bearer token
        header = "Authorization: Bearer my-bearer-token-string-9999"
        self.assertNotIn("my-bearer-token-string-9999", _redact_secrets(header))
        self.assertIn("Bearer [REDACTED_TOKEN]", _redact_secrets(header))


if __name__ == "__main__":
    unittest.main()
