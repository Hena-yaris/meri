import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:meri/core/theme/app_typography.dart';
import 'package:meri/core/utils/youtube_url_helper.dart';
import 'package:meri/features/business_knowledge/data/providers.dart';
import 'package:meri/features/business_knowledge/domain/models/episode.dart';
import 'package:meri/features/business_knowledge/domain/models/insight.dart';
import 'package:meri/features/home/presentation/widgets/episode_card.dart';
import 'package:meri/features/home/presentation/widgets/insight_preview_strip.dart';

void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  group('Milestone 1 — Authentic Demo Content & Schema Integrity', () {
    test('sample_episodes.json deserializes into Episode model with authentic data', () async {
      final jsonString = await rootBundle.loadString('assets/data/sample_episodes.json');
      final decoded = jsonDecode(jsonString) as Map<String, dynamic>;
      final episodesList = decoded['episodes'] as List<dynamic>;

      expect(episodesList.length, 1);
      final episode = Episode.fromJson(episodesList.first as Map<String, dynamic>);

      expect(episode.id, 'ep-199');
      expect(episode.episodeNumber, 199);
      expect(episode.guest.name, 'Wengelawit (Liya) Gole');
      expect(episode.guest.company, 'International Makeup School & Liya Gole Beauty');
      expect(episode.youtubeUrl, 'https://www.youtube.com/watch?v=wohjyv428Us');
      expect(episode.insights.length, 2);
      expect(episode.quotations.length, 3);
    });

    test('Authentic quotations are grounded with verified timestamps and source video ID', () async {
      final jsonString = await rootBundle.loadString('assets/data/sample_episodes.json');
      final decoded = jsonDecode(jsonString) as Map<String, dynamic>;
      final episode = Episode.fromJson((decoded['episodes'] as List<dynamic>).first as Map<String, dynamic>);

      // Verify YouTube URL helper produces exact timestamp URL
      expect(episode.youtubeUrl, contains('wohjyv428Us'));

      final q1 = episode.quotations[0];
      expect(q1.timestampSeconds, 65);
      expect(q1.amharicQuote, contains('ቢዚ ነሽ ወይስ ፕሮዳክቲቭ ነሽ'));
      final timestampUrl1 = YouTubeUrlHelper.buildTimestampedUrl(
        episode.youtubeUrl!,
        q1.timestampSeconds,
      )?.toString();
      expect(timestampUrl1, 'https://www.youtube.com/watch?v=wohjyv428Us&t=65s');

      final q2 = episode.quotations[1];
      expect(q2.timestampSeconds, 56);
      expect(q2.amharicQuote, contains('ስራ ሰው አይደለም'));
      final timestampUrl2 = YouTubeUrlHelper.buildTimestampedUrl(
        episode.youtubeUrl!,
        q2.timestampSeconds,
      )?.toString();
      expect(timestampUrl2, 'https://www.youtube.com/watch?v=wohjyv428Us&t=56s');

      final q3 = episode.quotations[2];
      expect(q3.timestampSeconds, 205);
      expect(q3.amharicQuote, contains('ስታርት ካልጀመርክ'));
      final timestampUrl3 = YouTubeUrlHelper.buildTimestampedUrl(
        episode.youtubeUrl!,
        q3.timestampSeconds,
      )?.toString();
      expect(timestampUrl3, 'https://www.youtube.com/watch?v=wohjyv428Us&t=205s');
    });
  });

  group('Milestone 1 — Critical UX & Layout Verification', () {
    testWidgets('InsightPreviewStrip adapts under 1.5x accessibility text scale without overflow', (tester) async {
      final testInsights = [
        const Insight(
          id: 'ins-1',
          episodeId: 'ep-199',
          title: 'Legitimizing Informal Trades Through Structured Accreditation',
          summary: 'Transforming a dismissed service craft into a respected commercial enterprise requires formalizing curriculum.',
          category: 'Vocational Training',
          takeaways: ['Takeaway 1', 'Takeaway 2'],
          practicalAction: 'Standardize training protocols before expansion.',
        ),
        const Insight(
          id: 'ins-2',
          episodeId: 'ep-199',
          title: 'Disciplined Capital Reinvestment Over Passive Extraction',
          summary: 'Service enterprises achieve operational durability when leadership constantly separates mere busywork from productive execution.',
          category: 'Service Operations',
          takeaways: ['Takeaway A', 'Takeaway B'],
          practicalAction: 'Audit weekly tasks for institutional productivity.',
        ),
      ];

      await tester.pumpWidget(
        MaterialApp(
          home: MediaQuery(
            data: const MediaQueryData(
              textScaler: TextScaler.linear(1.5),
            ),
            child: Scaffold(
              body: InsightPreviewStrip(insights: testInsights),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Zero exceptions and no RenderFlex overflow
      expect(tester.takeException(), isNull);
      expect(find.text('Legitimizing Informal Trades Through Structured Accreditation'), findsOneWidget);
      expect(find.text('Disciplined Capital Reinvestment Over Passive Extraction'), findsOneWidget);
    });

    testWidgets('EpisodeCard bookmark button has 48x48 hit target and does not trigger card onTap', (tester) async {
      var cardTapped = false;

      final testEpisode = Episode.fromJson({
        'id': 'ep-199',
        'title': 'Turning Makeup into an Enterprise',
        'podcastTitle': 'Meri Podcast',
        'episodeNumber': 199,
        'durationMinutes': 86,
        'publishedAt': '2024-09-01T00:00:00.000Z',
        'summary': 'Wengelawit (Liya) Gole shares how she built IMS.',
        'isFeatured': true,
        'tags': ['Vocational Training', 'Brand Strategy'],
        'youtubeUrl': 'https://www.youtube.com/watch?v=wohjyv428Us',
        'guest': {
          'id': 'guest-liya-gole',
          'name': 'Wengelawit (Liya) Gole',
          'title': 'Founder & CEO',
          'company': 'IMS',
          'bio': 'Pioneering beauty entrepreneur.',
          'industry': 'Beauty & Vocational Training',
        },
        'insights': [],
        'quotations': [],
      });

      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp(
            home: Scaffold(
              body: EpisodeCard(
                episode: testEpisode,
                onTap: () {
                  cardTapped = true;
                },
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Find the bookmark button by semantics label
      final bookmarkButtonFinder = find.bySemanticsLabel('Bookmark episode');
      expect(bookmarkButtonFinder, findsOneWidget);

      // Verify the minimum 48x48 logical-pixel hit target
      final buttonSize = tester.getSize(bookmarkButtonFinder);
      expect(buttonSize.width, greaterThanOrEqualTo(48.0));
      expect(buttonSize.height, greaterThanOrEqualTo(48.0));

      // Tap specifically on the bookmark button
      await tester.tap(bookmarkButtonFinder);
      await tester.pumpAndSettle();

      // Card onTap should NOT have been called
      expect(cardTapped, isFalse);

      // Bookmark semantics label should now reflect toggled state
      expect(find.bySemanticsLabel('Remove bookmark'), findsOneWidget);
    });

    test('AppTypography.amharicQuotation strictly enforces upright FontStyle.normal', () {
      final style = AppTypography.amharicQuotation();
      expect(style.fontStyle, FontStyle.normal);
      expect(style.fontFamilyFallback, contains('Noto Serif Ethiopic'));
      expect(style.fontFamilyFallback, contains('Noto Sans Ethiopic'));
      expect(style.letterSpacing, 0.0);
    });

    testWidgets('availableTopicsProvider dynamically matches available content', (tester) async {
      final container = ProviderContainer(
        overrides: [
          episodesProvider.overrideWith((ref) async => [
            Episode.fromJson({
              'id': 'ep-199',
              'title': 'Turning Makeup into an Enterprise',
              'podcastTitle': 'Meri Podcast',
              'episodeNumber': 199,
              'durationMinutes': 86,
              'publishedAt': '2024-09-01T00:00:00.000Z',
              'summary': 'Summary',
              'isFeatured': true,
              'tags': ['Vocational Training', 'Brand Strategy'],
              'guest': {
                'id': 'g-1',
                'name': 'Liya Gole',
                'title': 'CEO',
                'company': 'IMS',
                'bio': 'Bio',
              },
              'insights': [
                {
                  'id': 'ins-1',
                  'episodeId': 'ep-199',
                  'title': 'Insight',
                  'category': 'Service Operations',
                  'summary': 'Summary',
                  'takeaways': ['Takeaway'],
                }
              ],
              'quotations': [],
            }),
          ]),
        ],
      );
      addTearDown(container.dispose);

      // Await the episodes
      await container.read(episodesProvider.future);
      final topics = container.read(availableTopicsProvider);

      expect(topics, ['All', 'Brand Strategy', 'Service Operations', 'Vocational Training']);
      expect(topics.contains('Hiring & Leadership'), isFalse);
    });
  });
}
