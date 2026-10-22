import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:meri/features/bookmarks/data/providers.dart';
import 'package:meri/features/bookmarks/domain/repositories/bookmarks_repository.dart';
import 'package:meri/features/bookmarks/presentation/screens/bookmarks_screen.dart';
import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';
import 'package:meri/features/business_knowledge/data/providers.dart';
import 'package:meri/features/business_knowledge/presentation/screens/episode_detail_screen.dart';

class FakeBookmarksRepository implements BookmarksRepository {
  FakeBookmarksRepository([Set<String>? initial])
      : _ids = initial != null ? Set.from(initial) : {};

  final Set<String> _ids;

  @override
  Future<Set<String>> getBookmarkedEpisodeIds() async => Set.from(_ids);

  @override
  Future<void> addBookmark(String episodeId) async => _ids.add(episodeId);

  @override
  Future<void> removeBookmark(String episodeId) async => _ids.remove(episodeId);

  @override
  Future<bool> toggleBookmark(String episodeId) async {
    if (_ids.contains(episodeId)) {
      _ids.remove(episodeId);
      return false;
    } else {
      _ids.add(episodeId);
      return true;
    }
  }

  @override
  Future<bool> isBookmarked(String episodeId) async => _ids.contains(episodeId);
}

const testSampleJson = '''
{
  "episodes": [
    {
      "id": "ep-101",
      "title": "Scaling Cold Chain Logistics",
      "podcastTitle": "Meri Series",
      "episodeNumber": 101,
      "durationMinutes": 74,
      "publishedAt": "2026-09-12T08:00:00.000Z",
      "summary": "Agricultural freight in Ethiopia.",
      "isFeatured": true,
      "tags": ["Logistics", "Agritech"],
      "guest": {
        "id": "g-101",
        "name": "Dawit Tadesse",
        "title": "Director",
        "company": "Nile Cold Chain",
        "bio": "Logistics entrepreneur."
      },
      "insights": [],
      "quotations": []
    },
    {
      "id": "ep-102",
      "title": "Merchant Cash Software",
      "podcastTitle": "Meri Series",
      "episodeNumber": 102,
      "durationMinutes": 62,
      "publishedAt": "2026-09-26T10:00:00.000Z",
      "summary": "Fintech in Merkato.",
      "isFeatured": false,
      "tags": ["Fintech"],
      "guest": {
        "id": "g-102",
        "name": "Bethlehem Assefa",
        "title": "CPO",
        "company": "Walia",
        "bio": "Product leader."
      },
      "insights": [],
      "quotations": []
    }
  ]
}
''';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  Widget buildTestWidget({
    required FakeBookmarksRepository bookmarksRepository,
  }) {
    final dataSource = LocalJsonDataSource(
      loader: (_) async => testSampleJson,
    );

    final router = GoRouter(
      initialLocation: '/bookmarks',
      routes: [
        GoRoute(
          path: '/bookmarks',
          builder: (context, state) => const BookmarksScreen(),
        ),
        GoRoute(
          path: '/explore',
          builder: (context, state) => const Scaffold(
            body: Center(child: Text('Explore Screen Destination')),
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

    return ProviderScope(
      overrides: [
        bookmarksRepositoryProvider.overrideWithValue(bookmarksRepository),
        localJsonDataSourceProvider.overrideWithValue(dataSource),
      ],
      child: MaterialApp.router(
        routerConfig: router,
      ),
    );
  }

  group('BookmarksScreen Widget Tests', () {
    testWidgets('renders empty state when no episodes are saved', (tester) async {
      final repository = FakeBookmarksRepository({});
      await tester.pumpWidget(buildTestWidget(bookmarksRepository: repository));
      await tester.pumpAndSettle();

      expect(find.text('No Saved Episodes'), findsOneWidget);
      expect(
        find.text(
          'Save insightful entrepreneur interviews and masterclasses to build your personal business knowledge notebook.',
        ),
        findsOneWidget,
      );
      expect(find.text('Explore Knowledge Archive'), findsOneWidget);
    });

    testWidgets('empty state button navigates to Explore', (tester) async {
      final repository = FakeBookmarksRepository({});
      await tester.pumpWidget(buildTestWidget(bookmarksRepository: repository));
      await tester.pumpAndSettle();

      final exploreButton = find.text('Explore Knowledge Archive');
      expect(exploreButton, findsOneWidget);

      await tester.tap(exploreButton);
      await tester.pumpAndSettle();

      expect(find.text('Explore Screen Destination'), findsOneWidget);
    });

    testWidgets('renders saved episodes list when bookmarks are present', (tester) async {
      final repository = FakeBookmarksRepository({'ep-101'});
      await tester.pumpWidget(buildTestWidget(bookmarksRepository: repository));
      await tester.pumpAndSettle();

      expect(find.text('SAVED KNOWLEDGE ARCHIVE • 1 EPISODE'), findsOneWidget);
      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
      expect(find.textContaining('Dawit Tadesse'), findsOneWidget);
      expect(find.text('No Saved Episodes'), findsNothing);
    });

    testWidgets('tapping saved episode card opens its detail route', (tester) async {
      final repository = FakeBookmarksRepository({'ep-101'});
      await tester.pumpWidget(buildTestWidget(bookmarksRepository: repository));
      await tester.pumpAndSettle();

      // Tap on the episode card (the title area)
      final episodeTitle = find.text('Scaling Cold Chain Logistics');
      await tester.tap(episodeTitle);
      await tester.pumpAndSettle();

      // Should be on EpisodeDetailScreen for ep-101
      expect(find.text('EPISODE #101'), findsOneWidget);
    });

    testWidgets('tapping bookmark button toggles bookmark without triggering card navigation', (tester) async {
      final repository = FakeBookmarksRepository({'ep-101'});
      await tester.pumpWidget(buildTestWidget(bookmarksRepository: repository));
      await tester.pumpAndSettle();

      expect(find.text('SAVED KNOWLEDGE ARCHIVE • 1 EPISODE'), findsOneWidget);

      // Find the bookmark button on the card (Semantics label 'Remove bookmark')
      final bookmarkButton = find.bySemanticsLabel('Remove bookmark');
      expect(bookmarkButton, findsOneWidget);

      await tester.tap(bookmarkButton);
      await tester.pumpAndSettle();

      // Should NOT have navigated to detail screen
      expect(find.text('EPISODE #101'), findsNothing);

      // Screen should have reactively updated to empty state
      expect(find.text('No Saved Episodes'), findsOneWidget);
      expect(find.text('Scaling Cold Chain Logistics'), findsNothing);
    });

    testWidgets('handles unresolved episode IDs safely without crashing', (tester) async {
      // ep-non-existent does not exist in testSampleJson
      final repository = FakeBookmarksRepository({'ep-101', 'ep-non-existent'});
      await tester.pumpWidget(buildTestWidget(bookmarksRepository: repository));
      await tester.pumpAndSettle();

      // Only ep-101 resolved
      expect(find.text('SAVED KNOWLEDGE ARCHIVE • 1 EPISODE'), findsOneWidget);
      expect(find.text('Scaling Cold Chain Logistics'), findsOneWidget);
    });
  });
}
