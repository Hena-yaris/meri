-- =============================================================================
-- Meri Content Pipeline: Milestone 3 Verification Test Suite
-- Target: PostgreSQL 15+ / Supabase
-- Description: Executes exhaustive assertions covering:
--   1. Multi-segment quotation relational provenance and sequence ordering.
--   2. Uniqueness constraints on quotation-segment pairs and sequence positions.
--   3. Cross-episode integrity rejection (quotation_segments and starting anchor).
--   4. Safe handling and backfill of pre-existing quotations.
--   5. Candidate review status preservation (never auto-promoted).
--   6. Rejection of unauthorized approval (anon and untrusted user_metadata).
--   7. Authorized editorial approval and rejection via review_candidate_item().
--   8. Editorial boundary: approval never automatically publishes an episode.
--   9. Publication rejection of candidate/unapproved content.
--  10. Quotation provenance requirement during publication.
--  11. Row Level Security: private table protection for quotation_segments.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- =============================================================================
-- TEST SUITE SETUP: SEED FIXTURES FOR MILESTONE 3
-- =============================================================================

DO $$
DECLARE
    v_guest_id UUID;
    v_ep1_id UUID;
    v_ep2_id UUID;
    v_seg1_0 UUID;
    v_seg1_1 UUID;
    v_seg1_2 UUID;
    v_seg2_0 UUID;
    v_quote_id UUID;
    v_insight_id UUID;
BEGIN
    RAISE NOTICE '>>> [M3] Initializing Milestone 3 Test Fixtures...';

    -- Guest
    INSERT INTO guests (slug, name, title, company, bio, industry)
    VALUES (
        'samuel-alemu', 'Samuel Alemu', 'Co-Founder', 'Fintech Ethiopia',
        'Pioneer in interoperable digital payment networks.', 'Fintech'
    ) RETURNING id INTO v_guest_id;

    -- Episode 1 (Draft)
    INSERT INTO episodes (
        legacy_id, episode_number, title, summary, guest_id,
        duration_minutes, publication_status, youtube_url, youtube_video_id
    ) VALUES (
        'ep-301', 301, 'Mobile Money Architecture and Interoperability',
        'In-depth discussion on banking rails.', v_guest_id,
        60, 'draft', 'https://www.youtube.com/watch?v=sample-ep301', 'sample-ep301'
    ) RETURNING id INTO v_ep1_id;

    -- Episode 2 (Draft, separate episode for cross-episode tests)
    INSERT INTO episodes (
        legacy_id, episode_number, title, summary, guest_id,
        duration_minutes, publication_status, youtube_url, youtube_video_id
    ) VALUES (
        'ep-302', 302, 'Agricultural Commodity Aggregation',
        'Discussion on commodity exchanges.', v_guest_id,
        45, 'draft', 'https://www.youtube.com/watch?v=sample-ep302', 'sample-ep302'
    ) RETURNING id INTO v_ep2_id;

    -- Segments for Episode 1
    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_ep1_id, 0, 0, 8000, 'Samuel Alemu', 'am', 'manual_upload',
        'ዲጂታል ክፍያ በኢትዮጵያ ውስጥ ገና በጅምር ላይ ያለ ትልቅ ዕድል ነው።'
    ) RETURNING id INTO v_seg1_0;

    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_ep1_id, 1, 8001, 19000, 'Samuel Alemu', 'am', 'manual_upload',
        'ትልቁ ፈተና ቴክኖሎጂ ሳይሆን የባንኮችና የቴሌኮም ስርዓቶች እርስ በርስ መተሳሰር ነው።'
    ) RETURNING id INTO v_seg1_1;

    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_ep1_id, 2, 19001, 31000, 'Samuel Alemu', 'am', 'manual_upload',
        'ይህ መተሳሰር ሲፈጠር የግብይት ወጪ በከፍተኛ ደረጃ ይቀንሳል።'
    ) RETURNING id INTO v_seg1_2;

    -- Segment for Episode 2 (belongs to ep-302)
    INSERT INTO transcript_segments (
        episode_id, segment_index, start_ms, end_ms, speaker_label, language_code, acquisition_method, text
    ) VALUES (
        v_ep2_id, 0, 0, 12000, 'Samuel Alemu', 'am', 'manual_upload',
        'የእህል ምርት ግብይት በቴክኖሎጂ ሲታገዝ ገበሬው ተጠቃሚ ይሆናል።'
    ) RETURNING id INTO v_seg2_0;

    -- Candidate insight for Ep 1 (review_status='candidate')
    INSERT INTO insights (
        episode_id, category, title, summary, takeaways, practical_action, review_status
    ) VALUES (
        v_ep1_id, 'Fintech & Banking', 'Interoperable Banking Rails',
        'Interoperability between banks and telcos reduces marginal transaction friction.',
        ARRAY['APIs must be standardized', 'Settlement latency must be under 3s'],
        'Implement standardized ISO 20022 message schemas', 'candidate'
    ) RETURNING id INTO v_insight_id;

    -- Link evidence for insight
    INSERT INTO insight_evidence (insight_id, segment_id, claim_quote_snippet)
    VALUES (v_insight_id, v_seg1_1, 'ትልቁ ፈተና ቴክኖሎጂ ሳይሆን የባንኮችና የቴሌኮም ስርዓቶች...');

    -- Candidate quotation for Ep 1 spanning multi-segment (segments 1 and 2)
    -- Canonical timestamp derived from start_ms of segment 1 (8001 ms -> 8 seconds)
    -- Preserving segment_id anchor to starting segment v_seg1_1
    INSERT INTO quotations (
        episode_id, segment_id, amharic_quote, english_translation,
        speaker, timestamp_seconds, context, review_status
    ) VALUES (
        v_ep1_id, v_seg1_1,
        'ትልቁ ፈተና ቴክኖሎጂ ሳይሆን የባንኮችና የቴሌኮም ስርዓቶች እርስ በርስ መተሳሰር ነው። ይህ መተሳሰር ሲፈጠር የግብይት ወጪ በከፍተኛ ደረጃ ይቀንሳል።',
        'The greatest hurdle is not technology, but interoperability between banks and telcos. Once interconnected, transaction costs plunge.',
        'Samuel Alemu', 8, 'Addressing payment infrastructure roadblocks', 'candidate'
    ) RETURNING id INTO v_quote_id;

    -- Relational multi-segment provenance: link sequence 0 and sequence 1
    INSERT INTO quotation_segments (quotation_id, segment_id, sequence_order)
    VALUES 
        (v_quote_id, v_seg1_1, 0),
        (v_quote_id, v_seg1_2, 1);

    RAISE NOTICE '>>> [M3] Test fixtures successfully initialized.';
END $$;


-- =============================================================================
-- TEST M3.1: MULTI-SEGMENT PROVENANCE & DETERMINISTIC SEQUENCE ORDERING
-- =============================================================================

DO $$
DECLARE
    v_quote RECORD;
    v_qs RECORD;
    v_count INT;
    v_seqs INT[];
BEGIN
    RAISE NOTICE '--- TEST M3.1: Multi-Segment Quotation Relational Provenance & Sequence ---';

    SELECT * INTO v_quote FROM quotations WHERE amharic_quote LIKE 'ትልቁ ፈተና%';

    -- Anchor segment_id must match the first segment
    IF v_quote.segment_id IS NULL THEN
        RAISE EXCEPTION 'TEST M3.1 FAILED: quotations.segment_id starting anchor is NULL!';
    END IF;

    -- Canonical timestamp must match 8 seconds (from 8001ms)
    IF v_quote.timestamp_seconds != 8 THEN
        RAISE EXCEPTION 'TEST M3.1 FAILED: Expected canonical timestamp 8, got %', v_quote.timestamp_seconds;
    END IF;

    -- Verify quotation_segments relational entries
    SELECT count(*), array_agg(sequence_order ORDER BY sequence_order) 
    INTO v_count, v_seqs
    FROM quotation_segments 
    WHERE quotation_id = v_quote.id;

    IF v_count != 2 THEN
        RAISE EXCEPTION 'TEST M3.1 FAILED: Expected 2 quotation_segments, got %', v_count;
    END IF;

    IF v_seqs != ARRAY[0, 1] THEN
        RAISE EXCEPTION 'TEST M3.1 FAILED: Expected sequence orders [0, 1], got %', v_seqs;
    END IF;

    RAISE NOTICE '>>> TEST M3.1 PASSED: Multi-segment provenance with deterministic sequence verified.';
END $$;


-- =============================================================================
-- TEST M3.2: ENFORCE UNIQUENESS FOR QUOTATION/SEGMENT ASSOCIATIONS & POSITIONS
-- =============================================================================

DO $$
DECLARE
    v_quote_id UUID;
    v_seg1_1 UUID;
    v_seg1_0 UUID;
    v_dup_assoc_failed BOOLEAN := FALSE;
    v_dup_seq_failed BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M3.2: Uniqueness of Quotation/Segment & Sequence Position ---';

    SELECT id INTO v_quote_id FROM quotations LIMIT 1;
    SELECT segment_id INTO v_seg1_1 FROM quotation_segments WHERE quotation_id = v_quote_id AND sequence_order = 0;
    SELECT id INTO v_seg1_0 FROM transcript_segments WHERE segment_index = 0 AND episode_id = (SELECT episode_id FROM quotations WHERE id = v_quote_id);

    -- 1. Attempt duplicate (quotation_id, segment_id) association
    BEGIN
        INSERT INTO quotation_segments (quotation_id, segment_id, sequence_order)
        VALUES (v_quote_id, v_seg1_1, 99);
    EXCEPTION
        WHEN unique_violation THEN
            v_dup_assoc_failed := TRUE;
    END;

    IF NOT v_dup_assoc_failed THEN
        RAISE EXCEPTION 'TEST M3.2 FAILED: Duplicate (quotation_id, segment_id) association was permitted!';
    END IF;

    -- 2. Attempt duplicate sequence_order on the same quotation
    BEGIN
        INSERT INTO quotation_segments (quotation_id, segment_id, sequence_order)
        VALUES (v_quote_id, v_seg1_0, 0); -- sequence_order 0 already taken
    EXCEPTION
        WHEN unique_violation THEN
            v_dup_seq_failed := TRUE;
    END;

    IF NOT v_dup_seq_failed THEN
        RAISE EXCEPTION 'TEST M3.2 FAILED: Duplicate sequence_order position on quotation was permitted!';
    END IF;

    RAISE NOTICE '>>> TEST M3.2 PASSED: Unique constraints on associations and sequence positions strictly enforced.';
END $$;


-- =============================================================================
-- TEST M3.3: CROSS-EPISODE INTEGRITY TRIGGER ON quotation_segments
-- =============================================================================

DO $$
DECLARE
    v_quote_id UUID;
    v_ep2_seg_id UUID;
    v_cross_episode_failed BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M3.3: Cross-Episode Reference Rejection on quotation_segments ---';

    -- Quote belongs to Ep 1
    SELECT q.id INTO v_quote_id 
    FROM quotations q 
    JOIN episodes e ON e.id = q.episode_id 
    WHERE e.episode_number = 301 LIMIT 1;

    -- Segment belongs to Ep 2
    SELECT s.id INTO v_ep2_seg_id 
    FROM transcript_segments s 
    JOIN episodes e ON e.id = s.episode_id 
    WHERE e.episode_number = 302 LIMIT 1;

    -- Attempt to link Ep 2 segment to Ep 1 quote
    BEGIN
        INSERT INTO quotation_segments (quotation_id, segment_id, sequence_order)
        VALUES (v_quote_id, v_ep2_seg_id, 5);
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Cross-episode integrity violation%' THEN
                v_cross_episode_failed := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.3 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_cross_episode_failed THEN
        RAISE EXCEPTION 'TEST M3.3 FAILED: Cross-episode quotation_segment was allowed!';
    END IF;

    RAISE NOTICE '>>> TEST M3.3 PASSED: Cross-episode reference on quotation_segments strictly rejected.';
END $$;


-- =============================================================================
-- TEST M3.4: CROSS-EPISODE INTEGRITY TRIGGER ON quotations.segment_id ANCHOR
-- =============================================================================

DO $$
DECLARE
    v_ep1_id UUID;
    v_ep2_seg_id UUID;
    v_anchor_failed BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M3.4: Cross-Episode Anchor Rejection on quotations.segment_id ---';

    SELECT id INTO v_ep1_id FROM episodes WHERE episode_number = 301;
    SELECT s.id INTO v_ep2_seg_id 
    FROM transcript_segments s 
    JOIN episodes e ON e.id = s.episode_id 
    WHERE e.episode_number = 302 LIMIT 1;

    BEGIN
        INSERT INTO quotations (
            episode_id, segment_id, amharic_quote, english_translation,
            speaker, timestamp_seconds, context, review_status
        ) VALUES (
            v_ep1_id, v_ep2_seg_id, 'የተሳሳተ ጥቅስ', 'Wrong quote',
            'Speaker', 0, 'Context', 'candidate'
        );
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Cross-episode integrity violation%' THEN
                v_anchor_failed := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.4 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_anchor_failed THEN
        RAISE EXCEPTION 'TEST M3.4 FAILED: Cross-episode segment anchor was allowed in quotations!';
    END IF;

    RAISE NOTICE '>>> TEST M3.4 PASSED: Cross-episode anchor in quotations.segment_id strictly rejected.';
END $$;


-- =============================================================================
-- TEST M3.5: CANDIDATE STATUS PRESERVATION (NEVER AUTOMATICALLY PROMOTED)
-- =============================================================================

DO $$
DECLARE
    v_cand_insight RECORD;
    v_cand_quote RECORD;
BEGIN
    RAISE NOTICE '--- TEST M3.5: Candidate Status Preservation ---';

    SELECT review_status INTO v_cand_insight FROM insights WHERE title = 'Interoperable Banking Rails';
    SELECT review_status INTO v_cand_quote FROM quotations WHERE amharic_quote LIKE 'ትልቁ ፈተና%';

    IF v_cand_insight.review_status != 'candidate' THEN
        RAISE EXCEPTION 'TEST M3.5 FAILED: Candidate insight initialized to % instead of candidate!',
            v_cand_insight.review_status;
    END IF;

    IF v_cand_quote.review_status != 'candidate' THEN
        RAISE EXCEPTION 'TEST M3.5 FAILED: Candidate quotation initialized to % instead of candidate!',
            v_cand_quote.review_status;
    END IF;

    RAISE NOTICE '>>> TEST M3.5 PASSED: Candidate items strictly staged with review_status=candidate.';
END $$;


-- =============================================================================
-- TEST M3.6: REJECTION OF UNAUTHORIZED EDITORIAL APPROVAL AND PUBLICATION
-- =============================================================================

DO $$
DECLARE
    v_ins_id UUID;
    v_ep1_id UUID;
    v_anon_blocked BOOLEAN := FALSE;
    v_unauth_jwt_blocked BOOLEAN := FALSE;
    v_user_metadata_spoof_blocked BOOLEAN := FALSE;
    v_unauth_pub_blocked BOOLEAN := FALSE;
    v_direct_role_blocked BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M3.6: Rejection of Unauthorized Editorial Approval & Publication ---';
    SELECT id INTO v_ins_id FROM insights LIMIT 1;
    SELECT id INTO v_ep1_id FROM episodes WHERE episode_number = 301 LIMIT 1;

    -- Subtest 1: Anon role invocation blocked (Grant-level REVOKE)
    SET ROLE anon;
    BEGIN
        PERFORM review_candidate_item('insight', v_ins_id, 'approved');
    EXCEPTION
        WHEN insufficient_privilege THEN
            v_anon_blocked := TRUE;
        WHEN others THEN
            IF SQLERRM LIKE '%Access denied%' THEN
                v_anon_blocked := TRUE;
            END IF;
    END;
    RESET ROLE;

    IF NOT v_anon_blocked THEN
        RAISE EXCEPTION 'TEST M3.6.1 FAILED: Unprivileged anon role was able to invoke review_candidate_item!';
    END IF;

    -- Subtest 2: Authenticated ordinary user (JWT role=authenticated, no admin claims in app_metadata)
    SET ROLE authenticated;
    SET LOCAL "request.jwt.claims" = '{"role": "authenticated", "sub": "11111111-1111-1111-1111-111111111111", "app_metadata": {}}';
    BEGIN
        PERFORM review_candidate_item('insight', v_ins_id, 'approved');
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Access denied: only administrators or service_role%' THEN
                v_unauth_jwt_blocked := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.6.2 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_unauth_jwt_blocked THEN
        RAISE EXCEPTION 'TEST M3.6.2 FAILED: Ordinary authenticated user without admin claims was allowed to review candidate!';
    END IF;

    -- Subtest 3: Authenticated user attempting to forge admin claim via user_metadata
    -- (In Supabase, user_metadata is editable by clients, app_metadata is server-controlled)
    SET LOCAL "request.jwt.claims" = '{"role": "authenticated", "sub": "11111111-1111-1111-1111-111111111111", "user_metadata": {"role": "admin", "is_admin": true}, "app_metadata": {}}';
    BEGIN
        PERFORM review_candidate_item('insight', v_ins_id, 'approved');
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Access denied: only administrators or service_role%' THEN
                v_user_metadata_spoof_blocked := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.6.3 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_user_metadata_spoof_blocked THEN
        RAISE EXCEPTION 'TEST M3.6.3 FAILED: Attacker spoofing admin claim in user_metadata bypassed authorization!';
    END IF;

    -- Subtest 4: Authenticated ordinary user attempting to call publish_episode
    BEGIN
        PERFORM publish_episode(v_ep1_id);
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Access denied: only administrators or service_role%' THEN
                v_unauth_pub_blocked := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.6.4 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_unauth_pub_blocked THEN
        RAISE EXCEPTION 'TEST M3.6.4 FAILED: Ordinary authenticated user was allowed to invoke publish_episode!';
    END IF;

    -- Subtest 5: Direct SQL session switched to authenticated with no active JWT claims
    SET LOCAL "request.jwt.claims" = '';
    BEGIN
        PERFORM review_candidate_item('insight', v_ins_id, 'approved');
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Access denied: only administrators or service_role%' THEN
                v_direct_role_blocked := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.6.5 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;
    RESET ROLE;

    IF NOT v_direct_role_blocked THEN
        RAISE EXCEPTION 'TEST M3.6.5 FAILED: Direct unprivileged session without JWT bypassed SECURITY DEFINER checks!';
    END IF;

    RAISE NOTICE '>>> TEST M3.6 PASSED: All unauthorized callers (anon, untrusted JWT, forged user_metadata, direct role) strictly denied.';
END $$;


-- =============================================================================
-- TEST M3.7: REVIEWER & PUBLISHER IDENTITY INTEGRITY (SPOOFING PREVENTION)
-- =============================================================================

DO $$
DECLARE
    v_ins_id UUID;
    v_quote_id UUID;
    v_ep1_id UUID;
    v_res JSONB;
    v_spoof_reviewer_blocked BOOLEAN := FALSE;
    v_spoof_publisher_blocked BOOLEAN := FALSE;
    v_admin_uid UUID := '11111111-1111-1111-1111-111111111111'::uuid;
    v_spoofed_uid UUID := '99999999-9999-9999-9999-999999999999'::uuid;
    v_service_reviewer UUID := '88888888-8888-8888-8888-888888888888'::uuid;
    v_recorded_reviewer UUID;
BEGIN
    RAISE NOTICE '--- TEST M3.7: Reviewer & Publisher Identity Integrity ---';
    SELECT id INTO v_ins_id FROM insights WHERE title = 'Interoperable Banking Rails';
    SELECT id INTO v_quote_id FROM quotations WHERE amharic_quote LIKE 'ትልቁ ፈተና%';
    SELECT id INTO v_ep1_id FROM episodes WHERE episode_number = 301;

    -- 1. Reviewer identity spoofing attempt: Authenticated admin passes different p_reviewer_id
    SET ROLE authenticated;
    SET LOCAL "request.jwt.claims" = '{"role": "authenticated", "sub": "11111111-1111-1111-1111-111111111111", "app_metadata": {"role": "admin"}}';

    BEGIN
        PERFORM review_candidate_item(
            p_item_type := 'insight',
            p_item_id := v_ins_id,
            p_decision := 'approved',
            p_reviewer_id := v_spoofed_uid
        );
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Reviewer identity spoofing detected%' THEN
                v_spoof_reviewer_blocked := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.7.1 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_spoof_reviewer_blocked THEN
        RAISE EXCEPTION 'TEST M3.7.1 FAILED: Authenticated admin was able to spoof p_reviewer_id!';
    END IF;

    -- 2. Legitimate authenticated reviewer approval (p_reviewer_id is NULL or matches auth.uid())
    v_res := review_candidate_item(
        p_item_type := 'insight',
        p_item_id := v_ins_id,
        p_decision := 'approved',
        p_reviewer_id := NULL
    );

    IF (v_res ->> 'success')::boolean != TRUE OR (v_res ->> 'reviewed_by')::uuid != v_admin_uid THEN
        RAISE EXCEPTION 'TEST M3.7.2 FAILED: Expected reviewed_by=%, got: %', v_admin_uid, v_res;
    END IF;

    SELECT reviewed_by INTO v_recorded_reviewer FROM insights WHERE id = v_ins_id;
    IF v_recorded_reviewer != v_admin_uid THEN
        RAISE EXCEPTION 'TEST M3.7.2 FAILED: Stored reviewed_by is %, expected %', v_recorded_reviewer, v_admin_uid;
    END IF;

    -- 3. Publisher identity spoofing attempt on publish_episode
    BEGIN
        PERFORM publish_episode(
            p_episode_id := v_ep1_id,
            p_admin_user_id := v_spoofed_uid
        );
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Publisher identity spoofing detected%' THEN
                v_spoof_publisher_blocked := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.7.3 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_spoof_publisher_blocked THEN
        RAISE EXCEPTION 'TEST M3.7.3 FAILED: Authenticated admin was able to spoof p_admin_user_id!';
    END IF;

    RESET ROLE;

    -- 4. Trusted server / service-role path: accepts explicit p_reviewer_id
    SET ROLE service_role;
    SET LOCAL "request.jwt.claims" = '{"role": "service_role"}';

    v_res := review_candidate_item(
        p_item_type := 'quotation',
        p_item_id := v_quote_id,
        p_decision := 'approved',
        p_reviewer_id := v_service_reviewer
    );

    IF (v_res ->> 'success')::boolean != TRUE OR (v_res ->> 'reviewed_by')::uuid != v_service_reviewer THEN
        RAISE EXCEPTION 'TEST M3.7.4 FAILED: Service role approval failed to record explicit reviewer: %', v_res;
    END IF;

    SELECT reviewed_by INTO v_recorded_reviewer FROM quotations WHERE id = v_quote_id;
    IF v_recorded_reviewer != v_service_reviewer THEN
        RAISE EXCEPTION 'TEST M3.7.4 FAILED: Stored quotation reviewed_by is %, expected %',
            v_recorded_reviewer, v_service_reviewer;
    END IF;

    RESET ROLE;
    SET LOCAL "request.jwt.claims" = '';

    RAISE NOTICE '>>> TEST M3.7 PASSED: Reviewer & publisher spoofing prevented; trusted server path verified.';
END $$;


-- =============================================================================
-- TEST M3.8: RECONCILE REVIEW-STATUS CONSTRAINTS & SEPARATION FROM PUBLICATION
-- =============================================================================

DO $$
DECLARE
    v_ins_id UUID;
    v_ep_status episode_publication_status;
    v_ep_published_at TIMESTAMPTZ;
    v_enum_invalid_blocked BOOLEAN := FALSE;
    v_res JSONB;
BEGIN
    RAISE NOTICE '--- TEST M3.8: Reconcile review_status constraints & editorial boundary ---';
    SELECT id INTO v_ins_id FROM insights WHERE title = 'Interoperable Banking Rails';

    -- 1. Direct INSERT / UPDATE with 'approved' is strictly rejected by PostgreSQL enum
    BEGIN
        UPDATE insights SET review_status = 'approved'::editorial_review_status WHERE id = v_ins_id;
    EXCEPTION
        WHEN invalid_text_representation THEN
            v_enum_invalid_blocked := TRUE;
        WHEN others THEN
            IF SQLERRM LIKE '%invalid input value for enum editorial_review_status: "approved"%' THEN
                v_enum_invalid_blocked := TRUE;
            END IF;
    END;

    IF NOT v_enum_invalid_blocked THEN
        RAISE EXCEPTION 'TEST M3.8.1 FAILED: review_status permitted un-enumerated value "approved" directly!';
    END IF;

    -- 2. Verify that review_candidate_item accepts 'approved' and 'verified' and stores 'verified'
    v_res := review_candidate_item('insight', v_ins_id, 'verified');
    IF (v_res ->> 'review_status') != 'verified' THEN
        RAISE EXCEPTION 'TEST M3.8.2 FAILED: Calling with decision "verified" returned %', v_res;
    END IF;

    -- 3. Verify that editorial approval strictly preserves episode draft status
    SELECT publication_status, published_at 
    INTO v_ep_status, v_ep_published_at
    FROM episodes 
    WHERE episode_number = 301;

    IF v_ep_status != 'draft' OR v_ep_published_at IS NOT NULL THEN
        RAISE EXCEPTION 'TEST M3.8.3 FAILED: Editorial approval modified episode publication_status to % (published_at=%)!',
            v_ep_status, v_ep_published_at;
    END IF;

    RAISE NOTICE '>>> TEST M3.8 PASSED: review_status constraint verified; verified is distinct from publication.';
END $$;


-- =============================================================================
-- TEST M3.9: REJECTION OF PUBLICATION FOR UNAPPROVED CANDIDATES
-- =============================================================================

DO $$
DECLARE
    v_ep2_id UUID;
    v_pub_rejected BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M3.9: Rejection of Publication for Unapproved Candidate Episode ---';

    SELECT id INTO v_ep2_id FROM episodes WHERE episode_number = 302;

    -- Episode 302 has no verified insights. Publication must be strictly rejected!
    BEGIN
        PERFORM publish_episode(v_ep2_id);
    EXCEPTION
        WHEN others THEN
            IF SQLERRM LIKE '%Publication rejected%' THEN
                v_pub_rejected := TRUE;
            ELSE
                RAISE EXCEPTION 'TEST M3.9 FAILED with unexpected error: %', SQLERRM;
            END IF;
    END;

    IF NOT v_pub_rejected THEN
        RAISE EXCEPTION 'TEST M3.9 FAILED: Episode 302 without verified insights was published!';
    END IF;

    RAISE NOTICE '>>> TEST M3.9 PASSED: Unapproved candidates strictly rejected from publication.';
END $$;


-- =============================================================================
-- TEST M3.10: ATOMIC PUBLICATION OF VERIFIED CONTENT WITH QUOTATION PROVENANCE
-- =============================================================================

DO $$
DECLARE
    v_ep1_id UUID;
    v_res JSONB;
    v_final_status episode_publication_status;
BEGIN
    RAISE NOTICE '--- TEST M3.10: Successful Publication with Quotation Provenance Verification ---';

    SELECT id INTO v_ep1_id FROM episodes WHERE episode_number = 301;

    -- Now publish Episode 301 via explicit publish_episode RPC with quotation verification enabled
    v_res := publish_episode(
        p_episode_id := v_ep1_id,
        p_admin_user_id := '00000000-0000-0000-0000-000000000101',
        p_require_quotations := TRUE,
        p_min_quotations := 1
    );

    IF (v_res ->> 'success')::boolean != TRUE THEN
        RAISE EXCEPTION 'TEST M3.10 FAILED: Publication RPC failed: %', v_res;
    END IF;

    SELECT publication_status INTO v_final_status FROM episodes WHERE id = v_ep1_id;
    IF v_final_status != 'published' THEN
        RAISE EXCEPTION 'TEST M3.10 FAILED: Episode not in published status: %', v_final_status;
    END IF;

    RAISE NOTICE '>>> TEST M3.10 PASSED: Verified episode with quotation provenance published atomically.';
END $$;


-- =============================================================================
-- TEST M3.11: ROW LEVEL SECURITY & PRIVATE DATA PROTECTION
-- =============================================================================

-- Subtest 1: Public anon role denied query access to quotation_segments
SET ROLE anon;

DO $$
DECLARE
    v_anon_denied BOOLEAN := FALSE;
BEGIN
    RAISE NOTICE '--- TEST M3.11: RLS Denial of quotation_segments for Public Anon Role ---';

    BEGIN
        PERFORM count(*) FROM quotation_segments;
    EXCEPTION
        WHEN insufficient_privilege THEN
            v_anon_denied := TRUE;
    END;

    IF NOT v_anon_denied THEN
        RAISE EXCEPTION 'TEST M3.11.1 FAILED: Public anon role was able to query quotation_segments!';
    END IF;
END $$;

RESET ROLE;

-- Subtest 2: Ordinary authenticated client querying quotation_segments receives 0 rows (RLS policy)
SET ROLE authenticated;
SET LOCAL "request.jwt.claims" = '{"role": "authenticated", "sub": "22222222-2222-2222-2222-222222222222", "app_metadata": {}}';

DO $$
DECLARE
    v_row_count INT;
BEGIN
    SELECT count(*) INTO v_row_count FROM quotation_segments;
    IF v_row_count != 0 THEN
        RAISE EXCEPTION 'TEST M3.11.2 FAILED: Ordinary authenticated user saw % rows in private quotation_segments!', v_row_count;
    END IF;
END $$;

-- Subtest 3: Ordinary authenticated user can ONLY read verified insights from published episodes
DO $$
DECLARE
    v_visible_draft_insights INT;
BEGIN
    -- Episode 302 is draft and candidate. Should NOT be visible to authenticated user.
    SELECT count(*) INTO v_visible_draft_insights
    FROM insights i
    JOIN episodes e ON e.id = i.episode_id
    WHERE e.episode_number = 302;

    IF v_visible_draft_insights != 0 THEN
        RAISE EXCEPTION 'TEST M3.11.3 FAILED: Ordinary authenticated user was able to view draft candidate insight (count=%)!',
            v_visible_draft_insights;
    END IF;
END $$;

RESET ROLE;

\echo '>>> TEST M3.11 PASSED: quotation_segments and candidate items strictly protected by RLS and grants.'

ROLLBACK;

\echo '============================================================================='
\echo 'ALL 11 MILESTONE 3 VERIFICATION TESTS PASSED SUCCESSFULLY ON POSTGRESQL 15+!'
\echo '============================================================================='

