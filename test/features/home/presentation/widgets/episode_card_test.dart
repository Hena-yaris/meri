import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:meri/features/bookmarks/data/providers.dart';
import 'package:meri/features/bookmarks/domain/repositories/bookmarks_repository.dart';
import 'package:meri/features/business_knowledge/domain/models/episode.dart';
import 'package:meri/features/business_knowledge/domain/models/guest.dart';
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

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  final testEpisode = Episode(
    id: 'ep-199',
    title: 'Turning Vocational Craft into Scalable Enterprise',
    podcastTitle: 'Meri Podcast',
    episodeNumber: 199,
    durationMinutes: 86,
    publishedAt: DateTime.parse('2024-09-01T00:00:00.000Z'),
    summary: 'Wengelawit (Liya) Gole details formalizing curriculum, institutionalizing apprenticeships, and separating busywork from productive execution.',
    guest: const Guest(
      id: 'guest-liya-gole',
      name: 'Wengelawit (Liya) Gole',
      title: 'Founder & CEO',
      company: 'International Makeup School & Liya Gole Beauty',
      bio: 'Pioneering Ethiopian beauty entrepreneur.',
    ),
    insights: const [],
    quotations: const [],
    tags: const ['Vocational Training', 'Service Operations'],
    isFeatured: true,
  );

  Widget buildCardWidget({
    required Episode episode,
    VoidCallback? onTap,
    Set<String> bookmarkedIds = const {},
    TextScaler? textScaler,
  }) {
    final repository = FakeBookmarksRepository(bookmarkedIds);

    Widget widget = ProviderScope(
      overrides: [
        bookmarksRepositoryProvider.overrideWithValue(repository),
      ],
      child: MaterialApp(
        home: Scaffold(
          body: EpisodeCard(
            episode: episode,
            onTap: onTap,
          ),
        ),
      ),
    );

    if (textScaler != null) {
      widget = MediaQuery(
        data: MediaQueryData(textScaler: textScaler),
        child: widget,
      );
    }

    return widget;
  }

  group('EpisodeCard Editorial Redesign Tests', () {
    testWidgets('renders subdued metadata, primary headline, guest organization, summary, and understated topics', semanticsEnabled: true, (tester) async {
      await tester.pumpWidget(
        buildCardWidget(
          episode: testEpisode,
          onTap: () {},
        ),
      );
      await tester.pumpAndSettle();

      // 1. Subdued metadata
      expect(find.text('EPISODE #199 • 1H 26M'), findsOneWidget);

      // 2. Primary headline
      expect(
        find.text('Turning Vocational Craft into Scalable Enterprise'),
        findsOneWidget,
      );

      // 3. Guest name and organization
      expect(
        find.text('Wengelawit (Liya) Gole • International Makeup School & Liya Gole Beauty'),
        findsOneWidget,
      );

      // 4. Concise summary
      expect(
        find.text(
          'Wengelawit (Liya) Gole details formalizing curriculum, institutionalizing apprenticeships, and separating busywork from productive execution.',
        ),
        findsOneWidget,
      );

      // 5. Understated topic labels
      expect(find.text('VOCATIONAL TRAINING  •  SERVICE OPERATIONS'), findsOneWidget);

      // 6. Bookmark control
      expect(find.bySemanticsLabel('Bookmark episode'), findsOneWidget);
    });

    testWidgets('bookmark button has minimum 48x48 hit target and toggles without triggering card onTap', (tester) async {
      var cardTapped = false;

      await tester.pumpWidget(
        buildCardWidget(
          episode: testEpisode,
          onTap: () => cardTapped = true,
        ),
      );
      await tester.pumpAndSettle();

      final bookmarkFinder = find.bySemanticsLabel('Bookmark episode');
      expect(bookmarkFinder, findsOneWidget);

      // Check minimum 48x48 logical pixels
      final buttonSize = tester.getSize(bookmarkFinder);
      expect(buttonSize.width, greaterThanOrEqualTo(48.0));
      expect(buttonSize.height, greaterThanOrEqualTo(48.0));

      // Tap bookmark
      await tester.tap(bookmarkFinder);
      await tester.pumpAndSettle();

      // Card onTap must NOT be triggered
      expect(cardTapped, isFalse);

      // Semantics updated to Remove bookmark
      expect(find.bySemanticsLabel('Remove bookmark'), findsOneWidget);
      expect(find.byIcon(Icons.bookmark_rounded), findsOneWidget);

      // Tapping card body triggers card onTap
      await tester.tap(find.text('Turning Vocational Craft into Scalable Enterprise'));
      await tester.pumpAndSettle();
      expect(cardTapped, isTrue);
    });

    testWidgets('adapts under 1.5x accessibility text scale without RenderFlex overflow', (tester) async {
      await tester.pumpWidget(
        buildCardWidget(
          episode: testEpisode,
          textScaler: const TextScaler.linear(1.5),
        ),
      );
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(
        find.text('Turning Vocational Craft into Scalable Enterprise'),
        findsOneWidget,
      );
      expect(find.text('EPISODE #199 • 1H 26M'), findsOneWidget);
    });
  });
}
