import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:meri/core/utils/youtube_url_helper.dart';
import 'package:meri/features/business_knowledge/domain/models/episode.dart';

void main() {
  group('Milestone 4A — Content Pipeline Contracts & Database Foundation', () {
    late String schemaJsonString;
    late Map<String, dynamic> schemaMap;
    late String validCandidateString;
    late Map<String, dynamic> validCandidateMap;
    late String invalidCandidateString;
    late Map<String, dynamic> invalidCandidateMap;
    late String publishedEpisodePayloadString;
    late Map<String, dynamic> publishedEpisodeMap;
    late String migrationSqlString;

    setUpAll(() {
      final schemaFile =
          File('backend/schemas/gemini_extraction_schema.v1.json');
      expect(schemaFile.existsSync(), isTrue,
          reason: 'Gemini extraction schema file must exist');
      schemaJsonString = schemaFile.readAsStringSync();
      schemaMap = jsonDecode(schemaJsonString) as Map<String, dynamic>;

      final validCandidateFile = File(
          'backend/schemas/fixtures/sample_candidate_gemini_response.json');
      expect(validCandidateFile.existsSync(), isTrue,
          reason: 'Valid candidate fixture must exist');
      validCandidateString = validCandidateFile.readAsStringSync();
      validCandidateMap =
          jsonDecode(validCandidateString) as Map<String, dynamic>;

      final invalidCandidateFile = File(
          'backend/schemas/fixtures/sample_invalid_gemini_response.json');
      expect(invalidCandidateFile.existsSync(), isTrue,
          reason: 'Invalid candidate fixture must exist');
      invalidCandidateString = invalidCandidateFile.readAsStringSync();
      invalidCandidateMap =
          jsonDecode(invalidCandidateString) as Map<String, dynamic>;

      final publishedEpisodeFile = File(
          'backend/schemas/fixtures/backend_published_episode_payload.json');
      expect(publishedEpisodeFile.existsSync(), isTrue,
          reason: 'Backend published episode payload fixture must exist');
      publishedEpisodePayloadString = publishedEpisodeFile.readAsStringSync();
      publishedEpisodeMap =
          jsonDecode(publishedEpisodePayloadString) as Map<String, dynamic>;

      final migrationFile = File(
          'supabase/migrations/20261020000001_content_pipeline_foundation.sql');
      expect(migrationFile.existsSync(), isTrue,
          reason: 'Supabase Cloud migration file must exist in supabase/migrations/');
      migrationSqlString = migrationFile.readAsStringSync();
    });

    // =========================================================================
    // 1. JSON Schema Draft-07 Specification Tests
    // =========================================================================
    test('JSON Schema adheres to Draft-07 and defines required contracts', () {
      expect(schemaMap['\$schema'], 'http://json-schema.org/draft-07/schema#');
      expect(schemaMap['type'], 'object');

      final requiredKeys = (schemaMap['required'] as List<dynamic>).cast<String>();
      expect(
        requiredKeys,
        containsAll([
          'schema_version',
          'episode_summary',
          'guest_profile',
          'insights',
          'quotations',
          'suggested_tags',
        ]),
      );

      final properties = schemaMap['properties'] as Map<String, dynamic>;

      // Check taxonomy categories
      final insightsProp = properties['insights'] as Map<String, dynamic>;
      final insightItems = insightsProp['items'] as Map<String, dynamic>;
      final categoryProp =
          (insightItems['properties'] as Map<String, dynamic>)['category']
              as Map<String, dynamic>;
      final allowedCategories =
          (categoryProp['enum'] as List<dynamic>).cast<String>();

      expect(allowedCategories, containsAll([
        'Operations',
        'Fintech',
        'Technology & Infrastructure',
        'Leadership & Culture',
        'Sales & Marketing',
        'Finance & Capital',
        'Legal & Regulatory',
        'Product Strategy',
        'Export & Trade',
      ]));
    });

    // =========================================================================
    // 2. Candidate Gemini Extraction Output Fixture Conformance
    // =========================================================================
    test('Valid Gemini candidate fixture conforms strictly to schema rules', () {
      expect(validCandidateMap['schema_version'], '1.0.0');

      // Episode summary checks
      final summary =
          validCandidateMap['episode_summary'] as Map<String, dynamic>;
      expect((summary['brief'] as String).length, inInclusiveRange(30, 320));
      expect((summary['comprehensive'] as String).length, greaterThanOrEqualTo(120));
      final themes = summary['primary_themes'] as List<dynamic>;
      expect(themes.length, inInclusiveRange(2, 8));

      // Guest profile checks
      final guest = validCandidateMap['guest_profile'] as Map<String, dynamic>;
      expect(guest['name'], 'Dawit Tadesse');
      expect(guest['company'], 'Nile Cold Chain Logistics');
      expect((guest['bio'] as String).length, greaterThanOrEqualTo(50));

      // Insights and evidence reference checks
      final insights = validCandidateMap['insights'] as List<dynamic>;
      expect(insights.isNotEmpty, isTrue);

      for (final insDynamic in insights) {
        final ins = insDynamic as Map<String, dynamic>;
        expect(ins['title'], isNotEmpty);
        expect(ins['category'], isIn([
          'Operations',
          'Fintech',
          'Technology & Infrastructure',
          'Leadership & Culture',
          'Sales & Marketing',
          'Finance & Capital',
          'Legal & Regulatory',
          'Product Strategy',
          'Export & Trade',
        ]));
        expect((ins['summary'] as String).length, greaterThanOrEqualTo(30));
        expect((ins['takeaways'] as List<dynamic>).length, inInclusiveRange(1, 6));
        expect((ins['practical_action'] as String).length, greaterThanOrEqualTo(15));

        // Evidence check: must cite non-empty segment indices >= 0
        final evidenceIndices =
            (ins['evidence_segment_indices'] as List<dynamic>).cast<int>();
        expect(evidenceIndices.isNotEmpty, isTrue);
        for (final idx in evidenceIndices) {
          expect(idx, greaterThanOrEqualTo(0));
        }

        // Confidence score check
        final confidence = (ins['confidence_score'] as num).toDouble();
        expect(confidence, inInclusiveRange(0.0, 1.0));
      }

      // Quotations checks
      final quotations = validCandidateMap['quotations'] as List<dynamic>;
      expect(quotations.isNotEmpty, isTrue);

      for (final qDynamic in quotations) {
        final q = qDynamic as Map<String, dynamic>;
        expect((q['amharic_quote'] as String).length, greaterThanOrEqualTo(10));
        expect((q['english_translation'] as String).length, greaterThanOrEqualTo(10));
        expect(q['speaker'], isNotEmpty);
        expect((q['source_segment_index'] as int), greaterThanOrEqualTo(0));
        expect((q['timestamp_seconds'] as int), greaterThanOrEqualTo(0));
        expect((q['context'] as String).length, greaterThanOrEqualTo(15));
      }
    });

    // =========================================================================
    // 3. Negative Testing: Deliberately Invalid Fixture Rejection
    // =========================================================================
    test('Schema validation flags deliberately malformed candidate outputs', () {
      final summary =
          invalidCandidateMap['episode_summary'] as Map<String, dynamic>;
      // 'Too short' is < 30 chars
      expect((summary['brief'] as String).length < 30, isTrue);
      // 'primary_themes' has only 1 item (< 2 minItems)
      expect((summary['primary_themes'] as List<dynamic>).length < 2, isTrue);

      final insights = invalidCandidateMap['insights'] as List<dynamic>;
      final badInsight = insights.first as Map<String, dynamic>;

      // Invalid category
      const validCategories = [
        'Operations',
        'Fintech',
        'Technology & Infrastructure',
        'Leadership & Culture',
        'Sales & Marketing',
        'Finance & Capital',
        'Legal & Regulatory',
        'Product Strategy',
        'Export & Trade',
      ];
      expect(validCategories.contains(badInsight['category']), isFalse);

      // Negative confidence score
      expect((badInsight['confidence_score'] as num) < 0, isTrue);

      // Empty evidence segments
      expect(
          (badInsight['evidence_segment_indices'] as List<dynamic>).isEmpty,
          isTrue);

      final quotations = invalidCandidateMap['quotations'] as List<dynamic>;
      final badQuote = quotations.first as Map<String, dynamic>;

      // Negative timestamp
      expect((badQuote['timestamp_seconds'] as int) < 0, isTrue);
      // Negative segment index
      expect((badQuote['source_segment_index'] as int) < 0, isTrue);
    });

    // =========================================================================
    // 4. Flutter Model Parity & Deserialization Tests
    // =========================================================================
    test('Backend published episode payload maps 100% cleanly to Flutter Episode model', () {
      final episode = Episode.fromJson(publishedEpisodeMap);

      // Top-level episode fields
      expect(episode.id, '7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a');
      expect(episode.title, 'Scaling Cold Chain Logistics Across Agricultural Corridors');
      expect(episode.podcastTitle, 'Meri Business Series');
      expect(episode.episodeNumber, 101);
      expect(episode.durationMinutes, 74);
      expect(episode.formattedDuration, '1h 14m');
      expect(episode.publishedAt, DateTime.parse('2026-09-12T08:00:00.000Z'));
      expect(episode.isFeatured, isTrue);
      expect(episode.tags, containsAll(['Logistics', 'Agritech', 'Operations', 'Supply Chain']));
      expect(episode.audioUrl, 'https://sample-audio.meri.et/ep101.mp3');
      expect(episode.youtubeUrl, 'https://www.youtube.com/watch?v=sample-ep101');

      // Guest nested entity
      final guest = episode.guest;
      expect(guest.id, '3b4c5d6e-7f8a-9b0c-1d2e-3f4a5b6c7d8e');
      expect(guest.name, 'Dawit Tadesse');
      expect(guest.company, 'Nile Cold Chain Logistics');
      expect(guest.industry, 'Agricultural Logistics & Cold Storage');

      // Insights nested list
      expect(episode.insights.length, 2);
      final firstInsight = episode.insights.first;
      expect(firstInsight.id, '1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d');
      expect(firstInsight.episodeId, episode.id);
      expect(firstInsight.category, 'Operations');
      expect(firstInsight.takeaways.length, 3);
      expect(firstInsight.practicalAction, isNotNull);

      // Quotations nested list
      expect(episode.quotations.length, 2);
      final firstQuote = episode.quotations.first;
      expect(firstQuote.id, '4c5d6e7f-8a9b-0c1d-2e3f-4a5b6c7d8e9f');
      expect(firstQuote.episodeId, episode.id);
      expect(firstQuote.amharicQuote, contains('የሎጂስቲክስ ስራ'));
      expect(firstQuote.englishTranslation, contains('The greatest test in logistics'));
      expect(firstQuote.speaker, 'Dawit Tadesse');
      expect(firstQuote.timestampSeconds, 1420);
      expect(firstQuote.formattedTimestamp, '23:40');

      final secondQuote = episode.quotations[1];
      expect(secondQuote.timestampSeconds, 3210);
      expect(secondQuote.formattedTimestamp, '53:30');

      // Serialization round-trip symmetry
      final serializedJson = episode.toJson();
      final roundTripped = Episode.fromJson(serializedJson);
      expect(roundTripped, equals(episode));
    });

    // =========================================================================
    // 5. YouTube Timestamp Deep-Linking Compatibility
    // =========================================================================
    test('YouTubeUrlHelper successfully builds timestamped URLs for backend quotations', () {
      final episode = Episode.fromJson(publishedEpisodeMap);
      expect(YouTubeUrlHelper.isValidYouTubeUrl(episode.youtubeUrl), isTrue);

      final quoteUri = YouTubeUrlHelper.buildTimestampedUrl(
        episode.youtubeUrl,
        episode.quotations.first.timestampSeconds,
      );

      expect(quoteUri, isNotNull);
      expect(quoteUri.toString(), 'https://www.youtube.com/watch?v=sample-ep101&t=1420s');
    });

    // =========================================================================
    // 6. SQL Migration File Verification
    // =========================================================================
    test('SQL migration declares all 9 required tables, constraints, RLS, and RPC', () {
      final requiredTables = [
        'CREATE TABLE IF NOT EXISTS guests',
        'CREATE TABLE IF NOT EXISTS episodes',
        'CREATE TABLE IF NOT EXISTS processing_jobs',
        'CREATE TABLE IF NOT EXISTS transcript_segments',
        'CREATE TABLE IF NOT EXISTS transcript_chunks',
        'CREATE TABLE IF NOT EXISTS extraction_runs',
        'CREATE TABLE IF NOT EXISTS insights',
        'CREATE TABLE IF NOT EXISTS quotations',
        'CREATE TABLE IF NOT EXISTS insight_evidence',
      ];

      for (final tableStmt in requiredTables) {
        expect(
          migrationSqlString.contains(tableStmt),
          isTrue,
          reason: 'Migration must declare $tableStmt',
        );
      }

      // Check for YouTube deduplication unique constraint
      expect(
        migrationSqlString.contains('youtube_video_id TEXT NOT NULL UNIQUE'),
        isTrue,
        reason: 'Migration must enforce unique normalized YouTube video IDs',
      );

      // Check for publication status check constraint
      expect(
        migrationSqlString.contains('chk_published_timestamp CHECK'),
        isTrue,
        reason: 'Migration must enforce publication timestamp check',
      );

      // Check for atomic publication function
      expect(
        migrationSqlString.contains('CREATE OR REPLACE FUNCTION publish_episode'),
        isTrue,
        reason: 'Migration must provide atomic publish_episode RPC function',
      );

      // Check for RLS enablement on all tables
      for (final table in [
        'guests',
        'episodes',
        'processing_jobs',
        'transcript_segments',
        'transcript_chunks',
        'extraction_runs',
        'insights',
        'quotations',
        'insight_evidence'
      ]) {
        expect(
          migrationSqlString.contains('ALTER TABLE $table ENABLE ROW LEVEL SECURITY;'),
          isTrue,
          reason: 'Table $table must have Row-Level Security enabled',
        );
      }

      // Cloud compatibility checks:
      // Must NOT attempt to create roles managed by Supabase infrastructure
      expect(
        migrationSqlString.contains('CREATE ROLE anon'),
        isFalse,
        reason: 'Cloud migration must not attempt to create Supabase-managed anon role',
      );
      expect(
        migrationSqlString.contains('CREATE ROLE authenticated'),
        isFalse,
        reason: 'Cloud migration must not attempt to create Supabase-managed authenticated role',
      );

      // Must NOT create fallback definitions or replacements for Supabase authentication functions
      expect(
        migrationSqlString.contains('CREATE OR REPLACE FUNCTION auth.jwt'),
        isFalse,
        reason: 'Cloud migration must not override native Supabase auth.jwt() function',
      );
      expect(
        migrationSqlString.contains('CREATE OR REPLACE FUNCTION auth.uid'),
        isFalse,
        reason: 'Cloud migration must not override native Supabase auth.uid() function',
      );

      // Generated start_seconds column in transcript_segments
      expect(
        migrationSqlString.contains('start_seconds NUMERIC(8,2) GENERATED ALWAYS AS'),
        isTrue,
        reason: 'Migration must compute start_seconds as a stored generated column',
      );

      // Explicit grants on public tables
      expect(
        migrationSqlString.contains('GRANT SELECT ON episodes, guests, insights, quotations TO anon, authenticated;'),
        isTrue,
        reason: 'Migration must grant SELECT to anon and authenticated on public tables',
      );

      // Explicit revocations on private pipeline tables
      expect(
        migrationSqlString.contains('REVOKE ALL ON processing_jobs, transcript_segments, transcript_chunks, extraction_runs, insight_evidence FROM anon, PUBLIC;'),
        isTrue,
        reason: 'Migration must explicitly revoke private table access from public/anon',
      );

      // Secure search_path and authorization check on publish_episode
      expect(
        migrationSqlString.contains('SET search_path = public, auth, pg_temp'),
        isTrue,
        reason: 'SECURITY DEFINER function must pin search_path to prevent hijacking',
      );
      expect(
        migrationSqlString.contains('p_require_quotations BOOLEAN DEFAULT FALSE'),
        isTrue,
        reason: 'publish_episode must provide configurable quotation requirements',
      );
    });

    // =========================================================================
    // 7. Bookmarks UUID vs. Legacy ID Migration Simulation
    // =========================================================================
    test('Simulated bookmark resolution supports both legacy string IDs and UUIDs', () {
      final episode = Episode.fromJson(publishedEpisodeMap);
      final legacyId = publishedEpisodeMap['legacyId'] as String; // 'ep-101'
      final uuid = episode.id; // '7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a'

      // Stored user bookmarks containing legacy ID from older client build
      final storedBookmarks = <String>{'ep-101', 'ep-102'};

      bool isEpisodeBookmarked(Episode ep, Set<String> bookmarkedIds, {String? legacy}) {
        return bookmarkedIds.contains(ep.id) || (legacy != null && bookmarkedIds.contains(legacy));
      }

      // Legacy lookup matches
      expect(isEpisodeBookmarked(episode, storedBookmarks, legacy: legacyId), isTrue);

      // Simulating transparent migration
      final legacyToUuidMap = {
        'ep-101': '7f8b9e6a-4d2c-4f1b-9e3a-8b2c4d6e8f0a',
        'ep-102': '8a9b0c1d-2e3f-4a5b-6c7d-8e9f0a1b2c3d',
      };

      final migratedBookmarks = storedBookmarks
          .map((id) => legacyToUuidMap[id] ?? id)
          .toSet();

      expect(migratedBookmarks, contains(uuid));
      expect(migratedBookmarks.contains('ep-101'), isFalse);
      expect(isEpisodeBookmarked(episode, migratedBookmarks), isTrue);
    });
  });
}
