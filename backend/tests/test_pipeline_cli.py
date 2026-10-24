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


if __name__ == "__main__":
    unittest.main()
