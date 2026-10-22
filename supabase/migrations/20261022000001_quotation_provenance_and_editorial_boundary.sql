-- =============================================================================
-- Migration: 20261022000001_quotation_provenance_and_editorial_boundary.sql
-- Module: Content Pipeline Milestone 3 - Multi-Segment Provenance & Editorial Boundary
-- Target: Supabase Cloud (PostgreSQL 15+)
-- Description: 
--   1. Adds relational join table `quotation_segments` for multi-segment quote provenance.
--   2. Enforces deterministic sequence ordering and uniqueness constraints.
--   3. Validates cross-episode referential integrity via strict database triggers.
--   4. Safely backfills existing quotations into quotation_segments preserving starting anchor.
--   5. Implements server-side authorized editorial review function (`review_candidate_item`).
--   6. Enforces that editorial approval never automatically publishes an episode.
--   7. Configures Row Level Security (RLS) and strict permissions for provenance tables.
--   8. Updates atomic publication RPC (`publish_episode`) to verify quotation provenance.
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. RELATIONAL MULTI-SEGMENT PROVENANCE: TABLE quotation_segments
-- =============================================================================

CREATE TABLE IF NOT EXISTS quotation_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quotation_id UUID NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    segment_id UUID NOT NULL REFERENCES transcript_segments(id) ON DELETE RESTRICT,
    sequence_order INT NOT NULL CHECK (sequence_order >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Enforce uniqueness of quotation-segment pairs
    CONSTRAINT uq_quotation_segment UNIQUE (quotation_id, segment_id),
    -- Enforce uniqueness of sequence position within a quotation
    CONSTRAINT uq_quotation_sequence_order UNIQUE (quotation_id, sequence_order)
);

-- Performance indexes for relational provenance lookups
CREATE INDEX IF NOT EXISTS idx_quotation_segments_quotation_id 
    ON quotation_segments(quotation_id, sequence_order);
CREATE INDEX IF NOT EXISTS idx_quotation_segments_segment_id 
    ON quotation_segments(segment_id);


-- =============================================================================
-- 2. CROSS-EPISODE INTEGRITY TRIGGERS
-- =============================================================================

-- Validates that every linked segment in quotation_segments belongs to the same episode as the quotation
CREATE OR REPLACE FUNCTION check_quotation_segment_same_episode()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_quote_episode_id UUID;
    v_segment_episode_id UUID;
BEGIN
    SELECT episode_id INTO v_quote_episode_id 
    FROM quotations 
    WHERE id = NEW.quotation_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quotation % does not exist.', NEW.quotation_id;
    END IF;

    SELECT episode_id INTO v_segment_episode_id 
    FROM transcript_segments 
    WHERE id = NEW.segment_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Transcript segment % does not exist.', NEW.segment_id;
    END IF;

    IF v_quote_episode_id <> v_segment_episode_id THEN
        RAISE EXCEPTION 'Cross-episode integrity violation: quotation % (episode %) and segment % (episode %) belong to different episodes.',
            NEW.quotation_id, v_quote_episode_id, NEW.segment_id, v_segment_episode_id;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_check_quotation_segment_same_episode ON quotation_segments;
CREATE TRIGGER trg_check_quotation_segment_same_episode
BEFORE INSERT OR UPDATE ON quotation_segments
FOR EACH ROW
EXECUTE FUNCTION check_quotation_segment_same_episode();


-- Also enforce that quotations.segment_id starting anchor belongs to the same episode
CREATE OR REPLACE FUNCTION check_quotation_starting_segment_same_episode()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_segment_episode_id UUID;
BEGIN
    IF NEW.segment_id IS NOT NULL THEN
        SELECT episode_id INTO v_segment_episode_id 
        FROM transcript_segments 
        WHERE id = NEW.segment_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Transcript segment % does not exist.', NEW.segment_id;
        END IF;

        IF v_segment_episode_id <> NEW.episode_id THEN
            RAISE EXCEPTION 'Cross-episode integrity violation: anchor segment % belongs to episode % but quotation % belongs to episode %.',
                NEW.segment_id, v_segment_episode_id, NEW.id, NEW.episode_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_check_quotation_starting_segment_same_episode ON quotations;
CREATE TRIGGER trg_check_quotation_starting_segment_same_episode
BEFORE INSERT OR UPDATE OF segment_id, episode_id ON quotations
FOR EACH ROW
EXECUTE FUNCTION check_quotation_starting_segment_same_episode();


-- =============================================================================
-- 3. SAFE BACKFILL FOR EXISTING QUOTATIONS
-- =============================================================================

-- Populate quotation_segments for any existing quotations that have a starting anchor segment_id
INSERT INTO quotation_segments (quotation_id, segment_id, sequence_order)
SELECT q.id, q.segment_id, 0
FROM quotations q
JOIN transcript_segments s ON s.id = q.segment_id AND s.episode_id = q.episode_id
WHERE q.segment_id IS NOT NULL
ON CONFLICT (quotation_id, segment_id) DO NOTHING;


-- =============================================================================
-- 4. ROW LEVEL SECURITY (RLS) & GRANTS: quotation_segments
-- =============================================================================

ALTER TABLE quotation_segments ENABLE ROW LEVEL SECURITY;

-- Revoke all public access (quotation_segments is private provenance metadata like insight_evidence)
REVOKE ALL ON quotation_segments FROM anon, PUBLIC;

-- Table permissions to enable RLS policies
GRANT ALL ON quotation_segments TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON quotation_segments TO authenticated;

-- Service role full access
CREATE POLICY "Service role full access quotation_segments" 
    ON quotation_segments FOR ALL 
    TO service_role 
    USING (true) 
    WITH CHECK (true);

-- Admin authenticated full access (enforcing server-side app_metadata or admin claims)
CREATE POLICY "Admin full access quotation_segments"
    ON quotation_segments FOR ALL
    TO authenticated
    USING (
        (auth.jwt() ->> 'role') = 'admin' OR 
        (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR 
        (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin'
    )
    WITH CHECK (
        (auth.jwt() ->> 'role') = 'admin' OR 
        (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR 
        (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin'
    );


-- =============================================================================
-- 5. SECURE SERVER-SIDE EDITORIAL APPROVAL RPC FUNCTION
-- =============================================================================

-- Authoritatively transitions a candidate item's review status.
-- STRICT SECURITY RULES:
-- 1. Evaluates server-side authorization: only service_role, postgres, or authenticated
--    users with admin claims in JWT app_metadata are authorized. User-editable metadata is ignored.
-- 2. Transitions review_status between candidate, verified, and rejected.
-- 3. Storing 'approved' maps deterministically to 'verified' to preserve schema enum compatibility.
-- 4. CRITICAL: Reviewing/approving an item NEVER modifies the parent episode publication_status.
--    Publication remains strictly gated behind publish_episode().
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
    -- Security note: In a SECURITY DEFINER function, PostgreSQL sets current_user to the function owner
    -- (typically 'postgres'). Therefore, checking `current_user IN ('postgres', 'service_role')` is a critical
    -- vulnerability that grants access to ANY caller who can invoke the function.
    -- Instead, we evaluate the caller from:
    --   (a) Supabase PostgREST JWT claims (if request.jwt.claims is present)
    --   (b) Direct SQL session role (session_user and current_setting('role')) when no JWT is active.

    v_jwt := nullif(current_setting('request.jwt.claims', true), '')::jsonb;
    v_caller_role := coalesce(nullif(current_setting('role', true), ''), 'none');

    IF v_jwt IS NOT NULL AND v_jwt <> '{}'::jsonb THEN
        -- Case A: HTTP API / PostgREST execution context
        IF (v_jwt ->> 'role') = 'service_role' THEN
            -- Trusted server path via Supabase service_role secret key
            v_is_authorized := TRUE;
        ELSIF (v_jwt ->> 'role') = 'authenticated' THEN
            -- Authenticated user: only permit if verified admin claims exist in server-controlled app_metadata.
            -- Never trust user_metadata (which can be edited by end-users).
            IF (v_jwt -> 'app_metadata' ->> 'role') = 'admin' OR 
               (v_jwt -> 'app_metadata' ->> 'is_admin')::boolean = true THEN
                v_is_authorized := TRUE;
            END IF;
        END IF;
    ELSE
        -- Case B: Direct SQL session (psql, migrations, or direct backend connection pool)
        -- Must ensure the connecting session_user is trusted AND the active role was not set to an unprivileged role.
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
    -- Prevent client-supplied reviewer ID spoofing:
    -- If called by an authenticated user, reviewer identity MUST bind to auth.uid().
    -- Any mismatch between client-supplied p_reviewer_id and auth.uid() is rejected as spoofing.
    IF auth.uid() IS NOT NULL THEN
        IF p_reviewer_id IS NOT NULL AND p_reviewer_id <> auth.uid() THEN
            RAISE EXCEPTION 'Reviewer identity spoofing detected: client-supplied reviewer % does not match authenticated user %.',
                p_reviewer_id, auth.uid();
        END IF;
        v_effective_reviewer := auth.uid();
    ELSE
        -- Trusted-server / service-role path: accept explicitly passed reviewer ID
        v_effective_reviewer := p_reviewer_id;
    END IF;

    -- 4. Apply status update depending on item_type
    IF lower(p_item_type) = 'insight' THEN
        SELECT episode_id, review_status INTO v_episode_id, v_current_review_status
        FROM insights WHERE id = p_item_id FOR UPDATE;

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
        SELECT episode_id, review_status INTO v_episode_id, v_current_review_status
        FROM quotations WHERE id = p_item_id FOR UPDATE;

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

    -- Notice: The parent episode's publication_status is strictly UNTOUCHED.
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

-- Function permissions: revoke from public/anon, grant to authenticated and service_role
REVOKE ALL ON FUNCTION review_candidate_item(TEXT, UUID, TEXT, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION review_candidate_item(TEXT, UUID, TEXT, UUID) FROM anon;
GRANT EXECUTE ON FUNCTION review_candidate_item(TEXT, UUID, TEXT, UUID) TO authenticated, service_role;


-- =============================================================================
-- 6. ENHANCED publish_episode WITH QUOTATION PROVENANCE VERIFICATION
-- =============================================================================

CREATE OR REPLACE FUNCTION publish_episode(
    p_episode_id UUID,
    p_admin_user_id UUID DEFAULT NULL,
    p_min_insights INT DEFAULT 1,
    p_require_quotations BOOLEAN DEFAULT FALSE,
    p_min_quotations INT DEFAULT 0
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth, pg_temp
AS $$
DECLARE
    v_is_authorized BOOLEAN := FALSE;
    v_jwt JSONB;
    v_caller_role TEXT;
    v_effective_publisher UUID;
    v_episode RECORD;
    v_verified_insights_count INT;
    v_verified_quotations_count INT;
    v_unsupported_insights_count INT;
    v_unsupported_quotations_count INT;
    v_target_min_quotations INT;
    v_effective_min_insights INT;
    v_result JSONB;
BEGIN
    -- 1. Strict Server-Side Caller Authorization
    -- Security note: In a SECURITY DEFINER function, PostgreSQL sets current_user to the function owner
    -- (typically 'postgres'). Therefore, checking `current_user IN ('postgres', 'service_role')` is a critical
    -- vulnerability that grants access to ANY caller who can invoke the function.
    -- Instead, we evaluate the caller from:
    --   (a) Supabase PostgREST JWT claims (if request.jwt.claims is present)
    --   (b) Direct SQL session role (session_user and current_setting('role')) when no JWT is active.

    v_jwt := nullif(current_setting('request.jwt.claims', true), '')::jsonb;
    v_caller_role := coalesce(nullif(current_setting('role', true), ''), 'none');

    IF v_jwt IS NOT NULL AND v_jwt <> '{}'::jsonb THEN
        -- Case A: HTTP API / PostgREST execution context
        IF (v_jwt ->> 'role') = 'service_role' THEN
            v_is_authorized := TRUE;
        ELSIF (v_jwt ->> 'role') = 'authenticated' THEN
            IF (v_jwt -> 'app_metadata' ->> 'role') = 'admin' OR 
               (v_jwt -> 'app_metadata' ->> 'is_admin')::boolean = true THEN
                v_is_authorized := TRUE;
            END IF;
        END IF;
    ELSE
        -- Case B: Direct SQL session (psql, migrations, or direct backend connection pool)
        IF session_user IN ('postgres', 'service_role') AND v_caller_role IN ('none', 'postgres', 'service_role') THEN
            v_is_authorized := TRUE;
        END IF;
    END IF;

    IF NOT v_is_authorized THEN
        RAISE EXCEPTION 'Access denied: only administrators or service_role can publish episodes.';
    END IF;

    -- 2. Publisher Identity Integrity
    IF auth.uid() IS NOT NULL THEN
        IF p_admin_user_id IS NOT NULL AND p_admin_user_id <> auth.uid() THEN
            RAISE EXCEPTION 'Publisher identity spoofing detected: client-supplied publisher % does not match authenticated user %.',
                p_admin_user_id, auth.uid();
        END IF;
        v_effective_publisher := auth.uid();
    ELSE
        v_effective_publisher := p_admin_user_id;
    END IF;

    -- 3. Lock and retrieve episode record
    SELECT * INTO v_episode
    FROM episodes
    WHERE id = p_episode_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Episode % not found.', p_episode_id;
    END IF;

    -- 4. Idempotent check: if already published, return safe status without re-running checks
    IF v_episode.publication_status = 'published' THEN
        RETURN jsonb_build_object(
            'success', true,
            'message', 'Episode is already published',
            'episode_id', p_episode_id,
            'published_at', v_episode.published_at
        );
    END IF;

    -- 5. Verify minimum verified insights count (Meri foundation requires >= 1 insight)
    v_effective_min_insights := GREATEST(p_min_insights, 1);

    SELECT count(*) INTO v_verified_insights_count
    FROM insights
    WHERE episode_id = p_episode_id AND review_status = 'verified';

    IF v_verified_insights_count < v_effective_min_insights THEN
        RAISE EXCEPTION 'Publication rejected: episode has % verified insight(s), but at least % is required.',
            v_verified_insights_count, v_effective_min_insights;
    END IF;

    -- 6. Verify quotations according to editorial policy configuration
    SELECT count(*) INTO v_verified_quotations_count
    FROM quotations
    WHERE episode_id = p_episode_id AND review_status = 'verified';

    v_target_min_quotations := CASE 
        WHEN p_require_quotations AND p_min_quotations = 0 THEN 1
        ELSE p_min_quotations
    END;

    IF v_verified_quotations_count < v_target_min_quotations THEN
        RAISE EXCEPTION 'Publication rejected: episode has % verified quotation(s), but % is required by policy.',
            v_verified_quotations_count, v_target_min_quotations;
    END IF;

    -- 7. Verify evidence references for insights: every verified insight MUST have at least one supporting transcript segment
    SELECT count(*) INTO v_unsupported_insights_count
    FROM insights ins
    WHERE ins.episode_id = p_episode_id
      AND ins.review_status = 'verified'
      AND NOT EXISTS (
          SELECT 1 FROM insight_evidence ev WHERE ev.insight_id = ins.id
      );

    IF v_unsupported_insights_count > 0 THEN
        RAISE EXCEPTION 'Publication rejected: % verified insight(s) lack supporting transcript evidence references.',
            v_unsupported_insights_count;
    END IF;

    -- 8. Verify provenance references for quotations: verified quotations must have relational provenance backing
    -- Check quotation_segments join table OR legacy segment_id starting anchor
    SELECT count(*) INTO v_unsupported_quotations_count
    FROM quotations q
    WHERE q.episode_id = p_episode_id
      AND q.review_status = 'verified'
      AND NOT EXISTS (
          SELECT 1 FROM quotation_segments qs WHERE qs.quotation_id = q.id
      )
      AND q.segment_id IS NULL;

    IF v_unsupported_quotations_count > 0 THEN
        RAISE EXCEPTION 'Publication rejected: % verified quotation(s) lack supporting transcript provenance.',
            v_unsupported_quotations_count;
    END IF;

    -- 9. Atomically transition state to published
    UPDATE episodes
    SET publication_status = 'published',
        published_at = COALESCE(published_at, now()),
        updated_at = now()
    WHERE id = p_episode_id;

    -- 10. Return audit response
    v_result := jsonb_build_object(
        'success', true,
        'episode_id', p_episode_id,
        'title', v_episode.title,
        'status', 'published',
        'verified_insights', v_verified_insights_count,
        'verified_quotations', v_verified_quotations_count,
        'published_by', v_effective_publisher,
        'published_at', now()
    );

    RETURN v_result;
END;
$$;

-- Explicit function permissions on publish_episode
REVOKE ALL ON FUNCTION publish_episode(UUID, UUID, INT, BOOLEAN, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION publish_episode(UUID, UUID, INT, BOOLEAN, INT) FROM anon;
GRANT EXECUTE ON FUNCTION publish_episode(UUID, UUID, INT, BOOLEAN, INT) TO authenticated, service_role;

COMMIT;
