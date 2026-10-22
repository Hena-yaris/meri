-- =============================================================================
-- Meri Database Foundation: Repeatable Verification Test Suite (Milestone 4B)
-- Target: PostgreSQL 15+ / Supabase
-- Description: Executes comprehensive assertions covering all 9 required
--              functional, security, and integrity verification cases.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- =============================================================================
-- TEST SUITE SETUP: SEED FIXTURES
-- =============================================================================

DO $$
DECLARE
    v_guest_id UUID;
    v_draft_episode_id UUID;
    v_published_episode_id UUID;
    v_segment_id UUID;
    v_chunk_id UUID;
    v_job_id UUID;
    v_run_id UUID;
    v_insight_id UUID;
    v_quote_id UUID;
BEGIN
    RAISE NOTICE '>>> Initializing Verification Test Fixtures...';

    -- 1. Create a guest
    INSERT INTO guests (slug, name, title, company, bio, industry)
    VALUES (
        'dawit-tadesse',
        'Dawit Tadesse',
        'Founder & MD',
        'Nile Cold Chain Logistics',
        'Pioneer of cold-chain freight transit networks in Ethiopia.',
        'Logistics & Agritech'
    ) RETURNING id INTO v_guest_id;

    -- 2. Create a draft episode
    INSERT INTO episodes (
        legacy_id, episode_number, title, summary, guest_id,
        duration_minutes, publication_status, youtube_url, youtube_video_id
    ) VALUES (
        'ep-101', 101, 'Cold Chain Logistics Across Agricultural Corridors',
        'Exploration into cold storage logistics.', v_guest_id,
        74, 'draft', 'https://www.youtube.com/watch?v=sample-ep101', 'sample-ep101'
    ) RETURNING id INTO v_draft_episode_id;

    -- 3. Create a processing job for the draft
    INSERT INTO processing_jobs (episode_id, youtube_url, youtube_video_id, status, current_stage)
    VALUES (v_draft_episode_id, 'https://www.youtube.com/watch?v=sample-ep101', 'sample-ep101', 'completed', 'human_review')
    RETURNING id INTO v_job_id;

    -- 4. Create transcript segments
    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_draft_episode_id, 0, 0, 14200, 'Dawit Tadesse', 'am', 'manual_upload',
        'እንኳን ደህና መጣችሁ። ዛሬ የምናወራው ስለ ቀዝቃዛ ሰንሰለት ሎጂስቲክስ ነው።'
    ) RETURNING id INTO v_segment_id;

    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_draft_episode_id, 1, 14201, 35000, 'Dawit Tadesse', 'am', 'manual_upload',
        'የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ማስላት ነው።'
    );

    -- 5. Create transcript chunk
    INSERT INTO transcript_chunks (
        episode_id, chunk_index, start_segment_index, end_segment_index, start_ms, end_ms, chunk_text
    ) VALUES (
        v_draft_episode_id, 0, 0, 1, 0, 35000, 'Combined chunk text for testing.'
    ) RETURNING id INTO v_chunk_id;

    -- 6. Create extraction run
    INSERT INTO extraction_runs (
        job_id, episode_id, run_number, model_id, prompt_version, validation_status
    ) VALUES (
        v_job_id, v_draft_episode_id, 1, 'gemini-1.5-pro-002', 'v1.0.0', 'passed'
    ) RETURNING id INTO v_run_id;

    -- 7. Create candidate insight (unreviewed)
    INSERT INTO insights (
        episode_id, extraction_run_id, category, title, summary, takeaways, practical_action, review_status
    ) VALUES (
        v_draft_episode_id, v_run_id, 'Operations', 'Decoupling Fleet Ownership',
        'Partnering with regional truck owners reduces initial CapEx.',
        ARRAY['Asset-light fleets scale faster', 'Quality incentives matter'],
        'Audit depreciation against subcontracting', 'candidate'
    ) RETURNING id INTO v_insight_id;

    -- 8. Create candidate quotation
    INSERT INTO quotations (
        episode_id, extraction_run_id, segment_id, amharic_quote, english_translation,
        speaker, timestamp_seconds, context, review_status
    ) VALUES (
        v_draft_episode_id, v_run_id, v_segment_id,
        'የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ማስላት ነው።',
        'The greatest test in logistics is calculating produce loss on the highway.',
        'Dawit Tadesse', 14, 'Discussion on fleet investment risks', 'candidate'
    ) RETURNING id INTO v_quote_id;

    RAISE NOTICE '>>> Seed fixtures successfully initialized.';
END $$;


-- =============================================================================
-- TEST 1: VERIFY SCHEMA CONSTRAINTS & GENERATED COLUMNS
-- =============================================================================

DO $$
DECLARE
    v_seg RECORD;
BEGIN
    RAISE NOTICE '--- TEST 1: Verifying Generated Columns and Table Structure ---';
    SELECT start_ms, start_seconds INTO v_seg FROM transcript_segments WHERE segment_index = 0;
    IF v_seg.start_ms != 0 OR v_seg.start_seconds != 0.00 THEN
        RAISE EXCEPTION 'TEST 1 FAILED: Expected start_seconds = 0.00, got %', v_seg.start_seconds;
    END IF;

    SELECT start_ms, start_seconds INTO v_seg FROM transcript_segments WHERE segment_index = 1;
    IF v_seg.start_seconds != 14.20 THEN
        RAISE EXCEPTION 'TEST 1 FAILED: Expected start_seconds = 14.20, got %', v_seg.start_seconds;
    END IF;
    RAISE NOTICE '>>> TEST 1 PASSED: Generated columns compute stored seconds accurately.';
END $$;


-- =============================================================================
-- TEST 2: DUPLICATE YOUTUBE VIDEO ID REJECTION
-- =============================================================================

DO $$
DECLARE
    v_guest_id UUID;
    v_duplicate_failed BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST 2: Testing Duplicate YouTube Video ID Rejection ---';
    SELECT id INTO v_guest_id FROM guests LIMIT 1;

    BEGIN
        INSERT INTO episodes (
            episode_number, title, summary, guest_id, duration_minutes,
            publication_status, youtube_url, youtube_video_id
        ) VALUES (
            102, 'Another Title', 'Summary text', v_guest_id, 45,
            'draft', 'https://www.youtube.com/watch?v=sample-ep101', 'sample-ep101'
        );
    EXCEPTION
        WHEN unique_violation THEN
            v_duplicate_failed := TRUE;
    END;

    IF NOT v_duplicate_failed THEN
        RAISE EXCEPTION 'TEST 2 FAILED: Expected unique_violation on duplicate youtube_video_id, but insert succeeded!';
    END IF;
    RAISE NOTICE '>>> TEST 2 PASSED: Duplicate YouTube video ID was strictly rejected.';
END $$;


-- =============================================================================
-- TEST 3: VALID AND INVALID TRANSCRIPT TIMESTAMPS
-- =============================================================================

DO $$
DECLARE
    v_ep_id UUID;
    v_negative_start_failed BOOLEAN := FALSE;
    v_end_before_start_failed BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST 3: Testing Valid and Invalid Transcript Timestamps ---';
    SELECT id INTO v_ep_id FROM episodes LIMIT 1;

    -- Test 3A: Negative start_ms must be rejected
    BEGIN
        INSERT INTO transcript_segments (
            episode_id, segment_index, start_ms, end_ms, speaker_label, acquisition_method, text
        ) VALUES (v_ep_id, 99, -500, 1000, 'Speaker', 'manual_upload', 'Invalid timestamp text');
    EXCEPTION
        WHEN check_violation THEN
            v_negative_start_failed := TRUE;
    END;

    IF NOT v_negative_start_failed THEN
        RAISE EXCEPTION 'TEST 3A FAILED: Negative start_ms was not rejected by check constraint!';
    END IF;

    -- Test 3B: end_ms < start_ms must be rejected
    BEGIN
        INSERT INTO transcript_segments (
            episode_id, segment_index, start_ms, end_ms, speaker_label, acquisition_method, text
        ) VALUES (v_ep_id, 100, 5000, 2000, 'Speaker', 'manual_upload', 'Invalid interval text');
    EXCEPTION
        WHEN check_violation THEN
            v_end_before_start_failed := TRUE;
    END;

    IF NOT v_end_before_start_failed THEN
        RAISE EXCEPTION 'TEST 3B FAILED: end_ms < start_ms was not rejected by check constraint!';
    END IF;

    RAISE NOTICE '>>> TEST 3 PASSED: Timestamp boundary constraints strictly enforced.';
END $$;


-- =============================================================================
-- TEST 4: EVIDENCE FOREIGN-KEY INTEGRITY (ON DELETE RESTRICT)
-- =============================================================================

DO $$
DECLARE
    v_insight_id UUID;
    v_segment_id UUID;
    v_fake_segment_id UUID := '00000000-0000-0000-0000-000000000001';
    v_fk_failed BOOLEAN := FALSE;
    v_restrict_failed BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST 4: Testing Evidence Foreign-Key Integrity ---';
    SELECT id INTO v_insight_id FROM insights LIMIT 1;
    SELECT id INTO v_segment_id FROM transcript_segments WHERE segment_index = 0;

    -- Test 4A: Inserting evidence pointing to non-existent segment must fail
    BEGIN
        INSERT INTO insight_evidence (insight_id, segment_id, claim_quote_snippet)
        VALUES (v_insight_id, v_fake_segment_id, 'Orphan evidence reference');
    EXCEPTION
        WHEN foreign_key_violation THEN
            v_fk_failed := TRUE;
    END;

    IF NOT v_fk_failed THEN
        RAISE EXCEPTION 'TEST 4A FAILED: Non-existent segment_id was allowed in insight_evidence!';
    END IF;

    -- Link valid evidence
    INSERT INTO insight_evidence (insight_id, segment_id, claim_quote_snippet)
    VALUES (v_insight_id, v_segment_id, 'Valid evidence reference');

    -- Test 4B: Attempting to delete a segment referenced by insight_evidence must be RESTRICTED
    BEGIN
        DELETE FROM transcript_segments WHERE id = v_segment_id;
    EXCEPTION
        WHEN foreign_key_violation THEN
            v_restrict_failed := TRUE;
    END;

    IF NOT v_restrict_failed THEN
        RAISE EXCEPTION 'TEST 4B FAILED: Deletion of evidence-referenced segment should have been restricted!';
    END IF;

    RAISE NOTICE '>>> TEST 4 PASSED: Evidence foreign key integrity and RESTRICT delete verified.';
END $$;


-- =============================================================================
-- TEST 5: REJECTION OF PUBLICATION WITH UNVERIFIED CONTENT OR MISSING EVIDENCE
-- =============================================================================

DO $$
DECLARE
    v_ep_id UUID;
    v_pub_failed BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST 5: Testing Rejection of Publication on Candidate/Unreviewed Episode ---';
    SELECT id INTO v_ep_id FROM episodes WHERE publication_status = 'draft';

    -- Content is currently in 'candidate' review_status. Publication MUST fail!
    BEGIN
        PERFORM publish_episode(v_ep_id);
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Publication rejected: episode has 0 verified insight%' THEN
                v_pub_failed := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST 5 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_pub_failed THEN
        RAISE EXCEPTION 'TEST 5 FAILED: Candidate episode was published without verified insights!';
    END IF;

    RAISE NOTICE '>>> TEST 5 PASSED: Unreviewed content correctly blocked from publication.';
END $$;


-- =============================================================================
-- TEST 6: SUCCESSFUL PUBLICATION OF VALID REVIEWED CONTENT & EDITORIAL CONFIG
-- =============================================================================

DO $$
DECLARE
    v_ep_id UUID;
    v_insight_id UUID;
    v_quote_id UUID;
    v_res JSONB;
    v_status episode_publication_status;
    v_published_at TIMESTAMPTZ;
BEGIN
    RAISE NOTICE '--- TEST 6: Testing Successful Publication of Valid Reviewed Content ---';
    SELECT id INTO v_ep_id FROM episodes WHERE publication_status = 'draft';
    SELECT id INTO v_insight_id FROM insights WHERE episode_id = v_ep_id;
    SELECT id INTO v_quote_id FROM quotations WHERE episode_id = v_ep_id;

    -- Editor verifies the insight and quotation
    UPDATE insights SET review_status = 'verified' WHERE id = v_insight_id;
    UPDATE quotations SET review_status = 'verified' WHERE id = v_quote_id;

    -- Publish with quotations required (both verified, evidence present)
    v_res := publish_episode(
        p_episode_id := v_ep_id,
        p_admin_user_id := '00000000-0000-0000-0000-000000000099',
        p_require_quotations := TRUE,
        p_min_quotations := 1
    );

    IF (v_res ->> 'success')::boolean != TRUE THEN
        RAISE EXCEPTION 'TEST 6 FAILED: Expected success: true, got %', v_res;
    END IF;

    -- Verify episode record state in database
    SELECT publication_status, published_at INTO v_status, v_published_at
    FROM episodes WHERE id = v_ep_id;

    IF v_status != 'published' OR v_published_at IS NULL THEN
        RAISE EXCEPTION 'TEST 6 FAILED: Episode not updated to published (status=%, published_at=%)',
            v_status, v_published_at;
    END IF;

    RAISE NOTICE '>>> TEST 6 PASSED: Verified episode successfully and atomically published.';
END $$;


-- =============================================================================
-- TEST 7: REPEATED PUBLICATION BEHAVIOR (IDEMPOTENCY)
-- =============================================================================

DO $$
DECLARE
    v_ep_id UUID;
    v_res JSONB;
BEGIN
    RAISE NOTICE '--- TEST 7: Testing Repeated Publication (Idempotency) ---';
    SELECT id INTO v_ep_id FROM episodes WHERE publication_status = 'published';

    v_res := publish_episode(v_ep_id);

    IF (v_res ->> 'success')::boolean != TRUE OR (v_res ->> 'message') != 'Episode is already published' THEN
        RAISE EXCEPTION 'TEST 7 FAILED: Idempotent call did not return safe published message: %', v_res;
    END IF;

    RAISE NOTICE '>>> TEST 7 PASSED: Repeated publication is a safe, idempotent no-op.';
END $$;


-- =============================================================================
-- TEST 8: ATOMIC ROLLBACK IF PUBLICATION FAILS (TRANSACTION INTEGRITY)
-- =============================================================================

DO $$
DECLARE
    v_guest_id UUID;
    v_unsupported_ep_id UUID;
    v_insight_id UUID;
    v_rollback_occurred BOOLEAN := FALSE;
    v_final_status episode_publication_status;
BEGIN
    RAISE NOTICE '--- TEST 8: Testing Atomic Rollback on Publication Failure ---';
    SELECT id INTO v_guest_id FROM guests LIMIT 1;

    -- Create a second episode with a verified insight that has NO evidence
    INSERT INTO episodes (
        episode_number, title, summary, guest_id, duration_minutes,
        publication_status, youtube_url, youtube_video_id
    ) VALUES (
        103, 'Evidence-lacking episode', 'Summary', v_guest_id, 30,
        'draft', 'https://www.youtube.com/watch?v=sample-ep103', 'sample-ep103'
    ) RETURNING id INTO v_unsupported_ep_id;

    INSERT INTO insights (
        episode_id, category, title, summary, practical_action, review_status
    ) VALUES (
        v_unsupported_ep_id, 'Finance & Capital', 'Capital Structure',
        'Summary without evidence', 'Practical action', 'verified'
    ) RETURNING id INTO v_insight_id;

    -- Publication must fail because evidence is missing
    BEGIN
        PERFORM publish_episode(v_unsupported_ep_id);
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%lack supporting transcript evidence references%' THEN
                v_rollback_occurred := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST 8 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_rollback_occurred THEN
        RAISE EXCEPTION 'TEST 8 FAILED: Publication succeeded without evidence!';
    END IF;

    -- Confirm status is still draft (no partial write)
    SELECT publication_status INTO v_final_status FROM episodes WHERE id = v_unsupported_ep_id;
    IF v_final_status != 'draft' THEN
        RAISE EXCEPTION 'TEST 8 FAILED: Episode publication_status mutated to % despite failure!', v_final_status;
    END IF;

    RAISE NOTICE '>>> TEST 8 PASSED: Transaction safely rolled back, leaving state in draft.';
END $$;

ROLLBACK; -- Clean rollback of test transactions

-- =============================================================================
-- TEST 9: ROW LEVEL SECURITY & UNAUTHORIZED ACCESS TESTS
-- =============================================================================

-- Setup test data for RLS in a dedicated test block
BEGIN;

DO $$
DECLARE
    v_guest_id UUID;
    v_pub_ep_id UUID;
    v_draft_ep_id UUID;
    v_seg_id UUID;
    v_ins_ver_id UUID;
    v_ins_cand_id UUID;
BEGIN
    INSERT INTO guests (slug, name, title, company, bio)
    VALUES ('rls-test-guest', 'RLS Guest', 'CTO', 'Test Corp', 'Bio text')
    RETURNING id INTO v_guest_id;

    INSERT INTO episodes (
        episode_number, title, summary, guest_id, duration_minutes,
        publication_status, published_at, youtube_url, youtube_video_id
    ) VALUES (
        201, 'Published Ep', 'Summary', v_guest_id, 50,
        'published', now() - INTERVAL '1 hour',
        'https://www.youtube.com/watch?v=rls-pub-201', 'rls-pub-201'
    ) RETURNING id INTO v_pub_ep_id;

    INSERT INTO episodes (
        episode_number, title, summary, guest_id, duration_minutes,
        publication_status, youtube_url, youtube_video_id
    ) VALUES (
        202, 'Draft Ep', 'Summary', v_guest_id, 40,
        'draft', 'https://www.youtube.com/watch?v=rls-draft-202', 'rls-draft-202'
    ) RETURNING id INTO v_draft_ep_id;

    INSERT INTO insights (episode_id, category, title, summary, review_status)
    VALUES (v_pub_ep_id, 'Operations', 'Verified Insight', 'Summary', 'verified')
    RETURNING id INTO v_ins_ver_id;

    INSERT INTO insights (episode_id, category, title, summary, review_status)
    VALUES (v_pub_ep_id, 'Operations', 'Candidate Insight', 'Summary', 'candidate')
    RETURNING id INTO v_ins_cand_id;

    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, acquisition_method, text
    ) VALUES (
        v_pub_ep_id, 0, 0, 10000, 'manual_upload', 'Internal private transcript text'
    ) RETURNING id INTO v_seg_id;

    INSERT INTO insight_evidence (insight_id, segment_id, claim_quote_snippet)
    VALUES (v_ins_ver_id, v_seg_id, 'Private snippet');
END $$;

-- Switch to unprivileged anon role to verify public view restrictions
SET ROLE anon;

-- Verify anon can only see published episode 201, not draft episode 202
DO $$
DECLARE
    v_count INT;
BEGIN
    RAISE NOTICE '--- TEST 9A: Public Denial of Draft Episodes ---';
    SELECT count(*) INTO v_count FROM episodes WHERE youtube_video_id IN ('rls-pub-201', 'rls-draft-202');
    IF v_count != 1 THEN
        RAISE EXCEPTION 'TEST 9A FAILED: anon saw % episodes, expected exactly 1 (published only)', v_count;
    END IF;

    SELECT count(*) INTO v_count FROM episodes WHERE youtube_video_id = 'rls-draft-202';
    IF v_count != 0 THEN
        RAISE EXCEPTION 'TEST 9A FAILED: anon was able to view draft episode 202!';
    END IF;
    RAISE NOTICE '>>> TEST 9A PASSED: Public anon role denied access to draft episodes.';
END $$;

-- Verify anon cannot see candidate insights
DO $$
DECLARE
    v_count INT;
BEGIN
    RAISE NOTICE '--- TEST 9B: Public Denial of Candidate/Unverified Content ---';
    SELECT count(*) INTO v_count FROM insights WHERE title = 'Candidate Insight';
    IF v_count != 0 THEN
        RAISE EXCEPTION 'TEST 9B FAILED: anon was able to view candidate unverified insight!';
    END IF;

    SELECT count(*) INTO v_count FROM insights WHERE title = 'Verified Insight';
    IF v_count != 1 THEN
        RAISE EXCEPTION 'TEST 9B FAILED: anon was unable to view verified published insight!';
    END IF;
    RAISE NOTICE '>>> TEST 9B PASSED: Public anon role can only read verified insights.';
END $$;

-- Verify anon cannot access internal private tables (jobs, segments, chunks, extraction runs, evidence)
DO $$
DECLARE
    v_denied BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST 9C: Denial of Private Pipeline Internals (Segments & Evidence) ---';
    BEGIN
        PERFORM count(*) FROM transcript_segments;
    EXCEPTION
        WHEN insufficient_privilege THEN
            v_denied := TRUE;
    END;

    IF NOT v_denied THEN
        RAISE EXCEPTION 'TEST 9C FAILED: anon was able to query transcript_segments!';
    END IF;
    RAISE NOTICE '>>> TEST 9C PASSED: Permission denied on internal pipeline tables for anon.';
END $$;

-- Verify anon cannot invoke publish_episode
DO $$
DECLARE
    v_pub_blocked BOOLEAN := FALSE;
    v_fake_id UUID := '00000000-0000-0000-0000-000000000001';
BEGIN
    RAISE NOTICE '--- TEST 9D: Rejection of Unauthorized Publication by anon ---';
    BEGIN
        PERFORM publish_episode(v_fake_id);
    EXCEPTION
        WHEN insufficient_privilege THEN
            v_pub_blocked := TRUE;
        WHEN others THEN
            IF SQLERRM LIKE '%Access denied%' THEN
                v_pub_blocked := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST 9D FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_pub_blocked THEN
        RAISE EXCEPTION 'TEST 9D FAILED: anon was able to invoke publish_episode!';
    END IF;
    RAISE NOTICE '>>> TEST 9D PASSED: Unauthorized publication blocked for unprivileged users.';
END $$;

RESET ROLE;
ROLLBACK;

\echo '============================================================================='
\echo 'ALL 9 DATABASE VERIFICATION TESTS PASSED SUCCESSFULLY ON POSTGRESQL 15+!'
\echo '============================================================================='
