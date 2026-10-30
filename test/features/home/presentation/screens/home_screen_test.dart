import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';
import 'package:meri/features/business_knowledge/data/providers.dart';
import 'package:meri/features/business_knowledge/presentation/screens/episode_detail_screen.dart';
import 'package:meri/features/home/presentation/screens/home_screen.dart';
import 'package:meri/features/home/presentation/widgets/executive_takeaways_list.dart';
import 'package:meri/features/home/presentation/widgets/featured_episode_hero.dart';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  const singleEpisodeJson = '''
  {
    "episodes": [
      {
        "id": "ep-199",
        "title": "Turning Vocational Craft into Scalable Enterprise",
        "podcastTitle": "Meri Podcast",
        "episodeNumber": 199,
        "durationMinutes": 86,
        "publishedAt": "2024-09-01T00:00:00.000Z",
        "summary": "Wengelawit (Liya) Gole details formalizing curriculum and managing capital.",
        "isFeatured": true,
        "tags": ["Vocational Training", "Service Operations"],
        "youtubeUrl": "https://www.youtube.com/watch?v=wohjyv428Us",
        "guest": {
          "id": "guest-liya-gole",
          "name": "Wengelawit (Liya) Gole",
          "title": "Founder & CEO",
          "company": "International Makeup School & Liya Gole Beauty",
          "bio": "Pioneering Ethiopian beauty and vocational education entrepreneur."
        },
        "insights": [
          {
            "id": "ins-199-1",
            "episodeId": "ep-199",
            "title": "Legitimizing Informal Trades Through Structured Accreditation",
            "summary": "Transforming a dismissed service craft into a respected commercial enterprise requires standardizing curriculum.",
            "category": "Vocational Training",
            "takeaways": ["Standardized training builds industry credibility"],
            "practicalAction": "Formalize internal apprenticeship playbooks."
          },
          {
            "id": "ins-199-2",
            "episodeId": "ep-199",
            "title": "Disciplined Capital Reinvestment Over Passive Extraction",
            "summary": "Service enterprises achieve operational durability when leadership separates busywork from productive execution.",
            "category": "Service Operations",
            "takeaways": ["Avoid drawing capital before systems stabilize"],
            "practicalAction": "Audit tasks weekly for institutional productivity."
          }
        ],
        "quotations": [
          {
            "id": "q-199-1",
            "episodeId": "ep-199",
            "amharicQuote": "ቢዚ ነሽ ወይስ ፕሮዳክቲቭ ነሽ?",
            "englishTranslation": "Are you simply busy, or are you truly productive?",
            "speaker": "Wengelawit (Liya) Gole",
            "timestampSeconds": 65,
            "context": "Liya reflecting on business operational focus."
          }
        ]
      }
    ]
  }
  ''';

  const multiEpisodeJson = '''
  {
    "episodes": [
      {
        "id": "ep-199",
        "title": "Turning Vocational Craft into Scalable Enterprise",
        "podcastTitle": "Meri Podcast",
        "episodeNumber": 199,
        "durationMinutes": 86,
        "publishedAt": "2024-09-01T00:00:00.000Z",
        "summary": "Wengelawit (Liya) Gole details formalizing curriculum.",
        "isFeatured": true,
        "tags": ["Vocational Training"],
        "guest": {
          "id": "guest-liya-gole",
          "name": "Wengelawit (Liya) Gole",
          "title": "Founder & CEO",
          "company": "IMS",
          "bio": "Beauty entrepreneur."
        },
        "insights": [],
        "quotations": []
      },
      {
        "id": "ep-101",
        "title": "Scaling Cold Chain Logistics Across Corridors",
        "podcastTitle": "Meri Podcast",
        "episodeNumber": 101,
        "durationMinutes": 74,
        "publishedAt": "2026-09-12T08:00:00.000Z",
        "summary": "Agricultural freight and telemetry in Ethiopia.",
        "isFeatured": false,
        "tags": ["Logistics"],
        "guest": {
          "id": "guest-dawit",
          "name": "Dawit Tadesse",
          "title": "Founder",
          "company": "Nile Cold Chain",
          "bio": "Logistics founder."
        },
        "insights": [],
        "quotations": []
      }
    ]
  }
  ''';

  Widget buildHomeTestWidget({
    String json = singleEpisodeJson,
    TextScaler? textScaler,
    GoRouter? customRouter,
  }) {
    final mockDataSource = LocalJsonDataSource(
      loader: (path) async => json,
    );

    final router = customRouter ??
        GoRouter(
          initialLocation: '/',
          routes: [
            GoRoute(
              path: '/',
              builder: (context, state) => const HomeScreen(),
            ),
            GoRoute(
              path: '/episode/:id',
              builder: (context, state) => EpisodeDetailScreen(
                episodeId: state.pathParameters['id']!,
              ),
            ),
            GoRoute(
              path: '/explore',
              builder: (context, state) => const Scaffold(
                body: Center(child: Text('Explore Knowledge')),
              ),
            ),
          ],
        );

    Widget app = MaterialApp.router(
      routerConfig: router,
    );

    if (textScaler != null) {
      app = MediaQuery(
        data: MediaQueryData(textScaler: textScaler),
        child: app,
      );
    }

    return ProviderScope(
      overrides: [
        localJsonDataSourceProvider.overrideWithValue(mockDataSource),
      ],
      child: app,
    );
  }

  group('Editorial Home Screen Redesign — Verification Suite', () {
    testWidgets('1. Home renders editorial masthead and the current featured episode', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildHomeTestWidget());
      await tester.pumpAndSettle();

      // Editorial masthead without dashboard buttons
      expect(find.text('MERI'), findsOneWidget);
      expect(find.textContaining('The business behind the story.'), findsOneWidget);
      expect(find.byIcon(Icons.refresh_rounded), findsNothing);

      // Featured Masterclass section
      expect(find.text('Masterclass Spotlight'), findsOneWidget);
      expect(find.text('VERIFIED ENTREPRENEUR JOURNEY'), findsOneWidget);
      expect(find.byType(FeaturedEpisodeHero), findsOneWidget);

      // Lead story elements
      expect(find.text('Turning Vocational Craft into Scalable Enterprise'), findsOneWidget);
      expect(find.text('Wengelawit (Liya) Gole'), findsOneWidget);
      expect(find.text('Founder & CEO, International Makeup School & Liya Gole Beauty'), findsOneWidget);
      expect(find.text('EPISODE #199 • 1H 26M'), findsOneWidget);
      expect(find.text('“ቢዚ ነሽ ወይስ ፕሮዳክቲቭ ነሽ?”'), findsOneWidget);
      expect(find.text('Are you simply busy, or are you truly productive?'), findsOneWidget);
      expect(find.text('Read Full Briefing'), findsOneWidget);
    });

    testWidgets('2. Featured episode is not immediately repeated in archive when only one exists', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildHomeTestWidget(json: singleEpisodeJson));
      await tester.pumpAndSettle();

      // Should find headline exactly once on the page (in FeaturedEpisodeHero, not repeated in archive)
      expect(
        find.text('Turning Vocational Craft into Scalable Enterprise'),
        findsOneWidget,
      );

      // Archive header should not be displayed when archive is empty
      expect(find.text('Interview Archive'), findsNothing);

      // Understated exploration footer is shown instead
      expect(find.text('EXPLORE THEMATIC ARCHIVE'), findsOneWidget);
      expect(find.text('Browse Topic Index'), findsOneWidget);
    });

    testWidgets('2b. Multi-episode dataset renders archive without repeating featured episode', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildHomeTestWidget(json: multiEpisodeJson));
      await tester.pumpAndSettle();

      // Featured episode appears in hero
      expect(find.byType(FeaturedEpisodeHero), findsOneWidget);
      expect(find.text('Turning Vocational Craft into Scalable Enterprise'), findsOneWidget);

      // Non-featured episode appears in archive
      expect(find.text('Interview Archive'), findsOneWidget);
      expect(find.text('Scaling Cold Chain Logistics Across Corridors'), findsOneWidget);
      expect(find.textContaining('Dawit Tadesse'), findsOneWidget);

      // Lead story is still not duplicated in archive
      expect(find.text('Turning Vocational Craft into Scalable Enterprise'), findsOneWidget);
    });

    testWidgets('3. Existing insights render in vertically flowing ExecutiveTakeawaysList', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildHomeTestWidget());
      await tester.pumpAndSettle();

      expect(find.byType(ExecutiveTakeawaysList), findsOneWidget);
      expect(find.text('Executive Takeaways'), findsOneWidget);

      // Ordinals
      expect(find.text('01'), findsOneWidget);
      expect(find.text('02'), findsOneWidget);

      // Insight titles and categories
      expect(
        find.text('Legitimizing Informal Trades Through Structured Accreditation'),
        findsOneWidget,
      );
      expect(find.text('VOCATIONAL TRAINING'), findsOneWidget);
      expect(
        find.text('Disciplined Capital Reinvestment Over Passive Extraction'),
        findsOneWidget,
      );
      expect(find.text('SERVICE OPERATIONS'), findsOneWidget);

      // Practical action badge
      expect(find.text('Formalize internal apprenticeship playbooks.'), findsOneWidget);

      // Tapping an insight opens bottom sheet
      await tester.tap(find.text('Legitimizing Informal Trades Through Structured Accreditation'));
      await tester.pumpAndSettle();

      expect(find.text('Formalize internal apprenticeship playbooks.'), findsWidgets);
    });

    testWidgets('4. Opening lead story navigates to its detail screen', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildHomeTestWidget());
      await tester.pumpAndSettle();

      // Tap on "Read Full Briefing"
      await tester.tap(find.text('Read Full Briefing'));
      await tester.pumpAndSettle();

      // Detail screen rendered
      expect(find.byType(EpisodeDetailScreen), findsOneWidget);
      expect(find.text('Turning Vocational Craft into Scalable Enterprise'), findsOneWidget);
    });

    testWidgets('5. Bookmark interactions work and do not trigger episode navigation', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildHomeTestWidget());
      await tester.pumpAndSettle();

      final bookmarkFinder = find.bySemanticsLabel('Bookmark episode');
      expect(bookmarkFinder, findsOneWidget);

      // Verify touch target >= 48x48
      final buttonSize = tester.getSize(bookmarkFinder);
      expect(buttonSize.width, greaterThanOrEqualTo(48.0));
      expect(buttonSize.height, greaterThanOrEqualTo(48.0));

      // Tap bookmark
      await tester.tap(bookmarkFinder);
      await tester.pumpAndSettle();

      // Should still be on Home, NOT navigated to Detail screen
      expect(find.byType(EpisodeDetailScreen), findsNothing);
      expect(find.byType(HomeScreen), findsOneWidget);

      // Bookmark state changed
      expect(find.bySemanticsLabel('Remove bookmark'), findsOneWidget);
    });

    testWidgets('6. Obsolete synthetic-data warning is not displayed', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildHomeTestWidget());
      await tester.pumpAndSettle();

      expect(find.textContaining('DEVELOPMENT SAMPLE DATASET'), findsNothing);
      expect(find.textContaining('Illustrative synthetic profiles'), findsNothing);
    });

    testWidgets('7. Layout remains usable at 1.5x text scale without RenderFlex overflow', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(
        buildHomeTestWidget(
          textScaler: const TextScaler.linear(1.5),
        ),
      );
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(find.text('Turning Vocational Craft into Scalable Enterprise'), findsOneWidget);
      expect(
        find.text('Legitimizing Informal Trades Through Structured Accreditation'),
        findsOneWidget,
      );
    });
  });
}
