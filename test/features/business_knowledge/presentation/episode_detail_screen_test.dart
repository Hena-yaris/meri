import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';
import 'package:meri/features/business_knowledge/data/providers.dart';
import 'package:meri/features/business_knowledge/domain/models/episode.dart';
import 'package:meri/features/business_knowledge/presentation/screens/episode_detail_screen.dart';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  const testFullJson = '''
  {
    "episodes": [
      {
        "id": "ep-101",
        "title": "Scaling Cold Chain Logistics",
        "podcastTitle": "Meri Business Series",
        "episodeNumber": 101,
        "durationMinutes": 74,
        "publishedAt": "2026-09-12T08:00:00.000Z",
        "summary": "Deep exploration of agricultural cold chain networks.",
        "isFeatured": true,
        "tags": ["Logistics", "Agritech"],
        "youtubeUrl": "https://www.youtube.com/watch?v=sample-ep101",
        "guest": {
          "id": "g-101",
          "name": "Dawit Tadesse",
          "title": "Managing Director",
          "company": "Nile Cold Chain",
          "bio": "Logistics entrepreneur operating high-altitude freight.",
          "industry": "Cold Storage Logistics"
        },
        "insights": [
          {
            "id": "ins-101-1",
            "episodeId": "ep-101",
            "title": "Telemetry Over Fleet Size",
            "category": "Operations",
            "summary": "Partnering with regional truck owners saves upfront capital.",
            "takeaways": [
              "Sensors cut asset costs by 60%",
              "Quality incentives align drivers"
            ],
            "practicalAction": "Audit vehicle asset depreciation."
          },
          {
            "id": "ins-101-2",
            "episodeId": "ep-101",
            "title": "High Altitude Cooling",
            "category": "Infrastructure",
            "summary": "Altitude shifts stress standard cooling compressors.",
            "takeaways": [
              "Use dual-compressor failovers"
            ],
            "practicalAction": null
          }
        ],
        "quotations": [
          {
            "id": "quote-101-1",
            "episodeId": "ep-101",
            "amharicQuote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን ምርት መጠበቅ ነው።",
            "englishTranslation": "The test in logistics is preserving harvest, not buying trucks.",
            "speaker": "Dawit Tadesse",
            "timestampSeconds": 1420,
            "context": "Discussing fleet capital vs sensor retrofits."
          },
          {
            "id": "quote-101-2",
            "episodeId": "ep-101",
            "amharicQuote": "የገበሬው ድካም በከተማ ገበያ በክብር እንዲሸጥ መንገድ ማቃናት አለብን።",
            "englishTranslation": "We must smooth the path so farmer labor sells with dignity.",
            "speaker": "Dawit Tadesse",
            "timestampSeconds": 3665,
            "context": "Closing reflections on agricultural equity."
          }
        ]
      },
      {
        "id": "ep-104",
        "title": "Specialty Coffee Roasting at Origin",
        "podcastTitle": "Meri Business Series",
        "episodeNumber": 104,
        "durationMinutes": 68,
        "publishedAt": "2026-10-15T09:15:00.000Z",
        "summary": "Transitioning from green coffee export to packaged specialty retail.",
        "isFeatured": false,
        "tags": ["Coffee", "Export"],
        "youtubeUrl": null,
        "guest": {
          "id": "g-104",
          "name": "Samrawit Kebede",
          "title": "Founder & Master Roaster",
          "company": "Buna Origin",
          "bio": "Agronomist and specialty coffee champion.",
          "industry": null
        },
        "insights": [],
        "quotations": [
          {
            "id": "quote-104-1",
            "episodeId": "ep-104",
            "amharicQuote": "ቡናችን በዓለም ላይ ወደር የሌለው ቅርስ ነው።",
            "englishTranslation": "Our coffee is an unmatched world heritage.",
            "speaker": "Samrawit Kebede",
            "timestampSeconds": 980,
            "context": ""
          }
        ]
      }
    ]
  }
  ''';

  Widget buildDetailWidget({
    required String episodeId,
    LocalJsonDataSource? customDataSource,
    List<dynamic> additionalOverrides = const [],
  }) {
    final dataSource = customDataSource ??
        LocalJsonDataSource(
          loader: (path) async => testFullJson,
        );

    final router = GoRouter(
      initialLocation: '/episode/$episodeId',
      routes: [
        GoRoute(
          path: '/episode/:id',
          builder: (context, state) => EpisodeDetailScreen(
            episodeId: state.pathParameters['id']!,
          ),
        ),
      ],
    );

    return ProviderScope(
      overrides: [
        localJsonDataSourceProvider.overrideWithValue(dataSource),
        ...additionalOverrides,
      ],
      child: MaterialApp.router(
        routerConfig: router,
      ),
    );
  }

  group('EpisodeDetailScreen Presentation Tests', () {
    testWidgets('renders all sections for a complete episode with YouTube source', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildDetailWidget(episodeId: 'ep-101'));
      await tester.pumpAndSettle();

      // 1. Header & Metadata
      expect(find.text('EPISODE #101'), findsWidgets);
      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.text('1h 14m'), findsOneWidget);
      expect(find.text('LOGISTICS'), findsOneWidget);
      expect(find.text('AGRITECH'), findsOneWidget);

      // YouTube Hero Banner
      expect(find.text('Verified YouTube Recording'), findsOneWidget);
      expect(find.text('Watch'), findsOneWidget);

      // 2. Executive Overview
      expect(find.text('Executive Summary'), findsOneWidget);
      expect(find.text('Deep exploration of agricultural cold chain networks.'), findsOneWidget);

      // 3. Featured Entrepreneur
      expect(find.text('Featured Entrepreneur'), findsOneWidget);
      expect(find.text('Dawit Tadesse'), findsWidgets);
      expect(find.text('Managing Director • Nile Cold Chain'), findsOneWidget);
      expect(find.text('COLD STORAGE LOGISTICS'), findsOneWidget);
      expect(find.text('Logistics entrepreneur operating high-altitude freight.'), findsOneWidget);

      // 4. Strategic Insights (all items rendered)
      expect(find.text('Strategic Insights'), findsOneWidget);
      expect(find.text('Telemetry Over Fleet Size'), findsOneWidget);
      expect(find.text('Partnering with regional truck owners saves upfront capital.'), findsOneWidget);
      expect(find.text('Sensors cut asset costs by 60%'), findsOneWidget);
      expect(find.text('PRACTICAL ACTION'), findsOneWidget);
      expect(find.text('Audit vehicle asset depreciation.'), findsOneWidget);

      // Second insight
      expect(find.text('High Altitude Cooling'), findsOneWidget);
      expect(find.text('Use dual-compressor failovers'), findsOneWidget);

      // 5. Direct Quotations (all items rendered)
      expect(find.text('Direct Quotations'), findsOneWidget);
      expect(find.text('“የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት ሳይሆን ምርት መጠበቅ ነው።”'), findsOneWidget);
      expect(find.text('The test in logistics is preserving harvest, not buying trucks.'), findsOneWidget);
      expect(find.text('“የገበሬው ድካም በከተማ ገበያ በክብር እንዲሸጥ መንገድ ማቃናት አለብን።”'), findsOneWidget);
      expect(find.text('We must smooth the path so farmer labor sells with dignity.'), findsOneWidget);

      // Quotation formatted timestamps and actionable Watch badge
      expect(find.text('23:40 • Watch'), findsOneWidget);
      expect(find.text('1:01:05 • Watch'), findsOneWidget);

      // 6. Disclaimer
      expect(find.textContaining('DEVELOPMENT SAMPLE DATASET'), findsOneWidget);
    });

    testWidgets('renders non-actionable static timestamp when episode has no YouTube URL', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildDetailWidget(episodeId: 'ep-104'));
      await tester.pumpAndSettle();

      // Episode 104 title & guest
      expect(find.text('Specialty Coffee Roasting at Origin'), findsOneWidget);
      expect(find.text('Samrawit Kebede'), findsWidgets);

      // No YouTube Hero Banner since youtubeUrl is null
      expect(find.text('Verified YouTube Recording'), findsNothing);

      // Quotation is present
      expect(find.text('“ቡናችን በዓለም ላይ ወደር የሌለው ቅርስ ነው።”'), findsOneWidget);

      // Static timestamp is displayed without Watch action
      expect(find.text('16:20'), findsOneWidget);
      expect(find.text('16:20 • Watch'), findsNothing);

      // Handles empty insights cleanly
      expect(find.text('No strategic insights recorded for this interview.'), findsOneWidget);
    });

    testWidgets('renders clean Not Found state when episode ID does not exist', (tester) async {
      await tester.pumpWidget(buildDetailWidget(episodeId: 'non-existent-id'));
      await tester.pumpAndSettle();

      expect(find.text('Episode Not Found'), findsOneWidget);
      expect(find.textContaining('non-existent-id'), findsOneWidget);
      expect(find.text('Return to Archive'), findsOneWidget);
    });

    testWidgets('renders loading state while resolving episode', (tester) async {
      final completer = Completer<Episode?>();
      addTearDown(() {
        if (!completer.isCompleted) completer.complete(null);
      });

      final widget = ProviderScope(
        overrides: [
          episodeByIdProvider('ep-loading').overrideWith(
            (ref) => completer.future,
          ),
        ],
        child: const MaterialApp(
          home: EpisodeDetailScreen(episodeId: 'ep-loading'),
        ),
      );

      await tester.pumpWidget(widget);
      // Just pump without settling to catch loading state
      await tester.pump();

      expect(find.text('Loading episode record...'), findsOneWidget);
    });

    testWidgets('renders error state with retry when provider fails', (tester) async {
      final widget = ProviderScope(
        overrides: [
          episodeByIdProvider('ep-error').overrideWith(
            (ref) => Future<Episode?>.error(Exception('Network timeout')),
          ),
        ],
        child: const MaterialApp(
          home: EpisodeDetailScreen(episodeId: 'ep-error'),
        ),
      );

      await tester.pumpWidget(widget);
      await tester.pumpAndSettle();

      expect(find.text('Unable to Load Records'), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
    });
  });

  group('Navigation from EpisodeCard to EpisodeDetailScreen', () {
    testWidgets('Tapping episode card in Explore navigates to EpisodeDetailScreen', (tester) async {
      final dataSource = LocalJsonDataSource(
        loader: (path) async => testFullJson,
      );

      final router = GoRouter(
        initialLocation: '/explore',
        routes: [
          GoRoute(
            path: '/explore',
            builder: (context, state) => Scaffold(
              body: ListView(
                children: [
                  ListTile(
                    title: const Text('Scaling Cold Chain Logistics'),
                    onTap: () => context.push('/episode/ep-101'),
                  ),
                ],
              ),
            ),
          ),
          GoRoute(
            path: '/episode/:id',
            builder: (context, state) => EpisodeDetailScreen(
              episodeId: state.pathParameters['id']!,
            ),
          ),
        ],
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            localJsonDataSourceProvider.overrideWithValue(dataSource),
          ],
          child: MaterialApp.router(
            routerConfig: router,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Tap on the episode item
      await tester.tap(find.text('Scaling Cold Chain Logistics'));
      await tester.pumpAndSettle();

      // Should be on the detail screen
      expect(find.text('Executive Summary'), findsOneWidget);
      expect(find.text('Dawit Tadesse'), findsWidgets);
    });
  });
}
