# AI Extraction Contract & Dual Validation Doctrine

## 1. Overview & Objective

The AI extraction layer processes chunked transcript text to generate candidate business intelligence objects:
- **Episode Summary**: Brief teaser, comprehensive analytical breakdown, primary themes.
- **Guest Profile**: Verified entrepreneur identity, title, enterprise, professional background, and journey summary.
- **Journey Milestones**: Chronological business phases with strategic decisions, strictly backed by segment citations.
- **Structured Insights**: Domain-categorized lessons, analytical summaries, 1–5 bulleted takeaways, and concrete operational directives.
- **Original Quotations**: Authentic Amharic quotes, English translations, speaker attribution, derived absolute timestamps, and context.
- **Search Tags**: Curated taxonomy tags.

The canonical JSON Schema is maintained at:
[`backend/schemas/gemini_extraction_schema.v1.json`](../../backend/schemas/gemini_extraction_schema.v1.json).

---

## 2. The Dual Validation Doctrine

A valid JSON output from Gemini does **not** prove that the extracted claims are factual, accurate, or attributable to the guest. Meri enforces a two-tier validation barrier before any candidate extraction reaches human editorial review:

```
                  Gemini Raw Response
                           │
                           ▼
          ┌──────────────────────────────────┐
          │  Phase 1: Syntactic Validation   │
          │    (JSON Schema Draft-07)        │
          └────────────────┬─────────────────┘
                           │ Passed
                           ▼
          ┌──────────────────────────────────┐
          │  Phase 2: Semantic Evidence Check│
          │    (Segment Grounding Engine)    │
          └────────────────┬─────────────────┘
                           │ Passed
                           ▼
                 Passed to Editorial Review
```

### Phase 1 — Syntactic Schema Validation
Ensures structural and data-type compliance:
- `schema_version`: Must equal `"1.0.0"`.
- Required top-level keys must all be present.
- `category`: Must strictly match one of the 9 defined business domain enums:
  `Operations`, `Fintech`, `Technology & Infrastructure`, `Leadership & Culture`, `Sales & Marketing`, `Finance & Capital`, `Legal & Regulatory`, `Product Strategy`, `Export & Trade`.
- String bounds: Prevents truncated outputs or verbose hallucinations (`title`: 5–140 chars; `summary`: min 30 chars; `practical_action`: min 15 chars).
- Array boundaries: `takeaways` (1–6 items); `suggested_tags` (2–10 items).

### Phase 2 — Semantic Evidence Reference Validation
Validates claims against the immutable transcript ground truth:
1. **Segment Index Existence**:
   Every index listed in `evidence_segment_indices` and `source_segment_index` must exist in `transcript_segments` for this episode. If a model cites `segment_index = 84` but the episode only has 60 segments, extraction fails immediately.
2. **Deterministic Timestamp Boundary Check**:
   The model must not invent timestamps.
   The validator computes:
   $$\text{expected\_seconds} = \lfloor \text{transcript\_segments[source\_segment\_index].start\_ms} / 1000 \rfloor$$
   $$\text{max\_seconds} = \lceil \text{transcript\_segments[source\_segment\_index].end\_ms} / 1000 \rceil$$
   The provided `timestamp_seconds` must fall within $[\text{expected\_seconds} - 2, \text{max\_seconds} + 2]$.
3. **Quotation Text Verification (Fuzzy Token Overlap)**:
   The Amharic string in `amharic_quote` is tokenized and compared against the text of the referenced `transcript_segment` (plus adjacent segments $\pm 1$ to allow for sentence boundary splits).
   Minimum token overlap threshold: $\ge 80\%$.
   If the quote text does not appear in the transcript, the quote candidate is rejected as an ungrounded paraphrase or hallucination.

---

## 3. Metadata Tracking & Reproducibility

Every invocation of the AI model creates an immutable row in the `extraction_runs` table:

```sql
CREATE TABLE extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    run_number INT NOT NULL DEFAULT 1,
    model_id TEXT NOT NULL,         -- e.g. 'gemini-1.5-pro-002'
    prompt_version TEXT NOT NULL,   -- e.g. 'v1.2.0'
    raw_response_json JSONB,        -- Exact unedited model text/json
    extracted_payload JSONB,        -- Validated candidate payload
    validation_status TEXT NOT NULL,-- 'passed', 'failed', 'partial'
    validation_errors JSONB,        -- Detailed list of any schema or grounding errors
    tokens_prompt INT,
    tokens_completion INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Why this is critical:
- **Prompt Evolution**: If a prompt is updated, historical extractions can be compared against new runs using the same transcript chunks.
- **Model Drift Detection**: If a newer Gemini model version changes its summarization behavior or hallucination rate, historical `extraction_runs` provide regression benchmarks.
- **Audit Trails**: Editors can view the exact prompt version and raw model output that generated any specific insight or quotation.

---

## 4. Prompt Engineering Directives for Gemini

When constructing the prompt for Gemini, the worker enforces the following system instructions:

1. **Strict Context Adherence**: Only use facts, milestones, numbers, and quotations explicitly stated in the provided transcript segments.
2. **Direct Amharic Quotes**: Always extract quotes in their original spoken Amharic script. Provide an idiomatic, executive-ready English translation.
3. **No Temporal Hallucination**: Copy the start timestamp directly from the metadata of the citing segment. Never estimate or guess when a quote was spoken.
4. **Action-Oriented Insights**: Avoid passive summaries. Frame practical actions as operational imperatives for founders and managers.
