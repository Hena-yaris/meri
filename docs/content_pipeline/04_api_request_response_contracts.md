# API Request & Response Contracts

## 1. Overview & Security Boundaries

The content pipeline exposes two strictly separated API surfaces:
1. **Admin / Ingestion API (`/api/v1/admin/*`)**:
   - Requires Supabase Admin JWT or Service Role Bearer token (`Authorization: Bearer <ADMIN_JWT>`).
   - Manages ingestion jobs, raw transcript overrides, pipeline retries, candidate drafts, and atomic publication.
2. **Public Mobile Client API (`/api/v1/*`)**:
   - Accessible via Supabase Anonymous key (`apikey: <SUPABASE_ANON_KEY>`).
   - Strictly read-only.
   - Enforced by PostgreSQL Row-Level Security: returns only records where `publication_status = 'published'` and `published_at <= now()`.
   - Never exposes unreviewed candidate drafts, jobs, segments, or evidence links to mobile clients.

---

## 2. Admin & Ingestion Endpoints

### 2.1 Create Ingestion Job
- **Route**: `POST /api/v1/admin/jobs`
- **Description**: Submits a YouTube interview recording for automated transcription and knowledge extraction.

#### Request Body
```json
{
  "youtubeUrl": "https://www.youtube.com/watch?v=sample-ep101",
  "episodeNumber": 101,
  "podcastTitle": "Meri Business Series",
  "priority": "normal",
  "options": {
    "forceAudioTranscribe": false,
    "language": "am"
  }
}
```

#### Response: `201 Created`
```json
{
  "jobId": "e5b8d2a1-3c4f-4d6b-8a2c-1f5e8b4a2c0d",
  "episodeId": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a",
  "youtubeVideoId": "sample-ep101",
  "status": "pending",
  "currentStage": "submission",
  "createdAt": "2026-10-20T10:00:00.000Z"
}
```

#### Error: `409 Conflict` (Duplicate Import)
```json
{
  "error": "Conflict",
  "message": "A job or episode with YouTube video ID 'sample-ep101' already exists.",
  "existingEpisodeId": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a"
}
```

---

### 2.2 Read Job Status
- **Route**: `GET /api/v1/admin/jobs/{job_id}`
- **Description**: Returns detailed execution telemetry, current processing stage, error history, and stage durations.

#### Response: `200 OK`
```json
{
  "jobId": "e5b8d2a1-3c4f-4d6b-8a2c-1f5e8b4a2c0d",
  "episodeId": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a",
  "youtubeVideoId": "sample-ep101",
  "status": "processing",
  "currentStage": "ai_extraction",
  "retryCount": 0,
  "maxRetries": 3,
  "errorSummary": null,
  "stageTimings": {
    "submission": { "startedAt": "2026-10-20T10:00:00.000Z", "completedAt": "2026-10-20T10:00:01.000Z", "durationMs": 1000 },
    "metadata_retrieval": { "startedAt": "2026-10-20T10:00:01.000Z", "completedAt": "2026-10-20T10:00:03.500Z", "durationMs": 2500 },
    "transcript_acquisition": { "startedAt": "2026-10-20T10:00:03.500Z", "completedAt": "2026-10-20T10:00:15.000Z", "durationMs": 11500 },
    "transcript_normalization": { "startedAt": "2026-10-20T10:00:15.000Z", "completedAt": "2026-10-20T10:00:17.200Z", "durationMs": 2200 },
    "chunking": { "startedAt": "2026-10-20T10:00:17.200Z", "completedAt": "2026-10-20T10:00:18.000Z", "durationMs": 800 },
    "ai_extraction": { "startedAt": "2026-10-20T10:00:18.000Z", "completedAt": null, "durationMs": null }
  },
  "createdAt": "2026-10-20T10:00:00.000Z",
  "updatedAt": "2026-10-20T10:00:18.000Z"
}
```

---

### 2.3 Submit / Override Transcript
- **Route**: `POST /api/v1/admin/jobs/{job_id}/transcript`
- **Description**: Manually uploads an authoritative transcript or SRT/WebVTT file to bypass or repair caption scraping.

#### Request Body
```json
{
  "format": "segments_json",
  "language": "am",
  "acquisitionMethod": "manual_upload",
  "segments": [
    {
      "segmentIndex": 0,
      "startMs": 0,
      "endMs": 14200,
      "speakerLabel": "Dawit Tadesse",
      "text": "እንኳን ደህና መጣችሁ። ዛሬ በዋናነት የምናወራው ስለ ኢትዮጵያ የቀዝቃዛ ሰንሰለት ሎጂስቲክስ ይሆናል።"
    }
  ]
}
```

#### Response: `200 OK`
```json
{
  "success": true,
  "jobId": "e5b8d2a1-3c4f-4d6b-8a2c-1f5e8b4a2c0d",
  "segmentsInserted": 142,
  "resumedAtStage": "transcript_normalization"
}
```

---

### 2.4 Retry Failed Stage
- **Route**: `POST /api/v1/admin/jobs/{job_id}/retry`
- **Description**: Re-triggers execution of a failed or stalled stage.

#### Request Body
```json
{
  "targetStage": "ai_extraction",
  "resetRetryCount": true
}
```

#### Response: `200 OK`
```json
{
  "success": true,
  "jobId": "e5b8d2a1-3c4f-4d6b-8a2c-1f5e8b4a2c0d",
  "status": "processing",
  "retryingStage": "ai_extraction"
}
```

---

### 2.5 Read Candidate Draft
- **Route**: `GET /api/v1/admin/episodes/{episode_id}/draft`
- **Description**: Retrieves candidate insights, quotes, and evidence references for human editorial review.

#### Response: `200 OK`
```json
{
  "episode": {
    "id": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a",
    "title": "Scaling Cold Chain Logistics Across Agricultural Corridors",
    "publicationStatus": "in_review",
    "guest": {
      "name": "Dawit Tadesse",
      "company": "Nile Cold Chain Logistics"
    }
  },
  "candidateInsights": [
    {
      "id": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
      "title": "Decoupling Fleet Ownership from Logistics Orchestration",
      "category": "Operations",
      "reviewStatus": "candidate",
      "evidenceReferences": [
        {
          "segmentIndex": 34,
          "startMs": 340000,
          "snippet": "የራሳችንን መኪና ከመግዛት ይልቅ..."
        }
      ]
    }
  ],
  "candidateQuotations": [
    {
      "id": "4c5d6e7f-8a9b-0c1d-2e3f-4a5b6c7d8e9f",
      "amharicQuote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን...",
      "timestampSeconds": 1420,
      "reviewStatus": "candidate"
    }
  ]
}
```

---

### 2.6 Approve and Publish Episode (Atomic RPC)
- **Route**: `POST /api/v1/admin/episodes/{episode_id}/publish`
- **Description**: Executes the `publish_episode` PostgreSQL function in a single transaction. Validates verified counts and evidence links, then transitions status to `published`.

#### Request Body
```json
{
  "publishedAt": "2026-10-20T10:30:00.000Z"
}
```

#### Response: `200 OK`
```json
{
  "success": true,
  "episodeId": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a",
  "title": "Scaling Cold Chain Logistics Across Agricultural Corridors",
  "status": "published",
  "verifiedInsights": 2,
  "verifiedQuotations": 2,
  "publishedAt": "2026-10-20T10:30:00.000Z"
}
```

---

## 3. Public Mobile Client Endpoints

### 3.1 List Published Episodes
- **Route**: `GET /api/v1/episodes?limit=20&offset=0&category=Operations`
- **Description**: Paginated feed of verified, published episodes.

#### Response: `200 OK`
```json
{
  "data": [
    {
      "id": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a",
      "legacyId": "ep-101",
      "title": "Scaling Cold Chain Logistics Across Agricultural Corridors",
      "podcastTitle": "Meri Business Series",
      "episodeNumber": 101,
      "durationMinutes": 74,
      "publishedAt": "2026-09-12T08:00:00.000Z",
      "summary": "An in-depth exploration into the structural obstacles of agricultural freight in Ethiopia...",
      "isFeatured": true,
      "tags": ["Logistics", "Agritech", "Operations", "Supply Chain"],
      "audioUrl": "https://sample-audio.meri.et/ep101.mp3",
      "coverImageUrl": null,
      "youtubeUrl": "https://www.youtube.com/watch?v=sample-ep101",
      "guest": {
        "id": "3b4c5d6e-7f8a-9b0c-1d2e-3f4a5b6c7d8e",
        "name": "Dawit Tadesse",
        "title": "Founder & Managing Director",
        "company": "Nile Cold Chain Logistics",
        "industry": "Agricultural Logistics & Cold Storage",
        "bio": "Mechanical engineer turned logistics entrepreneur..."
      }
    }
  ],
  "pagination": {
    "total": 1,
    "limit": 20,
    "offset": 0
  }
}
```

---

### 3.2 Read Published Episode Details
- **Route**: `GET /api/v1/episodes/{id_or_slug}`
- **Description**: Returns full episode details with verified insights and verified quotations.

#### Response: `200 OK`
Maps directly to Flutter `Episode.fromJson(...)`.
```json
{
  "id": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a",
  "legacyId": "ep-101",
  "title": "Scaling Cold Chain Logistics Across Agricultural Corridors",
  "podcastTitle": "Meri Business Series",
  "episodeNumber": 101,
  "durationMinutes": 74,
  "publishedAt": "2026-09-12T08:00:00.000Z",
  "summary": "An in-depth exploration into the structural obstacles of agricultural freight in Ethiopia...",
  "isFeatured": true,
  "tags": ["Logistics", "Agritech", "Operations", "Supply Chain"],
  "audioUrl": "https://sample-audio.meri.et/ep101.mp3",
  "coverImageUrl": null,
  "youtubeUrl": "https://www.youtube.com/watch?v=sample-ep101",
  "guest": {
    "id": "3b4c5d6e-7f8a-9b0c-1d2e-3f4a5b6c7d8e",
    "name": "Dawit Tadesse",
    "title": "Founder & Managing Director",
    "company": "Nile Cold Chain Logistics",
    "industry": "Agricultural Logistics & Cold Storage",
    "bio": "Mechanical engineer turned logistics entrepreneur...",
    "avatarUrl": null
  },
  "insights": [
    {
      "id": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
      "episodeId": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a",
      "title": "Decoupling Fleet Ownership from Logistics Orchestration",
      "category": "Operations",
      "summary": "Purchasing heavy transport vehicles burns seed capital too early...",
      "takeaways": [
        "Heavy asset purchases tie down working capital needed for quality control.",
        "Retrofitting independent trucker fleets cuts CapEx by 60%."
      ],
      "practicalAction": "Audit current asset depreciation against subcontracting models."
    }
  ],
  "quotations": [
    {
      "id": "4c5d6e7f-8a9b-0c1d-2e3f-4a5b6c7d8e9f",
      "episodeId": "7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a",
      "amharicQuote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን በመንገድ ላይ የሚባክነውን ምርት ዋጋ በሰከንድ ማስላት ነው።",
      "englishTranslation": "The greatest test in logistics isn't buying trucks; it's calculating by the second the value of harvest perishing on the highway.",
      "speaker": "Dawit Tadesse",
      "timestampSeconds": 1420,
      "context": "Explaining why telemetry monitoring matters more than fleet volume during seasonal harvest peaks."
    }
  ]
}
```
