"""
Schema contract assertions: verifies that Python model outputs strictly match
the PostgreSQL column names, types, and constraints declared in
supabase/migrations/20261020000001_content_pipeline_foundation.sql.
"""

from pathlib import Path
import unittest

from backend.src.chunker import TranscriptChunker
from backend.src.models import (
    NormalizedSegment,
    TranscriptAcquisitionMethod,
    TranscriptChunk,
)
from backend.src.transcript_normalizer import TranscriptNormalizer
from backend.src.transcript_parser import parse_json_transcript

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "supabase"
    / "migrations"
    / "20261020000001_content_pipeline_foundation.sql"
)


class TestSchemaContracts(unittest.TestCase):
    """Verifies strict parity between backend models and Supabase PostgreSQL schema."""

    def setUp(self) -> None:
        self.migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
        json_path = FIXTURES_DIR / "sample_transcript.json"
        raw_cues = parse_json_transcript(json_path.read_text(encoding="utf-8"))
        self.segments = TranscriptNormalizer(
            acquisition_method=TranscriptAcquisitionMethod.MANUAL_UPLOAD
        ).normalize(raw_cues)
        self.chunks = TranscriptChunker().chunk(self.segments)

    def test_transcript_segments_column_parity(self) -> None:
        """
        Ensures NormalizedSegment.to_db_dict() produces:
        1. An INSERT-safe dictionary (default) omitting PostgreSQL generated column start_seconds.
        2. A read/verification dictionary (include_generated=True) containing start_seconds.
        """
        sample_episode_id = "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a"
        seg = self.segments[0]

        # 1. Default / INSERT contract: must NOT contain generated column 'start_seconds'
        insert_dict = seg.to_db_dict(episode_id=sample_episode_id)
        self.assertNotIn(
            "start_seconds",
            insert_dict,
            "INSERT payload must not include generated column 'start_seconds' (violates PostgreSQL GENERATED ALWAYS)",
        )
        self.assertNotIn("start_seconds", seg.to_insert_dict(episode_id=sample_episode_id))

        expected_insert_columns = {
            "episode_id": str,
            "segment_index": int,
            "start_ms": int,
            "end_ms": int,
            "speaker_label": str,
            "language_code": str,
            "acquisition_method": str,
            "text": str,
        }

        for col, col_type in expected_insert_columns.items():
            self.assertIn(col, insert_dict, f"Missing required column '{col}' in segment dict")
            self.assertIsInstance(
                insert_dict[col],
                col_type,
                f"Column '{col}' must be {col_type}, got {type(insert_dict[col])}",
            )

        # 2. Read / verification contract: contains start_seconds
        read_dict = seg.to_db_dict(episode_id=sample_episode_id, include_generated=True)
        self.assertIn("start_seconds", read_dict)
        self.assertIsInstance(read_dict["start_seconds"], float)
        self.assertAlmostEqual(
            read_dict["start_seconds"], round(read_dict["start_ms"] / 1000.0, 2), places=2
        )

        # Confidence is optional float or None
        if insert_dict.get("confidence") is not None:
            self.assertIsInstance(insert_dict["confidence"], float)

        # Check DB constraints
        self.assertGreaterEqual(insert_dict["segment_index"], 0)
        self.assertGreaterEqual(insert_dict["start_ms"], 0)
        self.assertGreaterEqual(insert_dict["end_ms"], insert_dict["start_ms"])

    def test_transcript_chunks_column_parity(self) -> None:
        """
        Ensures TranscriptChunk.to_db_dict() contains exact column names
        and types matching table: transcript_chunks.
        """
        sample_episode_id = "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a"
        chunk_dict = self.chunks[0].to_db_dict(episode_id=sample_episode_id)

        expected_columns = {
            "episode_id": str,
            "chunk_index": int,
            "start_segment_index": int,
            "end_segment_index": int,
            "start_ms": int,
            "end_ms": int,
            "token_count_estimate": int,
            "chunk_text": str,
        }

        for col, col_type in expected_columns.items():
            self.assertIn(col, chunk_dict, f"Missing required column '{col}' in chunk dict")
            self.assertIsInstance(
                chunk_dict[col],
                col_type,
                f"Column '{col}' must be {col_type}, got {type(chunk_dict[col])}",
            )

        # Check DB constraints
        self.assertGreaterEqual(chunk_dict["chunk_index"], 0)
        self.assertGreaterEqual(chunk_dict["start_segment_index"], 0)
        self.assertGreaterEqual(
            chunk_dict["end_segment_index"], chunk_dict["start_segment_index"]
        )
        self.assertGreaterEqual(chunk_dict["start_ms"], 0)
        self.assertGreaterEqual(chunk_dict["end_ms"], chunk_dict["start_ms"])
        self.assertGreater(chunk_dict["token_count_estimate"], 0)

    def test_acquisition_method_enum_values_match_postgresql_migration(self) -> None:
        """
        Verifies that every enum value in TranscriptAcquisitionMethod exists
        in the PostgreSQL migration CREATE TYPE transcript_acquisition_method.
        """
        for method in TranscriptAcquisitionMethod:
            self.assertIn(
                f"'{method.value}'",
                self.migration_sql,
                f"Enum value '{method.value}' not found in Supabase migration",
            )


if __name__ == "__main__":
    unittest.main()
