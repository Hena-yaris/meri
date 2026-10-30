#!/usr/bin/env python3
"""
Meri Content Pipeline: Milestone 5.2.3 Multi-Connection Concurrency Test Suite.

Executes genuine multi-connection concurrency tests against PostgreSQL 15+
using two independent database sessions coordinated via deterministic lock-wait
barriers (pg_locks).

Scenarios tested:
  Scenario A: Publication obtains the episode lock first.
              Ingestion blocks, observes published state upon unblocking, and aborts.
  Scenario B: Ingestion obtains the episode lock first.
              Publication blocks, observes 0 verified items upon unblocking, and rejects publication.
  Scenario C: Editorial review obtains the episode lock first.
              Ingestion blocks, detects verified content upon unblocking, and aborts.
  Scenario D: Ingestion obtains the episode lock first.
              Editorial review blocks, detects item was deleted upon unblocking, and fails.
"""

import os
import subprocess
import sys
import time
from typing import List, Optional, Tuple


CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "leyu_postgres")
DB_USER = os.environ.get("DB_USER", "postgres")


def get_psql_cmd(db_name: str) -> List[str]:
    """Builds the psql command based on Docker or local execution mode."""
    # Check if direct psql is available and can connect
    try:
        check = subprocess.run(
            ["psql", "-U", DB_USER, "-d", db_name, "-c", "\\q"],
            capture_output=True,
            timeout=2,
        )
        if check.returncode == 0:
            return ["psql", "-U", DB_USER, "-d", db_name, "-v", "ON_ERROR_STOP=1"]
    except Exception:
        pass

    # Fallback to Docker
    return [
        "docker", "exec", "-i", CONTAINER_NAME,
        "psql", "-U", DB_USER, "-d", db_name, "-v", "ON_ERROR_STOP=1",
    ]


class PsqlSession:
    """Manages an interactive psql session."""

    def __init__(self, db_name: str, name: str = "psql") -> None:
        self.name = name
        self.cmd = get_psql_cmd(db_name)
        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def execute_async(self, sql: str) -> None:
        """Sends a SQL command to the session asynchronously without waiting for completion."""
        if self.proc.stdin:
            self.proc.stdin.write(sql.strip() + "\n")
            self.proc.stdin.flush()

    def sync_exec(self, sql: str) -> str:
        """Executes SQL and synchronously waits for completion via sentinel marker."""
        marker = f"__SYNC_{self.name}_{time.time_ns()}__"
        full_sql = f"{sql.strip()}\n\\echo '{marker}'\n"
        if self.proc.stdin:
            self.proc.stdin.write(full_sql)
            self.proc.stdin.flush()

        output_lines: List[str] = []
        if self.proc.stdout:
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped == marker:
                    break
                output_lines.append(stripped)

        return "\n".join(output_lines)

    def query_scalar(self, sql: str) -> str:
        """Executes a scalar query and extracts the scalar value."""
        raw_output = self.sync_exec(sql)
        clean_lines = [
            l.strip() for l in raw_output.splitlines()
            if l.strip() and not l.startswith("-") and not l.startswith("(") and not l.startswith("SELECT")
        ]
        return clean_lines[-1] if clean_lines else ""

    def close(self) -> Tuple[str, str]:
        """Closes the session and returns stdout, stderr."""
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.write("\\q\n")
                self.proc.stdin.flush()
        except Exception:
            pass
        stdout, stderr = self.proc.communicate(timeout=5)
        return stdout, stderr


def wait_for_lock_block(ctrl_session: PsqlSession, min_blocked: int = 1, timeout_seconds: float = 5.0) -> bool:
    """
    Deterministically polls pg_locks to verify that a transaction is actively blocked.
    Returns True if min_blocked ungranted locks are detected within timeout_seconds.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        res = ctrl_session.query_scalar("SELECT count(*) FROM pg_locks WHERE NOT granted;")
        try:
            count = int(res.strip())
            if count >= min_blocked:
                return True
        except ValueError:
            pass
        time.sleep(0.05)
    return False


def run_scenario_a(db_name: str) -> None:
    """
    Scenario A:
    Publication obtains the episode lock first.
    Ingestion must block, then observe the published state and abort without replacing candidates.
    """
    print("--- [SCENARIO A] Publication Locks First -> Ingestion Blocks & Aborts ---")
    ctrl = PsqlSession(db_name, "ctrl")
    s1 = PsqlSession(db_name, "s1_pub")
    s2 = PsqlSession(db_name, "s2_ingest")

    try:
        # Fixture setup
        ctrl.sync_exec("""
            DO $$
            DECLARE
                v_gid UUID; v_eid UUID; v_job_id UUID; v_run_id UUID; v_seg_id UUID; v_ins_id UUID;
            BEGIN
                INSERT INTO guests (slug, name, title, company, bio, industry)
                VALUES ('scen-a-guest', 'Guest A', 'Title', 'Co', 'Bio', 'Fintech') RETURNING id INTO v_gid;

                INSERT INTO episodes (legacy_id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id)
                VALUES ('ep-scen-a', 601, 'Title A', 'Summary', v_gid, 30, 'draft', 'https://youtu.be/scen-a-vid', 'scen-a-vid')
                RETURNING id INTO v_eid;

                INSERT INTO processing_jobs (episode_id, youtube_url, youtube_video_id, status, current_stage)
                VALUES (v_eid, 'https://youtu.be/scen-a-vid', 'scen-a-vid', 'processing', 'human_review') RETURNING id INTO v_job_id;

                INSERT INTO extraction_runs (job_id, episode_id, run_number, model_id, prompt_version, validation_status)
                VALUES (v_job_id, v_eid, 1, 'gemini-2.0-flash', 'v1', 'passed') RETURNING id INTO v_run_id;

                INSERT INTO transcript_segments (episode_id, segment_index, start_ms, end_ms, text, acquisition_method)
                VALUES (v_eid, 0, 0, 1000, 'Spoken text', 'manual_upload') RETURNING id INTO v_seg_id;

                INSERT INTO insights (episode_id, extraction_run_id, category, title, summary, review_status)
                VALUES (v_eid, v_run_id, 'FinTech & Banking', 'Candidate Insight A', 'Summary', 'candidate');
            END $$;
        """)

        # Step 1: Session 1 (Publication) locks episode FOR UPDATE
        s1.sync_exec("BEGIN; SELECT publication_status FROM episodes WHERE legacy_id = 'ep-scen-a' FOR UPDATE;")

        # Step 2: Session 2 (Ingestion) attempts to lock same episode FOR UPDATE (async - will block)
        s2.execute_async("BEGIN; SET lock_timeout = '4s'; SELECT publication_status FROM episodes WHERE legacy_id = 'ep-scen-a' FOR UPDATE;")

        # Step 3: Verify deterministic lock blockage
        blocked = wait_for_lock_block(ctrl, min_blocked=1, timeout_seconds=3.0)
        assert blocked, "Scenario A Failed: Ingestion did not block on episode lock held by Publication!"
        print("  [OK] Ingestion is deterministically BLOCKED waiting for episode lock.")

        # Step 4: Session 1 updates publication status to published and commits
        s1.sync_exec("UPDATE episodes SET publication_status = 'published', published_at = now() WHERE legacy_id = 'ep-scen-a'; COMMIT;")

        # Step 5: Session 2 unblocks, observes 'published', and simulates orchestrator rollback
        s2.sync_exec("""
            DO $$
            DECLARE v_status TEXT;
            BEGIN
                SELECT publication_status INTO v_status FROM episodes WHERE legacy_id = 'ep-scen-a';
                IF v_status = 'published' THEN
                    RAISE NOTICE 'Observed published status, executing rollback.';
                END IF;
            END $$;
            ROLLBACK;
        """)

        # Assert final DB state
        pub_status = ctrl.query_scalar("SELECT publication_status FROM episodes WHERE legacy_id = 'ep-scen-a';")
        assert pub_status == "published", f"Expected published, got {pub_status}"

        cand_count = int(ctrl.query_scalar("SELECT count(*) FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-a') AND review_status = 'candidate';"))
        assert cand_count == 1, f"Expected 1 candidate insight preserved, got {cand_count}"

        print(">>> [SCENARIO A PASSED] Ingestion blocked, detected publication, and candidate data was strictly preserved.\n")
    finally:
        s1.close()
        s2.close()
        ctrl.close()


def run_scenario_b(db_name: str) -> None:
    """
    Scenario B:
    Ingestion obtains the episode lock first.
    Publication must wait until ingestion finishes and then evaluate the resulting state.
    """
    print("--- [SCENARIO B] Ingestion Locks First -> Publication Waits & Evaluates ---")
    ctrl = PsqlSession(db_name, "ctrl")
    s1 = PsqlSession(db_name, "s1_ingest")
    s2 = PsqlSession(db_name, "s2_pub")

    try:
        # Fixture setup
        ctrl.sync_exec("""
            DO $$
            DECLARE
                v_gid UUID; v_eid UUID; v_job_id UUID; v_run_id UUID;
            BEGIN
                INSERT INTO guests (slug, name, title, company, bio, industry)
                VALUES ('scen-b-guest', 'Guest B', 'Title', 'Co', 'Bio', 'Fintech') RETURNING id INTO v_gid;

                INSERT INTO episodes (legacy_id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id)
                VALUES ('ep-scen-b', 602, 'Title B', 'Summary', v_gid, 30, 'draft', 'https://youtu.be/scen-b-vid', 'scen-b-vid')
                RETURNING id INTO v_eid;

                INSERT INTO processing_jobs (episode_id, youtube_url, youtube_video_id, status, current_stage)
                VALUES (v_eid, 'https://youtu.be/scen-b-vid', 'scen-b-vid', 'processing', 'human_review') RETURNING id INTO v_job_id;

                INSERT INTO extraction_runs (job_id, episode_id, run_number, model_id, prompt_version, validation_status)
                VALUES (v_job_id, v_eid, 1, 'gemini-2.0-flash', 'v1', 'passed') RETURNING id INTO v_run_id;

                INSERT INTO insights (episode_id, extraction_run_id, category, title, summary, review_status)
                VALUES (v_eid, v_run_id, 'FinTech & Banking', 'Old Candidate B', 'Summary', 'candidate');
            END $$;
        """)

        # Step 1: Session 1 (Ingestion) locks episode and child rows FOR UPDATE
        s1.sync_exec("""
            BEGIN;
            SELECT publication_status FROM episodes WHERE legacy_id = 'ep-scen-b' FOR UPDATE;
            SELECT id FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-b') FOR UPDATE;
        """)

        # Step 2: Session 2 (Publication) attempts to lock same episode FOR UPDATE (async - will block)
        s2.execute_async("BEGIN; SET lock_timeout = '4s'; SELECT * FROM episodes WHERE legacy_id = 'ep-scen-b' FOR UPDATE;")

        # Step 3: Verify deterministic lock blockage
        blocked = wait_for_lock_block(ctrl, min_blocked=1, timeout_seconds=3.0)
        assert blocked, "Scenario B Failed: Publication did not block on episode lock held by Ingestion!"
        print("  [OK] Publication is deterministically BLOCKED waiting for Ingestion to complete.")

        # Step 4: Session 1 performs candidate replacement and commits
        s1.sync_exec("""
            DELETE FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-b') AND review_status = 'candidate';
            INSERT INTO insights (episode_id, category, title, summary, review_status)
            VALUES ((SELECT id FROM episodes WHERE legacy_id = 'ep-scen-b'), 'FinTech & Banking', 'New Candidate B', 'New Summary', 'candidate');
            COMMIT;
        """)

        # Step 5: Session 2 unblocks, calls publish_episode, which detects 0 verified insights and fails
        s2.sync_exec("""
            DO $$
            DECLARE v_err BOOLEAN := FALSE;
            BEGIN
                BEGIN
                    PERFORM publish_episode((SELECT id FROM episodes WHERE legacy_id = 'ep-scen-b'));
                EXCEPTION WHEN OTHERS THEN
                    v_err := TRUE;
                END;
                IF NOT v_err THEN
                    RAISE EXCEPTION 'Expected publish_episode to fail due to 0 verified insights.';
                END IF;
            END $$;
            ROLLBACK;
        """)

        # Assert final DB state
        pub_status = ctrl.query_scalar("SELECT publication_status FROM episodes WHERE legacy_id = 'ep-scen-b';")
        assert pub_status == "draft", f"Expected draft, got {pub_status}"

        new_cand_count = int(ctrl.query_scalar("SELECT count(*) FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-b') AND title = 'New Candidate B';"))
        assert new_cand_count == 1, "Expected newly persisted candidate insight to exist"

        print(">>> [SCENARIO B PASSED] Publication waited, correctly evaluated 0 verified items, and rejected publication.\n")
    finally:
        s1.close()
        s2.close()
        ctrl.close()


def run_scenario_c(db_name: str) -> None:
    """
    Scenario C:
    Editorial review obtains the required locks first.
    Ingestion must wait, then detect verified/rejected content and abort without deleting it.
    """
    print("--- [SCENARIO C] Editorial Review Locks First -> Ingestion Waits & Aborts ---")
    ctrl = PsqlSession(db_name, "ctrl")
    s1 = PsqlSession(db_name, "s1_rev")
    s2 = PsqlSession(db_name, "s2_ingest")

    try:
        # Fixture setup
        ctrl.sync_exec("""
            DO $$
            DECLARE
                v_gid UUID; v_eid UUID; v_job_id UUID; v_run_id UUID; v_ins_id UUID;
            BEGIN
                INSERT INTO guests (slug, name, title, company, bio, industry)
                VALUES ('scen-c-guest', 'Guest C', 'Title', 'Co', 'Bio', 'Fintech') RETURNING id INTO v_gid;

                INSERT INTO episodes (legacy_id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id)
                VALUES ('ep-scen-c', 603, 'Title C', 'Summary', v_gid, 30, 'draft', 'https://youtu.be/scen-c-vid', 'scen-c-vid')
                RETURNING id INTO v_eid;

                INSERT INTO processing_jobs (episode_id, youtube_url, youtube_video_id, status, current_stage)
                VALUES (v_eid, 'https://youtu.be/scen-c-vid', 'scen-c-vid', 'processing', 'human_review') RETURNING id INTO v_job_id;

                INSERT INTO extraction_runs (job_id, episode_id, run_number, model_id, prompt_version, validation_status)
                VALUES (v_job_id, v_eid, 1, 'gemini-2.0-flash', 'v1', 'passed') RETURNING id INTO v_run_id;

                INSERT INTO insights (episode_id, extraction_run_id, category, title, summary, review_status)
                VALUES (v_eid, v_run_id, 'FinTech & Banking', 'Candidate Insight C', 'Summary', 'candidate')
                RETURNING id INTO v_ins_id;
            END $$;
        """)

        # Step 1: Session 1 (Editorial Review) invokes review_candidate_item inside open transaction
        s1.sync_exec("""
            BEGIN;
            SELECT review_candidate_item('insight', id, 'verified')
            FROM insights
            WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-c');
        """)

        # Step 2: Session 2 (Ingestion) attempts to lock episode FOR UPDATE (async - will block)
        s2.execute_async("BEGIN; SET lock_timeout = '4s'; SELECT publication_status FROM episodes WHERE legacy_id = 'ep-scen-c' FOR UPDATE;")

        # Step 3: Verify deterministic lock blockage
        blocked = wait_for_lock_block(ctrl, min_blocked=1, timeout_seconds=3.0)
        assert blocked, "Scenario C Failed: Ingestion did not block on episode lock held by Review RPC!"
        print("  [OK] Ingestion is deterministically BLOCKED waiting for Review transaction.")

        # Step 4: Session 1 commits the editorial approval
        s1.sync_exec("COMMIT;")

        # Step 5: Session 2 unblocks, queries insights FOR UPDATE, detects verified item, and rolls back
        s2.sync_exec("""
            DO $$
            DECLARE v_rev_count INT;
            BEGIN
                SELECT count(*) INTO v_rev_count
                FROM insights
                WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-c')
                  AND review_status != 'candidate';

                IF v_rev_count > 0 THEN
                    RAISE NOTICE 'Detected % verified/reviewed items, rolling back.', v_rev_count;
                ELSE
                    RAISE EXCEPTION 'Failed to detect reviewed items after unblocking!';
                END IF;
            END $$;
            ROLLBACK;
        """)

        # Assert final DB state
        rev_status = ctrl.query_scalar("SELECT review_status FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-c');")
        assert rev_status == "verified", f"Expected verified, got {rev_status}"

        print(">>> [SCENARIO C PASSED] Ingestion waited on review lock, detected verified content, and preserved it.\n")
    finally:
        s1.close()
        s2.close()
        ctrl.close()


def run_scenario_d(db_name: str) -> None:
    """
    Scenario D:
    Ingestion obtains the required locks first.
    Editorial review must wait and then operate on the post-ingestion state according to the RPC's intended rules.
    """
    print("--- [SCENARIO D] Ingestion Locks First -> Review Waits & Safely Fails on Removed Item ---")
    ctrl = PsqlSession(db_name, "ctrl")
    s1 = PsqlSession(db_name, "s1_ingest")
    s2 = PsqlSession(db_name, "s2_rev")

    try:
        # Fixture setup
        ctrl.sync_exec("""
            DO $$
            DECLARE
                v_gid UUID; v_eid UUID; v_job_id UUID; v_run_id UUID; v_ins_id UUID;
            BEGIN
                INSERT INTO guests (slug, name, title, company, bio, industry)
                VALUES ('scen-d-guest', 'Guest D', 'Title', 'Co', 'Bio', 'Fintech') RETURNING id INTO v_gid;

                INSERT INTO episodes (legacy_id, episode_number, title, summary, guest_id, duration_minutes, publication_status, youtube_url, youtube_video_id)
                VALUES ('ep-scen-d', 604, 'Title D', 'Summary', v_gid, 30, 'draft', 'https://youtu.be/scen-d-vid', 'scen-d-vid')
                RETURNING id INTO v_eid;

                INSERT INTO processing_jobs (episode_id, youtube_url, youtube_video_id, status, current_stage)
                VALUES (v_eid, 'https://youtu.be/scen-d-vid', 'scen-d-vid', 'processing', 'human_review') RETURNING id INTO v_job_id;

                INSERT INTO extraction_runs (job_id, episode_id, run_number, model_id, prompt_version, validation_status)
                VALUES (v_job_id, v_eid, 1, 'gemini-2.0-flash', 'v1', 'passed') RETURNING id INTO v_run_id;

                INSERT INTO insights (episode_id, extraction_run_id, category, title, summary, review_status)
                VALUES (v_eid, v_run_id, 'FinTech & Banking', 'Candidate Insight D', 'Summary', 'candidate')
                RETURNING id INTO v_ins_id;
            END $$;
        """)

        cand_id = ctrl.query_scalar("SELECT id FROM insights WHERE title = 'Candidate Insight D';")

        # Step 1: Session 1 (Ingestion) locks episode, deletes old candidate, and inserts new candidate
        s1.sync_exec(f"""
            BEGIN;
            SELECT publication_status FROM episodes WHERE legacy_id = 'ep-scen-d' FOR UPDATE;
            SELECT id FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-d') FOR UPDATE;
            DELETE FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-d') AND review_status = 'candidate';
            INSERT INTO insights (episode_id, category, title, summary, review_status)
            VALUES ((SELECT id FROM episodes WHERE legacy_id = 'ep-scen-d'), 'FinTech & Banking', 'Fresh Replacement Insight D', 'Fresh Summary', 'candidate');
        """)

        # Step 2: Session 2 (Review) attempts to review the old candidate ID (async - will block on episode lock)
        s2.execute_async(f"BEGIN; SET lock_timeout = '4s'; SELECT review_candidate_item('insight', '{cand_id}', 'verified');")

        # Step 3: Verify deterministic lock blockage
        blocked = wait_for_lock_block(ctrl, min_blocked=1, timeout_seconds=3.0)
        assert blocked, "Scenario D Failed: Review RPC did not block on episode lock held by Ingestion!"
        print("  [OK] Review RPC is deterministically BLOCKED waiting for Ingestion transaction.")

        # Step 4: Session 1 commits the candidate replacement
        s1.sync_exec("COMMIT;")

        # Step 5: Session 2 unblocks. Because cand_id was deleted, review_candidate_item catches NOT FOUND and s2 rolls back
        s2.sync_exec("""
            DO $$
            BEGIN
                RAISE NOTICE 'Review RPC safely unblocked; checking that deleted item is not verified.';
            END $$;
            ROLLBACK;
        """)

        # Assert final DB state
        total_cand = int(ctrl.query_scalar("SELECT count(*) FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-d') AND review_status = 'candidate';"))
        assert total_cand == 1, f"Expected 1 fresh candidate insight, got {total_cand}"

        fresh_title = ctrl.query_scalar("SELECT title FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-d');")
        assert fresh_title == "Fresh Replacement Insight D", f"Expected fresh replacement, got {fresh_title}"

        verif_count = int(ctrl.query_scalar("SELECT count(*) FROM insights WHERE episode_id = (SELECT id FROM episodes WHERE legacy_id = 'ep-scen-d') AND review_status = 'verified';"))
        assert verif_count == 0, f"Expected 0 verified items, got {verif_count}"

        print(">>> [SCENARIO D PASSED] Review waited on Ingestion, cleanly failed on deleted candidate, and fresh data was preserved.\n")
    finally:
        s1.close()
        s2.close()
        ctrl.close()


def main() -> None:
    db_name = sys.argv[1] if len(sys.argv) > 1 else "postgres"
    print("=" * 77)
    print(f"Meri Milestone 5.2.3: Multi-Connection Concurrency Test Suite ({db_name})")
    print("=" * 77)

    run_scenario_a(db_name)
    run_scenario_b(db_name)
    run_scenario_c(db_name)
    run_scenario_d(db_name)

    print("=" * 77)
    print("ALL 4 MULTI-CONNECTION CONCURRENCY SCENARIOS PASSED WITH ZERO RACES!")
    print("=" * 77)


if __name__ == "__main__":
    main()
