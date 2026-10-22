# Flutter Model Compatibility & Migration Architecture

## 1. Domain Model Parity & Field Mapping

The existing Flutter application uses strongly-typed domain models located in:
`lib/features/business_knowledge/domain/models/`:
- [`episode.dart`](../../lib/features/business_knowledge/domain/models/episode.dart)
- [`guest.dart`](../../lib/features/business_knowledge/domain/models/guest.dart)
- [`insight.dart`](../../lib/features/business_knowledge/domain/models/insight.dart)
- [`quotation.dart`](../../lib/features/business_knowledge/domain/models/quotation.dart)

The proposed Supabase PostgreSQL schema and API serialization map **100% cleanly** into these models without requiring breaking constructor changes or schema mutations on the mobile client.

### Field-by-Field Mapping Matrix

#### Table: `episodes` -> `Episode` Model
| PostgreSQL Column | API JSON Key | Dart `Episode` Field | Dart Type | Compatibility Notes |
| :--- | :--- | :--- | :--- | :--- |
| `id` (UUID) | `id` | `id` | `String` | Dart `String` accepts standard UUID v4 strings seamlessly. |
| `legacy_id` (TEXT) | `legacyId` | (Ignored / optional alias) | `String?` | Allows resolving historical fixture IDs (`ep-101`). |
| `title` | `title` | `title` | `String` | Direct match. |
| `podcast_title` | `podcastTitle` | `podcastTitle` | `String` | Direct match (defaults to `'Meri Podcast'`). |
| `episode_number` | `episodeNumber` | `episodeNumber` | `int` | Direct match. Used for display (#101) and sorting. |
| `duration_minutes` | `durationMinutes` | `durationMinutes` | `int` | Direct match. Powers `formattedDuration` (`1h 14m`). |
| `published_at` | `publishedAt` | `publishedAt` | `DateTime` | Serialized as ISO-8601 string; parsed via `DateTime.parse()`. |
| `summary` | `summary` | `summary` | `String` | Direct match. |
| `is_featured` | `isFeatured` | `isFeatured` | `bool` | Direct match. Defaults to `false`. |
| `tags` | `tags` | `tags` | `List<String>` | Direct match. |
| `audio_url` | `audioUrl` | `audioUrl` | `String?` | Direct match. |
| `cover_image_url` | `coverImageUrl` | `coverImageUrl` | `String?` | Direct match. |
| `youtube_url` | `youtubeUrl` | `youtubeUrl` | `String?` | Validated YouTube URL parsed by `YouTubeUrlHelper`. |
| JOIN `guests` | `guest` | `guest` | `Guest` | Nested object parsed via `Guest.fromJson()`. |
| JOIN `insights` | `insights` | `insights` | `List<Insight>` | Nested list parsed via `Insight.fromJson()`. |
| JOIN `quotations`| `quotations`| `quotations`| `List<Quotation>`| Nested list parsed via `Quotation.fromJson()`. |

#### Table: `guests` -> `Guest` Model
| PostgreSQL Column | API JSON Key | Dart `Guest` Field | Dart Type | Compatibility Notes |
| :--- | :--- | :--- | :--- | :--- |
| `id` (UUID) | `id` | `id` | `String` | Direct match. |
| `name` | `name` | `name` | `String` | Direct match. |
| `title` | `title` | `title` | `String` | Direct match. |
| `company` | `company` | `company` | `String` | Direct match. |
| `bio` | `bio` | `bio` | `String` | Direct match. |
| `avatar_url` | `avatarUrl` | `avatarUrl` | `String?` | Direct match. |
| `industry` | `industry` | `industry` | `String?` | Direct match. |

#### Table: `insights` -> `Insight` Model
| PostgreSQL Column | API JSON Key | Dart `Insight` Field | Dart Type | Compatibility Notes |
| :--- | :--- | :--- | :--- | :--- |
| `id` (UUID) | `id` | `id` | `String` | Direct match. |
| `episode_id` (UUID) | `episodeId` | `episodeId` | `String` | Foreign key matching `Episode.id`. |
| `title` | `title` | `title` | `String` | Direct match. |
| `summary` | `summary` | `summary` | `String` | Direct match. |
| `category` | `category` | `category` | `String` | Direct match. |
| `takeaways` | `takeaways` | `takeaways` | `List<String>` | Direct match. |
| `practical_action` | `practicalAction` | `practicalAction` | `String?` | Direct match. |

#### Table: `quotations` -> `Quotation` Model
| PostgreSQL Column | API JSON Key | Dart `Quotation` Field | Dart Type | Compatibility Notes |
| :--- | :--- | :--- | :--- | :--- |
| `id` (UUID) | `id` | `id` | `String` | Direct match. |
| `episode_id` (UUID) | `episodeId` | `episodeId` | `String` | Foreign key matching `Episode.id`. |
| `amharic_quote` | `amharicQuote` | `amharicQuote` | `String` | Direct match. Preserves authentic Amharic characters. |
| `english_translation` | `englishTranslation` | `englishTranslation` | `String` | Direct match. |
| `speaker` | `speaker` | `speaker` | `String` | Direct match. |
| `timestamp_seconds`| `timestampSeconds`| `timestampSeconds`| `int` | Direct match. Powers `formattedTimestamp` (e.g. `23:40`). |
| `context` | `context` | `context` | `String` | Direct match. |

---

## 2. UUID vs. Fixture Legacy IDs & Bookmark Migration

### 2.1 The Challenge
The bundled JSON fixture (`assets/data/sample_episodes.json`) uses semantic string IDs:
- Episodes: `"ep-101"`, `"ep-102"`, `"ep-103"`
- Guests: `"guest-dawit-t"`, `"guest-bethlehem-a"`
- Insights: `"ins-101-1"`, `"ins-101-2"`
- Quotations: `"quote-101-1"`, `"quote-101-2"`

Users on earlier builds have saved these IDs into `SharedPreferences` via:
`SharedPreferencesBookmarksDataSource` under the key:
`'meri_bookmarked_episode_ids'`.

The Supabase backend uses standard RFC-4122 UUID v4 primary keys (e.g. `'7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a'`).

### 2.2 Backward-Compatible Resolution Strategy
1. **Database Schema Support**:
   The `episodes` table includes a `legacy_id TEXT UNIQUE` column holding the fixture ID (e.g. `'ep-101'`).
2. **Dual-Key Lookup in Repository**:
   When checking bookmark status or retrieving episodes by ID:
   ```dart
   bool isBookmarked(Episode episode, Set<String> bookmarkedIds) {
     return bookmarkedIds.contains(episode.id) || 
            (episode.legacyId != null && bookmarkedIds.contains(episode.legacyId));
   }
   ```
3. **One-Time Transparent Storage Migration**:
   When the remote repository initializes, any stored bookmark ID that matches a `legacy_id` is updated in `SharedPreferences` to the corresponding `uuid` without user disruption:
   ```dart
   Future<void> migrateLegacyBookmarkIds(Map<String, String> legacyToUuidMap) async {
     final stored = await bookmarksDataSource.loadBookmarkedIds();
     final updated = stored.map((id) => legacyToUuidMap[id] ?? id).toSet();
     if (updated != stored) {
       await bookmarksDataSource.saveBookmarkedIds(updated);
     }
   }
   ```

---

## 3. YouTube URL Helper & Timestamp Behavior

The existing utility `YouTubeUrlHelper` ([`lib/core/utils/youtube_url_helper.dart`](../../lib/core/utils/youtube_url_helper.dart)) handles:
1. Validating YouTube links (standard `watch?v=`, short `youtu.be/`, `embed/`, and `shorts/`).
2. Appending timestamps via query parameter: `?t=1420s`.
3. Opening the external YouTube app via `url_launcher`.

### Backend Integration
- In `quotations`, `timestamp_seconds` is stored as an integer derived from `transcript_segments.start_ms / 1000`.
- In `EpisodeDetailScreen`, tapping a quote calls:
  ```dart
  YouTubeUrlHelper.launchYouTubeTimestamp(
    baseUrl: episode.youtubeUrl,
    timestampSeconds: quotation.timestampSeconds,
  );
  ```
Because the backend contract stores `timestamp_seconds` as an integer matching the transcript start time, timestamp deep-linking works with zero modifications to the UI or helper logic!

---

## 4. Local JSON Fixtures as Development Fallback

The current repository uses `LocalJsonDataSource` ([`lib/features/business_knowledge/data/datasources/local_json_data_source.dart`](../../lib/features/business_knowledge/data/datasources/local_json_data_source.dart)).

In Milestone 4A, **we do not replace the local repository**.
The decoupled Riverpod provider architecture in `lib/features/business_knowledge/data/providers.dart` defines:
```dart
final knowledgeRepositoryProvider = Provider<KnowledgeRepository>((ref) {
  final dataSource = ref.watch(localJsonDataSourceProvider);
  return LocalKnowledgeRepository(dataSource: dataSource);
});
```

When remote Supabase integration is connected in a future milestone, `RemoteKnowledgeRepository` will implement the exact same `KnowledgeRepository` interface. If network connectivity is unavailable, the repository can seamlessly fall back to `LocalJsonDataSource`, ensuring reliable offline-first operation and effortless local development.
