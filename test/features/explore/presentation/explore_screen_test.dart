import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';
import 'package:meri/features/business_knowledge/data/providers.dart';
import 'package:meri/features/business_knowledge/presentation/screens/episode_detail_screen.dart';
import 'package:meri/features/explore/presentation/screens/explore_screen.dart';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  const testSampleJson = '''
  {
    "episodes": [
      {
        "id": "ep-101",
        "title": "Scaling Cold Chain Logistics",
        "podcastTitle": "Meri Business Series",
        "episodeNumber": 101,
        "durationMinutes": 74,
        "publishedAt": "2026-09-12T08:00:00.000Z",
        "summary": "Agricultural freight and telemetry in Ethiopia.",
        "isFeatured": true,
        "tags": ["Logistics", "Agritech"],
        "guest": {
          "id": "guest-dawit",
          "name": "Dawit Tadesse",
          "title": "Founder",
          "company": "Nile Cold Chain",
          "bio": "Mechanical engineer turned logistics founder.",
          "industry": "Agricultural Logistics"
        },
        "insights": [
          {
            "id": "ins-1",
            "episodeId": "ep-101",
            "title": "Decoupling Fleet Ownership",
            "summary": "Telemetry retrofits save capital.",
            "category": "Operations",
            "takeaways": ["Telemetry is essential"]
          }
        ],
        "quotations": [
          {
            "id": "q-1",
            "episodeId": "ep-101",
            "amharicQuote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት አይደለም።",
            "englishTranslation": "The real test in logistics is not buying trucks.",
            "speaker": "Dawit Tadesse",
            "timestampSeconds": 1420,
            "context": "Context quote."
          }
        ]
      },
      {
        "id": "ep-102",
        "title": "Merchant Cash Software in Merkato",
        "podcastTitle": "Meri Business Series",
        "episodeNumber": 102,
        "durationMinutes": 62,
        "publishedAt": "2026-09-26T10:00:00.000Z",
        "summary": "Offline bookkeeping for cash traders.",
        "isFeatured": false,
        "tags": ["Fintech", "B2B"],
        "guest": {
          "id": "guest-bethlehem",
          "name": "Bethlehem Assefa",
          "title": "Co-founder",
          "company": "Walia Merchant Tech",
          "bio": "Product architect in Merkato.",
          "industry": "Retail Fintech"
        },
        "insights": [],
        "quotations": []
      }
    ]
  }
  ''';

  Widget buildTestWidget({LocalJsonDataSource? customDataSource}) {
    final dataSource = customDataSource ??
        LocalJsonDataSource(
          loader: (path) async => testSampleJson,
        );

    final router = GoRouter(
      initialLocation: '/explore',
      routes: [
        GoRoute(
          path: '/explore',
          builder: (context, state) => const ExploreScreen(),
        ),
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
      ],
      child: MaterialApp.router(
        routerConfig: router,
      ),
    );
  }

  group('ExploreScreen Functional Tests', () {
    testWidgets('Displays all episodes and topic chips initially', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      expect(find.text('Explore Knowledge'), findsOneWidget);
      expect(find.text('CURATED INDUSTRY THEMES'), findsOneWidget);
      expect(find.text('All'), findsOneWidget);
      expect(find.text('Agritech'), findsOneWidget);
      expect(find.text('Fintech'), findsOneWidget);

      // Initially shows both episodes
      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.text('Merchant Cash Software in Merkato'), findsOneWidget);
      expect(find.text('SHOWING 2 EPISODES'), findsOneWidget);
    });

    testWidgets('Searches by episode title or guest name reactively', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      // Search by guest name "Dawit"
      final searchField = find.byType(TextField);
      await tester.enterText(searchField, 'Dawit');
      await tester.pumpAndSettle();

      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.text('Merchant Cash Software in Merkato'), findsNothing);
      expect(find.text('SHOWING 1 EPISODE'), findsOneWidget);

      // Search by title "Merchant"
      await tester.enterText(searchField, 'Merchant');
      await tester.pumpAndSettle();

      expect(find.text('Merchant Cash Software in Merkato'), findsOneWidget);
      expect(find.text('Scaling Cold Chain Logistics'), findsNothing);
    });

    testWidgets('Clears search query via suffix close button', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      final searchField = find.byType(TextField);
      await tester.enterText(searchField, 'Dawit');
      await tester.pumpAndSettle();

      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.text('Merchant Cash Software in Merkato'), findsNothing);

      // Tap clear icon button
      final clearButton = find.byIcon(Icons.close_rounded);
      expect(clearButton, findsOneWidget);
      await tester.tap(clearButton);
      await tester.pumpAndSettle();

      // Verify search input is cleared and all episodes are restored
      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.text('Merchant Cash Software in Merkato'), findsOneWidget);
      expect(find.text('SHOWING 2 EPISODES'), findsOneWidget);
    });

    testWidgets('Filters by selecting category chip and restores with All', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      // Tap "Agritech" category chip
      await tester.tap(find.text('Agritech'));
      await tester.pumpAndSettle();

      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.text('Merchant Cash Software in Merkato'), findsNothing);

      // Tap "Fintech" category chip
      await tester.tap(find.text('Fintech'));
      await tester.pumpAndSettle();

      expect(find.text('Merchant Cash Software in Merkato'), findsOneWidget);
      expect(find.text('Scaling Cold Chain Logistics'), findsNothing);

      // Tap "All" to reset category filter
      await tester.tap(find.text('All'));
      await tester.pumpAndSettle();

      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.text('Merchant Cash Software in Merkato'), findsOneWidget);
      expect(find.text('SHOWING 2 EPISODES'), findsOneWidget);
    });

    testWidgets('Supports combined query and category filtering correctly', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      // Filter by "Agritech"
      await tester.tap(find.text('Agritech'));
      await tester.pumpAndSettle();
      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);

      // Query "Dawit" within "Agritech" -> matches
      final searchField = find.byType(TextField);
      await tester.enterText(searchField, 'Dawit');
      await tester.pumpAndSettle();
      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);

      // Query "Bethlehem" within "Agritech" -> zero matches (mismatch)
      await tester.enterText(searchField, 'Bethlehem');
      await tester.pumpAndSettle();
      expect(find.text('No Knowledge Records Found'), findsOneWidget);
      expect(find.text('Scaling Cold Chain Logistics'), findsNothing);
      expect(find.text('Merchant Cash Software in Merkato'), findsNothing);
    });

    testWidgets('Displays empty search state and resets filters', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      final searchField = find.byType(TextField);
      await tester.enterText(searchField, 'NonExistentTerm');
      await tester.pumpAndSettle();

      expect(find.text('No Knowledge Records Found'), findsOneWidget);
      expect(find.text('Reset All Filters'), findsOneWidget);

      // Tap Reset All Filters
      await tester.tap(find.text('Reset All Filters'));
      await tester.pumpAndSettle();

      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.text('Merchant Cash Software in Merkato'), findsOneWidget);
    });

    testWidgets('Tapping episode card navigates to episode details screen', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      // Tap first episode card
      await tester.tap(find.text('Scaling Cold Chain Logistics'));
      await tester.pumpAndSettle();

      // Verify EpisodeDetailScreen contents
      expect(find.text('Executive Summary'), findsOneWidget);
      expect(find.text('Dawit Tadesse'), findsWidgets);
      expect(find.text('Mechanical engineer turned logistics founder.'), findsOneWidget);
    });
  });
}
