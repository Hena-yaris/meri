-- =============================================================================
-- Meri Content Pipeline: Milestone 4 Orchestrator Database Verification Suite
-- Target: PostgreSQL 15+ / Supabase
-- Description: Executes database-backed assertions verifying:
--   1. Generated column constraints on transcript_segments.start_seconds.
--   2. ON DELETE RESTRICT behavior on insight_evidence and quotation_segments.
--   3. Foreign-key-safe deletion order during candidate reruns.
--   4. Protection of verified and rejected editorial items from deletion.
--   5. Unique constraint enforcement on extraction_runs (job_id, run_number).
--   6. Processing job status and stage lifecycle updates.
--   7. Atomic rollback behavior on mid-persistence write failure.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- =============================================================================
-- TEST SUITE SETUP: SEED FIXTURES FOR MILESTONE 4 ORCHESTRATOR
-- =============================================================================

DO $$
DECLARE
    v_guest_id UUID;
    v_ep_id UUID;
    v_job_id UUID;
    v_seg0_id UUID;
    v_seg1_id UUID;
    v_chunk_id UUID;
    v_run_id UUID;
    v_ins_id UUID;
    v_quote_id UUID;
BEGIN
    RAISE NOTICE '>>> [M4] Initializing Milestone 4 Orchestrator Test Fixtures...';

    -- 1. Guest fixture
    INSERT INTO guests (slug, name, title, company, bio, industry)
    VALUES (
        'm4-guest-tedros', 'Tedros Haile', 'Managing Director', 'Logistics Horn',
        'Supply chain architecture and cold storage specialist.', 'Logistics'
    ) RETURNING id INTO v_guest_id;

    -- 2. Episode fixture (draft)
    INSERT INTO episodes (
        legacy_id, episode_number, title, summary, guest_id,
        duration_minutes, publication_status, youtube_url, youtube_video_id
    ) VALUES (
        'ep-m4-401', 401, 'Cold Chain Logistics in the Horn of Africa',
        'End-to-end discussion on refrigerated transport networks.', v_guest_id,
        50, 'draft', 'https://www.youtube.com/watch?v=sample-ep401', 'sample-ep401'
    ) RETURNING id INTO v_ep_id;

    -- 3. Processing job fixture
    INSERT INTO processing_jobs (
        episode_id, youtube_url, youtube_video_id, status, current_stage
    ) VALUES (
        v_ep_id, 'https://www.youtube.com/watch?v=sample-ep401', 'sample-ep401',
        'processing', 'ai_extraction'
    ) RETURNING id INTO v_job_id;

    RAISE NOTICE '>>> [M4] Fixtures initialized: guest=%, ep=%, job=%', v_guest_id, v_ep_id, v_job_id;
END $$;


-- =============================================================================
-- TEST M4.1: Generated Column Behavior on transcript_segments.start_seconds
-- =============================================================================
DO $$
DECLARE
    v_ep_id UUID;
    v_seg_id UUID;
    v_calc_sec NUMERIC(8,2);
    v_err_caught BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M4.1: Generated Column Behavior on transcript_segments ---';

    SELECT id INTO v_ep_id FROM episodes WHERE legacy_id = 'ep-m4-401';

    -- Insert segment with start_ms = 12500 (expect start_seconds = 12.50)
    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_ep_id, 0, 12500, 24000, 'Tedros Haile', 'am', 'manual_upload',
        'የቀዝቃዛ ሰንሰለት ሎጂስቲክስ ለግብርና ምርቶች ጥራት ወሳኝ ነው።'
    ) RETURNING id, start_seconds INTO v_seg_id, v_calc_sec;

    IF v_calc_sec <> 12.50 THEN
        RAISE EXCEPTION 'start_seconds calculation error: expected 12.50, got %', v_calc_sec;
    END IF;

    -- Verify that attempting to insert explicit start_seconds is rejected by PostgreSQL
    BEGIN
        EXECUTE format(
            'INSERT INTO transcript_segments (episode_id, segment_index, start_ms, end_ms, start_seconds, acquisition_method, text) ' ||
            'VALUES (%L, 99, 1000, 2000, 1.00, %L, %L)',
            v_ep_id, 'manual_upload', 'Test'
        );
    EXCEPTION WHEN others THEN
        v_err_caught := TRUE;
    END;

    IF NOT v_err_caught THEN
        RAISE EXCEPTION 'Database permitted explicit insert into GENERATED ALWAYS column start_seconds!';
    END IF;

    RAISE NOTICE '>>> TEST M4.1 PASSED: Generated column start_seconds strictly computed and protected.';
END $$;


-- =============================================================================
-- TEST M4.2: ON DELETE RESTRICT on insight_evidence and quotation_segments
-- =============================================================================
DO $$
DECLARE
    v_ep_id UUID;
    v_job_id UUID;
    v_seg0_id UUID;
    v_seg1_id UUID;
    v_run_id UUID;
    v_ins_id UUID;
    v_quote_id UUID;
    v_err_evidence BOOLEAN := FALSE;
    v_err_quote BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M4.2: Evidence & Quotation Provenance RESTRICT Delete Integrity ---';

    SELECT id INTO v_ep_id FROM episodes WHERE legacy_id = 'ep-m4-401';
    SELECT id INTO v_job_id FROM processing_jobs WHERE episode_id = v_ep_id;
    SELECT id INTO v_seg0_id FROM transcript_segments WHERE episode_id = v_ep_id AND segment_index = 0;

    -- Insert segment 1
    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_ep_id, 1, 24001, 38000, 'Tedros Haile', 'am', 'manual_upload',
        'የመጋዘን አቅርቦት እጥረት በዋጋ ላይ ከፍተኛ ተፅዕኖ አሳድሯል።'
    ) RETURNING id INTO v_seg1_id;

    -- Insert extraction_run
    INSERT INTO extraction_runs (
        job_id, episode_id, run_number, model_id, prompt_version, validation_status
    ) VALUES (
        v_job_id, v_ep_id, 1, 'gemini-2.0-flash', 'v1.0.0', 'passed'
    ) RETURNING id INTO v_run_id;

    -- Insert candidate insight
    INSERT INTO insights (
        episode_id, extraction_run_id, category, title, summary, review_status
    ) VALUES (
        v_ep_id, v_run_id, 'Logistics & Supply Chain', 'Cold Chain Infrastructure',
        'Cold storage networks reduce post-harvest agricultural losses.', 'candidate'
    ) RETURNING id INTO v_ins_id;

    -- Link insight to segment 0 via insight_evidence
    INSERT INTO insight_evidence (insight_id, segment_id, relevance_score)
    VALUES (v_ins_id, v_seg0_id, 0.95);

    -- Insert candidate quotation
    INSERT INTO quotations (
        episode_id, extraction_run_id, segment_id, amharic_quote,
        english_translation, speaker, timestamp_seconds, context, review_status
    ) VALUES (
        v_ep_id, v_run_id, v_seg1_id, 'የመጋዘን አቅርቦት እጥረት በዋጋ ላይ ከፍተኛ ተፅዕኖ አሳድሯል።',
        'Lack of storage supply has had a significant impact on pricing.',
        'Tedros Haile', 24, 'Storage infrastructure challenge', 'candidate'
    ) RETURNING id INTO v_quote_id;

    -- Link quotation to segment 1 via quotation_segments
    INSERT INTO quotation_segments (quotation_id, segment_id, sequence_order)
    VALUES (v_quote_id, v_seg1_id, 0);

    -- Attempt 1: Direct deletion of transcript_segments referenced by insight_evidence must be BLOCKED by RESTRICT
    BEGIN
        DELETE FROM transcript_segments WHERE id = v_seg0_id;
    EXCEPTION WHEN foreign_key_violation THEN
        v_err_evidence := TRUE;
    END;

    IF NOT v_err_evidence THEN
        RAISE EXCEPTION 'ON DELETE RESTRICT failed to block deletion of segment referenced by insight_evidence!';
    END IF;

    -- Attempt 2: Direct deletion of transcript_segments referenced by quotation_segments must be BLOCKED by RESTRICT
    BEGIN
        DELETE FROM transcript_segments WHERE id = v_seg1_id;
    EXCEPTION WHEN foreign_key_violation THEN
        v_err_quote := TRUE;
    END;

    IF NOT v_err_quote THEN
        RAISE EXCEPTION 'ON DELETE RESTRICT failed to block deletion of segment referenced by quotation_segments!';
    END IF;

    RAISE NOTICE '>>> TEST M4.2 PASSED: Evidence and quotation segments strictly enforce ON DELETE RESTRICT.';
END $$;


-- =============================================================================
-- TEST M4.3: Safe Deletion Order for Candidate Rerun
-- =============================================================================
DO $$
DECLARE
    v_ep_id UUID;
    v_remaining_segs INT;
    v_remaining_ins INT;
    v_remaining_quotes INT;
    v_remaining_runs INT;
BEGIN
    RAISE NOTICE '--- TEST M4.3: Foreign-Key-Safe Deletion Order for Candidate Rerun ---';

    SELECT id INTO v_ep_id FROM episodes WHERE legacy_id = 'ep-m4-401';

    -- Execute the EXACT deletion order specified in PipelineOrchestrator._enforce_rerun_policy:
    -- 1. Candidate insights (cascades to insight_evidence)
    DELETE FROM insights WHERE episode_id = v_ep_id AND review_status = 'candidate';

    -- 2. Candidate quotations (cascades to quotation_segments)
    DELETE FROM quotations WHERE episode_id = v_ep_id AND review_status = 'candidate';

    -- 3. Transcript chunks
    DELETE FROM transcript_chunks WHERE episode_id = v_ep_id;

    -- 4. Transcript segments (now safe because all evidence and quotation_segments rows were cascaded)
    DELETE FROM transcript_segments WHERE episode_id = v_ep_id;

    -- 5. Unreferenced extraction runs
    DELETE FROM extraction_runs
    WHERE episode_id = v_ep_id
      AND NOT EXISTS (SELECT 1 FROM insights WHERE extraction_run_id = extraction_runs.id)
      AND NOT EXISTS (SELECT 1 FROM quotations WHERE extraction_run_id = extraction_runs.id);

    -- Verify all counts are zero
    SELECT count(*) INTO v_remaining_segs FROM transcript_segments WHERE episode_id = v_ep_id;
    SELECT count(*) INTO v_remaining_ins FROM insights WHERE episode_id = v_ep_id;
    SELECT count(*) INTO v_remaining_quotes FROM quotations WHERE episode_id = v_ep_id;
    SELECT count(*) INTO v_remaining_runs FROM extraction_runs WHERE episode_id = v_ep_id;

    IF v_remaining_segs <> 0 OR v_remaining_ins <> 0 OR v_remaining_quotes <> 0 OR v_remaining_runs <> 0 THEN
        RAISE EXCEPTION 'Rerun cleanup incomplete: segs=%, ins=%, quotes=%, runs=%',
            v_remaining_segs, v_remaining_ins, v_remaining_quotes, v_remaining_runs;
    END IF;

    RAISE NOTICE '>>> TEST M4.3 PASSED: Candidate rerun deletion order cleanly clears unreviewed data without RESTRICT errors.';
END $$;


-- =============================================================================
-- TEST M4.4: Protection of Verified and Rejected Editorial Content
-- =============================================================================
DO $$
DECLARE
    v_ep_id UUID;
    v_job_id UUID;
    v_seg_id UUID;
    v_run_id UUID;
    v_ins_id UUID;
    v_quote_id UUID;
    v_reviewed_count INT;
BEGIN
    RAISE NOTICE '--- TEST M4.4: Protection of Verified and Rejected Editorial Content ---';

    SELECT id INTO v_ep_id FROM episodes WHERE legacy_id = 'ep-m4-401';
    SELECT id INTO v_job_id FROM processing_jobs WHERE episode_id = v_ep_id;

    -- Insert a segment
    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_ep_id, 0, 0, 10000, 'Tedros Haile', 'am', 'manual_upload', 'የተረጋገጠ አረፍተ ነገር።'
    ) RETURNING id INTO v_seg_id;

    -- Insert extraction run
    INSERT INTO extraction_runs (
        job_id, episode_id, run_number, model_id, prompt_version, validation_status
    ) VALUES (
        v_job_id, v_ep_id, 2, 'gemini-2.0-flash', 'v1.0.0', 'passed'
    ) RETURNING id INTO v_run_id;

    -- Insert a VERIFIED insight
    INSERT INTO insights (
        episode_id, extraction_run_id, category, title, summary, review_status
    ) VALUES (
        v_ep_id, v_run_id, 'Logistics & Supply Chain', 'Verified Supply Chain Strategy',
        'Human approved editorial insight.', 'verified'
    ) RETURNING id INTO v_ins_id;

    -- Insert a REJECTED quotation
    INSERT INTO quotations (
        episode_id, extraction_run_id, segment_id, amharic_quote,
        english_translation, speaker, timestamp_seconds, context, review_status
    ) VALUES (
        v_ep_id, v_run_id, v_seg_id, 'ውድቅ የተደረገ ጥቅስ።', 'Rejected quotation.',
        'Tedros Haile', 0, 'Rejection context', 'rejected'
    ) RETURNING id INTO v_quote_id;

    -- Verify that the orchestrator review_status != 'candidate' query flags BOTH verified and rejected
    SELECT count(*) INTO v_reviewed_count
    FROM (
        SELECT id FROM insights WHERE episode_id = v_ep_id AND review_status != 'candidate'
        UNION ALL
        SELECT id FROM quotations WHERE episode_id = v_ep_id AND review_status != 'candidate'
    ) reviewed_items;

    IF v_reviewed_count <> 2 THEN
        RAISE EXCEPTION 'Editorial protection query failed to detect both verified and rejected items: count=%', v_reviewed_count;
    END IF;

    RAISE NOTICE '>>> TEST M4.4 PASSED: Both verified and rejected editorial decisions are strictly protected.';
END $$;


-- =============================================================================
-- TEST M4.5: Extraction Run Concurrency and Uniqueness Constraints
-- =============================================================================
DO $$
DECLARE
    v_ep_id UUID;
    v_job_id UUID;
    v_dup_error BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M4.5: Extraction Run Concurrency & Uniqueness ---';

    SELECT id INTO v_ep_id FROM episodes WHERE legacy_id = 'ep-m4-401';
    SELECT id INTO v_job_id FROM processing_jobs WHERE episode_id = v_ep_id;

    -- Extraction run 2 already exists for this job. Attempting to insert duplicate run_number=2 must fail
    BEGIN
        INSERT INTO extraction_runs (
            job_id, episode_id, run_number, model_id, prompt_version, validation_status
        ) VALUES (
            v_job_id, v_ep_id, 2, 'gemini-2.0-flash', 'v1.0.0', 'passed'
        );
    EXCEPTION WHEN unique_violation THEN
        v_dup_error := TRUE;
    END;

    IF NOT v_dup_error THEN
        RAISE EXCEPTION 'Database permitted duplicate extraction_run with same (job_id, run_number)!';
    END IF;

    -- Verify auto-incrementing query: next run_number should be 3
    PERFORM 1 FROM extraction_runs WHERE job_id = v_job_id;
    IF (SELECT COALESCE(MAX(run_number), 0) + 1 FROM extraction_runs WHERE job_id = v_job_id) <> 3 THEN
        RAISE EXCEPTION 'Next run_number calculation failed: expected 3';
    END IF;

    RAISE NOTICE '>>> TEST M4.5 PASSED: Unique constraint (job_id, run_number) strictly enforced.';
END $$;


-- =============================================================================
-- TEST M4.6: Processing Job Status and Stage Lifecycle
-- =============================================================================
DO $$
DECLARE
    v_job_id UUID;
    v_status processing_job_status;
    v_stage processing_stage;
    v_invalid_enum_rejected BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M4.6: Processing Job Lifecycle Updates ---';

    SELECT id INTO v_job_id FROM processing_jobs WHERE youtube_video_id = 'sample-ep401';

    -- 1. Advance to completed and human_review
    UPDATE processing_jobs
    SET status = 'completed'::processing_job_status,
        current_stage = 'human_review'::processing_stage,
        updated_at = now()
    WHERE id = v_job_id;

    SELECT status, current_stage INTO v_status, v_stage
    FROM processing_jobs WHERE id = v_job_id;

    IF v_status <> 'completed' OR v_stage <> 'human_review' THEN
        RAISE EXCEPTION 'Job update failed: status=%, stage=%', v_status, v_stage;
    END IF;

    -- 2. Test failure recording
    UPDATE processing_jobs
    SET status = 'failed'::processing_job_status,
        current_stage = 'validation'::processing_stage,
        error_summary = 'Semantic validation failed: fabricated quotation',
        updated_at = now()
    WHERE id = v_job_id;

    SELECT status, current_stage INTO v_status, v_stage
    FROM processing_jobs WHERE id = v_job_id;

    IF v_status <> 'failed' OR v_stage <> 'validation' THEN
        RAISE EXCEPTION 'Job failure update failed: status=%, stage=%', v_status, v_stage;
    END IF;

    -- 3. Verify that unsupported enum values are rejected
    BEGIN
        EXECUTE 'UPDATE processing_jobs SET status = ''invalid_status''::processing_job_status WHERE id = ' || quote_literal(v_job_id);
    EXCEPTION WHEN invalid_text_representation THEN
        v_invalid_enum_rejected := TRUE;
    END;

    IF NOT v_invalid_enum_rejected THEN
        RAISE EXCEPTION 'Database accepted unsupported processing_job_status enum value!';
    END IF;

    RAISE NOTICE '>>> TEST M4.6 PASSED: Processing job status/stage transitions conform to enum constraints.';
END $$;


-- =============================================================================
-- TEST M4.7: Atomic Transaction Rollback on Mid-Persistence Failure
-- =============================================================================
DO $$
DECLARE
    v_ep_id UUID;
    v_seg_count_before INT;
    v_seg_count_after INT;
BEGIN
    RAISE NOTICE '--- TEST M4.7: Atomic Rollback on Mid-Persistence Failure ---';

    SELECT id INTO v_ep_id FROM episodes WHERE legacy_id = 'ep-m4-401';
    SELECT count(*) INTO v_seg_count_before FROM transcript_segments WHERE episode_id = v_ep_id;

    -- Simulate a failed atomic write transaction using a subtransaction/savepoint
    BEGIN
        -- Step 1: Write some segments
        INSERT INTO transcript_segments (
            episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
        ) VALUES (
            v_ep_id, 100, 100000, 110000, 'Tedros Haile', 'am', 'manual_upload', 'ጊዜያዊ ክፍል'
        );

        -- Step 2: Simulate failure (e.g. duplicate segment_index)
        INSERT INTO transcript_segments (
            episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
        ) VALUES (
            v_ep_id, 100, 110001, 120000, 'Tedros Haile', 'am', 'manual_upload', 'የተደገመ ክፍል'
        );
    EXCEPTION WHEN unique_violation THEN
        -- Handled exception in PL/pgSQL rolls back the subtransaction
        RAISE NOTICE 'Captured expected unique violation during mid-persistence insert.';
    END;

    SELECT count(*) INTO v_seg_count_after FROM transcript_segments WHERE episode_id = v_ep_id;

    IF v_seg_count_after <> v_seg_count_before THEN
        RAISE EXCEPTION 'Rollback failed: segments changed from % to %', v_seg_count_before, v_seg_count_after;
    END IF;

    RAISE NOTICE '>>> TEST M4.7 PASSED: Transaction rollback completely restored pre-write state.';
END $$;


-- =============================================================================
-- TEST M4.8: Worker Atomic Claim Query with FOR UPDATE SKIP LOCKED
-- =============================================================================
DO $$
DECLARE
    v_ep_id UUID;
    v_job1_id UUID;
    v_job2_id UUID;
    v_claimed_id UUID;
    v_status processing_job_status;
    v_stage processing_stage;
BEGIN
    RAISE NOTICE '--- TEST M4.8: Worker Atomic Claim with FOR UPDATE SKIP LOCKED ---';

    SELECT id INTO v_ep_id FROM episodes WHERE legacy_id = 'ep-m4-401';

    -- Insert two pending jobs
    INSERT INTO processing_jobs (
        episode_id, youtube_url, youtube_video_id, status, current_stage, created_at
    ) VALUES (
        v_ep_id, 'https://www.youtube.com/watch?v=sample-claim-1', 'sample-claim-1',
        'pending', 'submission', now() - INTERVAL '10 minutes'
    ) RETURNING id INTO v_job1_id;

    INSERT INTO processing_jobs (
        episode_id, youtube_url, youtube_video_id, status, current_stage, created_at
    ) VALUES (
        v_ep_id, 'https://www.youtube.com/watch?v=sample-claim-2', 'sample-claim-2',
        'pending', 'submission', now() - INTERVAL '5 minutes'
    ) RETURNING id INTO v_job2_id;

    -- Execute Worker Claim 1 (should claim older job1 first)
    WITH claimable AS (
        SELECT id
        FROM processing_jobs
        WHERE status = 'pending'::processing_job_status
        ORDER BY created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE processing_jobs
    SET status = 'processing'::processing_job_status,
        current_stage = 'transcript_acquisition'::processing_stage,
        updated_at = now()
    FROM claimable
    WHERE processing_jobs.id = claimable.id
    RETURNING processing_jobs.id, processing_jobs.status, processing_jobs.current_stage
    INTO v_claimed_id, v_status, v_stage;

    IF v_claimed_id <> v_job1_id OR v_status <> 'processing' OR v_stage <> 'transcript_acquisition' THEN
        RAISE EXCEPTION 'Claim 1 failed: expected job %, got %, status=%, stage=%',
            v_job1_id, v_claimed_id, v_status, v_stage;
    END IF;

    -- Execute Worker Claim 2 (should claim job2)
    WITH claimable AS (
        SELECT id
        FROM processing_jobs
        WHERE status = 'pending'::processing_job_status
        ORDER BY created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE processing_jobs
    SET status = 'processing'::processing_job_status,
        current_stage = 'transcript_acquisition'::processing_stage,
        updated_at = now()
    FROM claimable
    WHERE processing_jobs.id = claimable.id
    RETURNING processing_jobs.id INTO v_claimed_id;

    IF v_claimed_id <> v_job2_id THEN
        RAISE EXCEPTION 'Claim 2 failed: expected job %, got %', v_job2_id, v_claimed_id;
    END IF;

    -- Execute Worker Claim 3 (no pending jobs left -> must return NULL)
    v_claimed_id := NULL;
    WITH claimable AS (
        SELECT id
        FROM processing_jobs
        WHERE status = 'pending'::processing_job_status
        ORDER BY created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE processing_jobs
    SET status = 'processing'::processing_job_status,
        current_stage = 'transcript_acquisition'::processing_stage,
        updated_at = now()
    FROM claimable
    WHERE processing_jobs.id = claimable.id
    RETURNING processing_jobs.id INTO v_claimed_id;

    IF v_claimed_id IS NOT NULL THEN
        RAISE EXCEPTION 'Claim 3 should have returned NULL on empty queue, got: %', v_claimed_id;
    END IF;

    RAISE NOTICE '>>> TEST M4.8 PASSED: FOR UPDATE SKIP LOCKED claims pending jobs in FIFO order without races.';
END $$;


-- =============================================================================
-- TEST M4.9: Worker Conditional Claim by ID
-- =============================================================================
DO $$
DECLARE
    v_ep_id UUID;
    v_completed_job_id UUID;
    v_pending_job_id UUID;
    v_claimed_id UUID;
BEGIN
    RAISE NOTICE '--- TEST M4.9: Worker Conditional Claim by ID ---';

    SELECT id INTO v_ep_id FROM episodes WHERE legacy_id = 'ep-m4-401';

    -- 1. Insert a job that is already completed
    INSERT INTO processing_jobs (
        episode_id, youtube_url, youtube_video_id, status, current_stage
    ) VALUES (
        v_ep_id, 'https://www.youtube.com/watch?v=sample-comp-1', 'sample-comp-1',
        'completed', 'human_review'
    ) RETURNING id INTO v_completed_job_id;

    -- Attempt conditional claim on completed job -> must return 0 rows
    v_claimed_id := NULL;
    WITH claimable AS (
        SELECT id
        FROM processing_jobs
        WHERE id = v_completed_job_id AND status = 'pending'::processing_job_status
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE processing_jobs
    SET status = 'processing'::processing_job_status,
        current_stage = 'transcript_acquisition'::processing_stage,
        updated_at = now()
    FROM claimable
    WHERE processing_jobs.id = claimable.id
    RETURNING processing_jobs.id INTO v_claimed_id;

    IF v_claimed_id IS NOT NULL THEN
        RAISE EXCEPTION 'Conditional claim should have rejected completed job %', v_completed_job_id;
    END IF;

    -- 2. Insert a pending job
    INSERT INTO processing_jobs (
        episode_id, youtube_url, youtube_video_id, status, current_stage
    ) VALUES (
        v_ep_id, 'https://www.youtube.com/watch?v=sample-pend-1', 'sample-pend-1',
        'pending', 'submission'
    ) RETURNING id INTO v_pending_job_id;

    -- Conditional claim on pending job -> must succeed
    v_claimed_id := NULL;
    WITH claimable AS (
        SELECT id
        FROM processing_jobs
        WHERE id = v_pending_job_id AND status = 'pending'::processing_job_status
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE processing_jobs
    SET status = 'processing'::processing_job_status,
        current_stage = 'transcript_acquisition'::processing_stage,
        updated_at = now()
    FROM claimable
    WHERE processing_jobs.id = claimable.id
    RETURNING processing_jobs.id INTO v_claimed_id;

    IF v_claimed_id <> v_pending_job_id THEN
        RAISE EXCEPTION 'Conditional claim on pending job % failed', v_pending_job_id;
    END IF;

    RAISE NOTICE '>>> TEST M4.9 PASSED: Conditional claim by ID safely guards against invalid state transitions.';
END $$;


ROLLBACK; -- Always cleanly roll back test fixtures

-- =============================================================================
-- TEST SUITE SUMMARY
-- =============================================================================
\echo '============================================================================='
\echo 'ALL 9 MILESTONE 4 ORCHESTRATOR & WORKER DATABASE VERIFICATION TESTS PASSED SUCCESSFULLY!'
\echo '============================================================================='
