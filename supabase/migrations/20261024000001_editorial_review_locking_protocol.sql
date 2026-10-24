-- =============================================================================
-- Migration: 20261024000001_editorial_review_locking_protocol.sql
-- Module: Content Pipeline Milestone 5.2 - Editorial Concurrency & Locking Protocol
-- Target: Supabase Cloud (PostgreSQL 15+)
-- Description:
--   Establishes a consistent, deadlock-free hierarchical locking protocol across:
--   1. Pipeline Ingestion Persistence (PipelineOrchestrator._enforce_rerun_policy)
--   2. Editorial Item Review (review_candidate_item)
--   3. Episode Publication (publish_episode)
--
-- LOCK HIERARCHY:
--   Level 1: parent episode row (`episodes WHERE id = ... FOR UPDATE`)
--   Level 2: child insight rows (`insights WHERE id = ... FOR UPDATE`)
--   Level 3: child quotation rows (`quotations WHERE id = ... FOR UPDATE`)
--
-- By acquiring Level 1 before child modifications, editorial reviews and ingestion
-- candidate reruns are serialized on the parent episode without deadlock risk.
-- =============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION review_candidate_item(
    p_item_type TEXT,
    p_item_id UUID,
    p_decision TEXT,
    p_reviewer_id UUID DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth, pg_temp
AS $$
DECLARE
    v_is_authorized BOOLEAN := FALSE;
    v_target_status editorial_review_status;
    v_effective_reviewer UUID;
    v_rows_updated INT := 0;
    v_episode_id UUID;
    v_current_review_status editorial_review_status;
    v_result JSONB;
    v_jwt JSONB;
    v_caller_role TEXT;
BEGIN
    -- 1. Strict Server-Side Caller Authorization
    v_jwt := nullif(current_setting('request.jwt.claims', true), '')::jsonb;
    v_caller_role := coalesce(nullif(current_setting('role', true), ''), 'none');

    IF v_jwt IS NOT NULL AND v_jwt <> '{}'::jsonb THEN
        IF (v_jwt ->> 'role') = 'service_role' THEN
            v_is_authorized := TRUE;
        ELSIF (v_jwt ->> 'role') = 'authenticated' THEN
            IF (v_jwt -> 'app_metadata' ->> 'role') = 'admin' OR
               (v_jwt -> 'app_metadata' ->> 'is_admin')::boolean = true THEN
                v_is_authorized := TRUE;
            END IF;
        END IF;
    ELSE
        IF session_user IN ('postgres', 'service_role') AND v_caller_role IN ('none', 'postgres', 'service_role') THEN
            v_is_authorized := TRUE;
        END IF;
    END IF;

    IF NOT v_is_authorized THEN
        RAISE EXCEPTION 'Access denied: only administrators or service_role can perform editorial review.';
    END IF;

    -- 2. Normalize and validate editorial decision
    CASE lower(trim(p_decision))
        WHEN 'verified', 'approved' THEN
            v_target_status := 'verified'::editorial_review_status;
        WHEN 'rejected' THEN
            v_target_status := 'rejected'::editorial_review_status;
        WHEN 'candidate' THEN
            v_target_status := 'candidate'::editorial_review_status;
        ELSE
            RAISE EXCEPTION 'Invalid editorial decision: "%". Must be approved, verified, rejected, or candidate.', p_decision;
    END CASE;

    -- 3. Reviewer Identity Integrity
    IF auth.uid() IS NOT NULL THEN
        IF p_reviewer_id IS NOT NULL AND p_reviewer_id <> auth.uid() THEN
            RAISE EXCEPTION 'Reviewer identity spoofing detected: client-supplied reviewer % does not match authenticated user %.',
                p_reviewer_id, auth.uid();
        END IF;
        v_effective_reviewer := auth.uid();
    ELSE
        v_effective_reviewer := p_reviewer_id;
    END IF;

    -- 4. Apply status update following the hierarchical locking protocol:
    -- Level 1: Acquire row lock on parent episode
    -- Level 2: Acquire row lock on target insight or quotation
    IF lower(p_item_type) = 'insight' THEN
        -- Lookup parent episode_id first
        SELECT episode_id INTO v_episode_id
        FROM insights
        WHERE id = p_item_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Insight % not found.', p_item_id;
        END IF;

        -- Level 1 Lock: Parent episode row
        PERFORM 1 FROM episodes WHERE id = v_episode_id FOR UPDATE;

        -- Level 2 Lock: Target insight row
        SELECT review_status INTO v_current_review_status
        FROM insights
        WHERE id = p_item_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Insight % not found.', p_item_id;
        END IF;

        UPDATE insights
        SET review_status = v_target_status,
            reviewed_by = v_effective_reviewer,
            reviewed_at = now(),
            updated_at = now()
        WHERE id = p_item_id;

        GET DIAGNOSTICS v_rows_updated = ROW_COUNT;

    ELSIF lower(p_item_type) = 'quotation' THEN
        -- Lookup parent episode_id first
        SELECT episode_id INTO v_episode_id
        FROM quotations
        WHERE id = p_item_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Quotation % not found.', p_item_id;
        END IF;

        -- Level 1 Lock: Parent episode row
        PERFORM 1 FROM episodes WHERE id = v_episode_id FOR UPDATE;

        -- Level 2 Lock: Target quotation row
        SELECT review_status INTO v_current_review_status
        FROM quotations
        WHERE id = p_item_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Quotation % not found.', p_item_id;
        END IF;

        UPDATE quotations
        SET review_status = v_target_status,
            reviewed_by = v_effective_reviewer,
            reviewed_at = now(),
            updated_at = now()
        WHERE id = p_item_id;

        GET DIAGNOSTICS v_rows_updated = ROW_COUNT;

    ELSE
        RAISE EXCEPTION 'Invalid item_type: "%". Must be "insight" or "quotation".', p_item_type;
    END IF;

    -- Parent episode publication status remains untouched
    v_result := jsonb_build_object(
        'success', true,
        'item_type', lower(p_item_type),
        'item_id', p_item_id,
        'previous_status', v_current_review_status,
        'review_status', v_target_status,
        'reviewed_by', v_effective_reviewer,
        'reviewed_at', now(),
        'episode_id', v_episode_id
    );

    RETURN v_result;
END;
$$;

-- Explicit function permissions
REVOKE ALL ON FUNCTION review_candidate_item(TEXT, UUID, TEXT, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION review_candidate_item(TEXT, UUID, TEXT, UUID) FROM anon;
GRANT EXECUTE ON FUNCTION review_candidate_item(TEXT, UUID, TEXT, UUID) TO authenticated, service_role;

COMMIT;
