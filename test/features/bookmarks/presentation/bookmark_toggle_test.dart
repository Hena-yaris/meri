import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:meri/features/bookmarks/data/providers.dart';
import 'package:meri/features/bookmarks/domain/repositories/bookmarks_repository.dart';
import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';
import 'package:meri/features/business_knowledge/data/providers.dart';
import 'package:meri/features/business_knowledge/domain/models/episode.dart';
import 'package:meri/features/business_knowledge/domain/models/guest.dart';
import 'package:meri/features/business_knowledge/presentation/screens/episode_detail_screen.dart';
import 'package:meri/features/home/presentation/widgets/episode_card.dart';

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
      "tags": ["Logistics"],
      "guest": {
        "id": "g-101",
        "name": "Dawit Tadesse",
        "title": "Director",
        "company": "Nile Cold Chain",
        "bio": "Logistics entrepreneur."
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

  group('Bookmark Toggle Interaction Tests', () {
    testWidgets('EpisodeCard displays bookmark state and toggles without triggering card onTap', (tester) async {
      final repository = FakeBookmarksRepository({});
      bool cardTapped = false;

      final testEpisode = Episode(
        id: 'ep-101',
        title: 'Scaling Cold Chain Logistics',
        podcastTitle: 'Meri Series',
        episodeNumber: 101,
        durationMinutes: 74,
        publishedAt: DateTime.parse('2026-09-12T08:00:00.000Z'),
        summary: 'Agricultural freight in Ethiopia.',
        isFeatured: true,
        tags: const ['Logistics'],
        guest: const Guest(
          id: 'g-101',
          name: 'Dawit Tadesse',
          title: 'Director',
          company: 'Nile Cold Chain',
          bio: 'Logistics entrepreneur.',
        ),
        insights: const [],
        quotations: const [],
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            bookmarksRepositoryProvider.overrideWithValue(repository),
          ],
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

      // Initially not bookmarked
      expect(find.byIcon(Icons.bookmark_border_rounded), findsOneWidget);
      expect(find.byIcon(Icons.bookmark_rounded), findsNothing);

      // Tap the bookmark button
      final bookmarkButton = find.bySemanticsLabel('Bookmark episode');
      expect(bookmarkButton, findsOneWidget);
      await tester.tap(bookmarkButton);
      await tester.pumpAndSettle();

      // Bookmark button tapped -> card onTap should NOT be triggered
      expect(cardTapped, isFalse);

      // Now bookmarked
      expect(find.byIcon(Icons.bookmark_rounded), findsOneWidget);
      expect(find.byIcon(Icons.bookmark_border_rounded), findsNothing);

      // Now tap the card body (not the bookmark button)
      final titleFinder = find.text('Scaling Cold Chain Logistics');
      await tester.tap(titleFinder);
      await tester.pumpAndSettle();

      // Card onTap should now be triggered
      expect(cardTapped, isTrue);
    });

    testWidgets('EpisodeDetailScreen appBar action toggles bookmark reactively', (tester) async {
      final repository = FakeBookmarksRepository({'ep-101'});
      final dataSource = LocalJsonDataSource(loader: (_) async => testSampleJson);

      final router = GoRouter(
        initialLocation: '/episode/ep-101',
        routes: [
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
            bookmarksRepositoryProvider.overrideWithValue(repository),
            localJsonDataSourceProvider.overrideWithValue(dataSource),
          ],
          child: MaterialApp.router(
            routerConfig: router,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Initially saved -> Icons.bookmark_rounded
      expect(find.byIcon(Icons.bookmark_rounded), findsOneWidget);

      // Tap bookmark button in AppBar action to unbookmark
      final bookmarkAction = find.byTooltip('Remove bookmark');
      expect(bookmarkAction, findsOneWidget);
      await tester.tap(bookmarkAction);
      await tester.pumpAndSettle();

      // Now should show bookmark_border_rounded and tooltip 'Bookmark episode'
      expect(find.byIcon(Icons.bookmark_border_rounded), findsOneWidget);
      expect(find.byTooltip('Bookmark episode'), findsOneWidget);
      expect(repository.isBookmarked('ep-101'), completion(isFalse));

      // Tap again to re-bookmark
      await tester.tap(find.byTooltip('Bookmark episode'));
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.bookmark_rounded), findsOneWidget);
      expect(find.byTooltip('Remove bookmark'), findsOneWidget);
      expect(repository.isBookmarked('ep-101'), completion(isTrue));
    });
  });
}
