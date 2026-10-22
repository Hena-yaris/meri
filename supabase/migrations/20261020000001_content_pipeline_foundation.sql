-- =============================================================================
-- Migration: 20261020000001_content_pipeline_foundation.sql
-- Module: Content Pipeline Contracts and Database Foundation
-- Target: Supabase Cloud (PostgreSQL 15+)
-- Description: Sets up the transcript-first content pipeline foundation including
--              episodes, guests, processing jobs, transcript segments, chunks,
--              extraction runs, insights, quotations, evidence references,
--              grants, Row-Level Security (RLS), and atomic transactional publication.
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- =============================================================================
-- 1. ENUM TYPES
-- =============================================================================

-- Episode publication lifecycle status (strictly separated from job processing status)
DO $$ BEGIN
    CREATE TYPE episode_publication_status AS ENUM (
        'draft',
        'in_review',
        'published',
        'archived'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Background processing job execution status
DO $$ BEGIN
    CREATE TYPE processing_job_status AS ENUM (
        'pending',
        'processing',
        'completed',
        'failed',
        'cancelled'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Processing pipeline stages for deterministic tracking and independent retries
DO $$ BEGIN
    CREATE TYPE processing_stage AS ENUM (
        'submission',
        'metadata_retrieval',
        'transcript_acquisition',
        'transcript_normalization',
        'chunking',
        'ai_extraction',
        'validation',
        'human_review',
        'publication'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Method used to acquire source transcripts
DO $$ BEGIN
    CREATE TYPE transcript_acquisition_method AS ENUM (
        'youtube_caption_manual',
        'youtube_caption_auto',
        'whisper_audio',
        'manual_upload',
        'external_vendor'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Verification/editorial review state for candidate extractions
DO $$ BEGIN
    CREATE TYPE editorial_review_status AS ENUM (
        'candidate',
        'verified',
        'rejected'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;


-- =============================================================================
-- 2. CORE DOMAIN TABLES: GUESTS & EPISODES
-- =============================================================================

-- Table 1: guests
-- Verified entrepreneurs, leaders, and subject matter experts featured on Meri.
CREATE TABLE IF NOT EXISTS guests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    bio TEXT NOT NULL,
    industry TEXT,
    avatar_url TEXT,
    social_links JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 2: episodes
-- Long-form business podcast episodes. Separates publication state from ingestion state.
CREATE TABLE IF NOT EXISTS episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_id TEXT UNIQUE, -- Preserves backward-compatibility with local fixtures (e.g. 'ep-101')
    podcast_title TEXT NOT NULL DEFAULT 'Meri Podcast',
    episode_number INT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    guest_id UUID NOT NULL REFERENCES guests(id) ON DELETE RESTRICT,
    duration_minutes INT NOT NULL CHECK (duration_minutes > 0),
    publication_status episode_publication_status NOT NULL DEFAULT 'draft',
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    tags TEXT[] NOT NULL DEFAULT '{}',
    audio_url TEXT,
    cover_image_url TEXT,
    youtube_url TEXT NOT NULL,
    youtube_video_id TEXT NOT NULL UNIQUE, -- Normalized 11-char ID prevents duplicate imports
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Consistency check: published episodes MUST have a published_at timestamp
    CONSTRAINT chk_published_timestamp CHECK (
        (publication_status = 'published' AND published_at IS NOT NULL) OR
        (publication_status != 'published')
    )
);


-- =============================================================================
-- 3. INGESTION & PIPELINE TABLES: JOBS, SEGMENTS, CHUNKS, EXTRACTION RUNS
-- =============================================================================

-- Table 3: processing_jobs
-- Tracks asynchronous ingestion and extraction lifecycle stages, retries, and errors.
CREATE TABLE IF NOT EXISTS processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id UUID REFERENCES episodes(id) ON DELETE SET NULL,
    youtube_url TEXT NOT NULL,
    youtube_video_id TEXT NOT NULL,
    status processing_job_status NOT NULL DEFAULT 'pending',
    current_stage processing_stage NOT NULL DEFAULT 'submission',
    retry_count INT NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retries INT NOT NULL DEFAULT 3 CHECK (max_retries >= 0),
    error_summary TEXT,
    error_details JSONB,
    stage_timings JSONB NOT NULL DEFAULT '{}'::jsonb, -- records started_at, completed_at, duration_ms
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Table 4: transcript_segments
-- Ground-truth transcript atom. Stores absolute millisecond offsets and speaker labels.
CREATE TABLE IF NOT EXISTS transcript_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    segment_index INT NOT NULL CHECK (segment_index >= 0),
    start_ms INT NOT NULL CHECK (start_ms >= 0),
    end_ms INT NOT NULL CHECK (end_ms >= start_ms),
    start_seconds NUMERIC(8,2) GENERATED ALWAYS AS (ROUND((start_ms / 1000.0)::numeric, 2)) STORED,
    speaker_label TEXT NOT NULL DEFAULT 'Speaker',
    language_code TEXT NOT NULL DEFAULT 'am',
    acquisition_method transcript_acquisition_method NOT NULL,
    text TEXT NOT NULL,
    confidence NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_episode_segment_index UNIQUE (episode_id, segment_index)
);

-- Table 5: transcript_chunks
-- Context-window chunks synthesized from contiguous segments for AI model processing.
CREATE TABLE IF NOT EXISTS transcript_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL CHECK (chunk_index >= 0),
    start_segment_index INT NOT NULL CHECK (start_segment_index >= 0),
    end_segment_index INT NOT NULL CHECK (end_segment_index >= start_segment_index),
    start_ms INT NOT NULL CHECK (start_ms >= 0),
    end_ms INT NOT NULL CHECK (end_ms >= start_ms),
    token_count_estimate INT CHECK (token_count_estimate IS NULL OR token_count_estimate > 0),
    chunk_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_episode_chunk_index UNIQUE (episode_id, chunk_index)
);

-- Table 6: extraction_runs
-- Versioned record of Gemini candidate extraction invocations for auditability and reproducibility.
CREATE TABLE IF NOT EXISTS extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    run_number INT NOT NULL DEFAULT 1 CHECK (run_number > 0),
    model_id TEXT NOT NULL, -- e.g. 'gemini-1.5-pro-002', 'gemini-2.0-flash'
    prompt_version TEXT NOT NULL, -- e.g. 'extraction_prompt_v1.2.0'
    raw_response_json JSONB,
    extracted_payload JSONB,
    validation_status TEXT NOT NULL CHECK (validation_status IN ('passed', 'failed', 'partial')),
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    tokens_prompt INT,
    tokens_completion INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_job_run_number UNIQUE (job_id, run_number)
);


-- =============================================================================
-- 4. STRUCTURED KNOWLEDGE TABLES: INSIGHTS, QUOTATIONS, EVIDENCE REFERENCES
-- =============================================================================

-- Table 7: insights
-- High-signal entrepreneurial insights, tactical takeaways, and practical actions.
CREATE TABLE IF NOT EXISTS insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_id TEXT UNIQUE, -- Preserves backward-compatibility with local fixtures (e.g. 'ins-101-1')
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    extraction_run_id UUID REFERENCES extraction_runs(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    takeaways TEXT[] NOT NULL DEFAULT '{}',
    practical_action TEXT,
    display_order INT NOT NULL DEFAULT 0,
    review_status editorial_review_status NOT NULL DEFAULT 'candidate',
    reviewed_by UUID,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 8: quotations
-- Original Amharic quotes with translations, derived timestamps, and speaker labels.
CREATE TABLE IF NOT EXISTS quotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_id TEXT UNIQUE, -- Preserves backward-compatibility with local fixtures (e.g. 'quote-101-1')
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    extraction_run_id UUID REFERENCES extraction_runs(id) ON DELETE SET NULL,
    segment_id UUID REFERENCES transcript_segments(id) ON DELETE SET NULL,
    amharic_quote TEXT NOT NULL,
    english_translation TEXT NOT NULL,
    speaker TEXT NOT NULL,
    timestamp_seconds INT NOT NULL CHECK (timestamp_seconds >= 0),
    context TEXT NOT NULL,
    display_order INT NOT NULL DEFAULT 0,
    review_status editorial_review_status NOT NULL DEFAULT 'candidate',
    reviewed_by UUID,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 9: insight_evidence
-- Direct traceability linking extracted insights to source transcript segments.
CREATE TABLE IF NOT EXISTS insight_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    insight_id UUID NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
    segment_id UUID NOT NULL REFERENCES transcript_segments(id) ON DELETE RESTRICT,
    relevance_score NUMERIC(4,3) CHECK (relevance_score IS NULL OR (relevance_score >= 0.0 AND relevance_score <= 1.0)),
    claim_quote_snippet TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_insight_segment UNIQUE (insight_id, segment_id)
);


-- =============================================================================
-- 5. PERFORMANCE INDEXES
-- =============================================================================

-- Video ID lookups for deduplication
CREATE INDEX IF NOT EXISTS idx_episodes_youtube_video_id ON episodes(youtube_video_id);

-- Public episode query indexing (published status and reverse chronological order)
CREATE INDEX IF NOT EXISTS idx_episodes_published ON episodes(publication_status, published_at DESC)
    WHERE publication_status = 'published';

-- Foreign key lookups
CREATE INDEX IF NOT EXISTS idx_episodes_guest_id ON episodes(guest_id);
CREATE INDEX IF NOT EXISTS idx_insights_episode_id ON insights(episode_id, review_status);
CREATE INDEX IF NOT EXISTS idx_quotations_episode_id ON quotations(episode_id, review_status);
CREATE INDEX IF NOT EXISTS idx_insight_evidence_insight_id ON insight_evidence(insight_id);
CREATE INDEX IF NOT EXISTS idx_insight_evidence_segment_id ON insight_evidence(segment_id);

-- Transcript segment range scanning
CREATE INDEX IF NOT EXISTS idx_transcript_segments_episode_lookup
    ON transcript_segments(episode_id, segment_index);
CREATE INDEX IF NOT EXISTS idx_transcript_segments_time
    ON transcript_segments(episode_id, start_ms, end_ms);

-- Pipeline job queue polling
CREATE INDEX IF NOT EXISTS idx_processing_jobs_queue ON processing_jobs(status, current_stage);


-- =============================================================================
-- 6. TRANSACTIONAL PUBLICATION FUNCTION (ATOMIC DRAFT -> PUBLISHED)
-- =============================================================================

-- Atomically validates and publishes an episode, making it visible to Flutter clients.
-- Includes caller authorization checks, configurable quotation requirements, and
-- evidence-backing verification.
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
    v_episode RECORD;
    v_verified_insights_count INT;
    v_verified_quotations_count INT;
    v_unsupported_insights_count INT;
    v_target_min_quotations INT;
    v_effective_min_insights INT;
    v_result JSONB;
BEGIN
    -- 1. Authorization check
    -- Allow execution ONLY if current_user is superuser/service_role/postgres OR JWT has admin claims
    IF current_user IN ('postgres', 'service_role') THEN
        v_is_authorized := TRUE;
    ELSE
        IF (auth.jwt() ->> 'role') = 'admin' OR 
           (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR
           (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin' THEN
            v_is_authorized := TRUE;
        END IF;
    END IF;

    IF NOT v_is_authorized THEN
        RAISE EXCEPTION 'Access denied: only administrators or service_role can publish episodes.';
    END IF;

    -- 2. Lock and retrieve episode record
    SELECT * INTO v_episode
    FROM episodes
    WHERE id = p_episode_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Episode % not found.', p_episode_id;
    END IF;

    -- 3. Idempotent check: if already published, return safe status without re-running checks
    IF v_episode.publication_status = 'published' THEN
        RETURN jsonb_build_object(
            'success', true,
            'message', 'Episode is already published',
            'episode_id', p_episode_id,
            'published_at', v_episode.published_at
        );
    END IF;

    -- 4. Verify minimum verified insights count (Meri foundation requires >= 1 insight)
    v_effective_min_insights := GREATEST(p_min_insights, 1);

    SELECT count(*) INTO v_verified_insights_count
    FROM insights
    WHERE episode_id = p_episode_id AND review_status = 'verified';

    IF v_verified_insights_count < v_effective_min_insights THEN
        RAISE EXCEPTION 'Publication rejected: episode has % verified insight(s), but at least % is required.',
            v_verified_insights_count, v_effective_min_insights;
    END IF;

    -- 5. Verify quotations according to editorial policy configuration
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

    -- 6. Verify evidence references: every verified insight MUST have at least one supporting transcript segment
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

    -- 7. Atomically transition state to published
    UPDATE episodes
    SET publication_status = 'published',
        published_at = COALESCE(published_at, now()),
        updated_at = now()
    WHERE id = p_episode_id;

    -- 8. Return audit response
    v_result := jsonb_build_object(
        'success', true,
        'episode_id', p_episode_id,
        'title', v_episode.title,
        'status', 'published',
        'verified_insights', v_verified_insights_count,
        'verified_quotations', v_verified_quotations_count,
        'published_by', p_admin_user_id,
        'published_at', now()
    );

    RETURN v_result;
END;
$$;


-- =============================================================================
-- 7. GRANTS & ACCESS CONTROL (ENABLING RLS ALONE IS NOT SUFFICIENT)
-- =============================================================================

-- Schema usage
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

-- Public tables: read-only for anon and authenticated clients
GRANT SELECT ON episodes, guests, insights, quotations TO anon, authenticated;

-- Service role: full administrative privileges
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA public TO service_role;

-- Internal pipeline tables: strictly private (explicit revocation from public/anon)
REVOKE ALL ON processing_jobs, transcript_segments, transcript_chunks, extraction_runs, insight_evidence FROM anon, PUBLIC;

-- Publication function permissions
REVOKE ALL ON FUNCTION publish_episode(UUID, UUID, INT, BOOLEAN, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION publish_episode(UUID, UUID, INT, BOOLEAN, INT) FROM anon;
GRANT EXECUTE ON FUNCTION publish_episode(UUID, UUID, INT, BOOLEAN, INT) TO authenticated, service_role;


-- =============================================================================
-- 8. ROW LEVEL SECURITY (RLS) POLICIES
-- =============================================================================

ALTER TABLE guests ENABLE ROW LEVEL SECURITY;
ALTER TABLE episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE processing_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE extraction_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE quotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE insight_evidence ENABLE ROW LEVEL SECURITY;

-- -----------------------------------------------------------------------------
-- Public / Anon Read-Only Policies: Only published and verified data is accessible
-- -----------------------------------------------------------------------------

-- Public can ONLY view published episodes
CREATE POLICY "Public read published episodes"
    ON episodes FOR SELECT
    TO anon, authenticated
    USING (publication_status = 'published' AND published_at <= now());

-- Public can view guests linked to at least one published episode
CREATE POLICY "Public read published guests"
    ON guests FOR SELECT
    TO anon, authenticated
    USING (
        EXISTS (
            SELECT 1 FROM episodes e
            WHERE e.guest_id = guests.id
              AND e.publication_status = 'published'
              AND e.published_at <= now()
        )
    );

-- Public can ONLY view verified insights belonging to published episodes
CREATE POLICY "Public read published verified insights"
    ON insights FOR SELECT
    TO anon, authenticated
    USING (
        review_status = 'verified' AND
        EXISTS (
            SELECT 1 FROM episodes e
            WHERE e.id = insights.episode_id
              AND e.publication_status = 'published'
              AND e.published_at <= now()
        )
    );

-- Public can ONLY view verified quotations belonging to published episodes
CREATE POLICY "Public read published verified quotations"
    ON quotations FOR SELECT
    TO anon, authenticated
    USING (
        review_status = 'verified' AND
        EXISTS (
            SELECT 1 FROM episodes e
            WHERE e.id = quotations.episode_id
              AND e.publication_status = 'published'
              AND e.published_at <= now()
        )
    );

-- -----------------------------------------------------------------------------
-- Service-Role Policies: Full access in all environments
-- -----------------------------------------------------------------------------

CREATE POLICY "Service role full access episodes" ON episodes FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access guests" ON guests FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access processing_jobs" ON processing_jobs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access transcript_segments" ON transcript_segments FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access transcript_chunks" ON transcript_chunks FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access extraction_runs" ON extraction_runs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access insights" ON insights FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access quotations" ON quotations FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access insight_evidence" ON insight_evidence FOR ALL TO service_role USING (true) WITH CHECK (true);

-- -----------------------------------------------------------------------------
-- Admin Policies: For authenticated administrators
-- -----------------------------------------------------------------------------

CREATE POLICY "Admin full access processing_jobs"
    ON processing_jobs FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

CREATE POLICY "Admin full access transcript_segments"
    ON transcript_segments FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

CREATE POLICY "Admin full access transcript_chunks"
    ON transcript_chunks FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

CREATE POLICY "Admin full access extraction_runs"
    ON extraction_runs FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

CREATE POLICY "Admin full access insight_evidence"
    ON insight_evidence FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

CREATE POLICY "Admin full access episodes"
    ON episodes FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

CREATE POLICY "Admin full access guests"
    ON guests FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

CREATE POLICY "Admin full access insights"
    ON insights FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

CREATE POLICY "Admin full access quotations"
    ON quotations FOR ALL
    TO authenticated
    USING ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
    WITH CHECK ((auth.jwt() ->> 'role') = 'admin' OR (auth.jwt() -> 'app_metadata' ->> 'is_admin')::boolean = true OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');
