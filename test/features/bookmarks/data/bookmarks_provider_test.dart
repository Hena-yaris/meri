import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:meri/features/bookmarks/data/providers.dart';
import 'package:meri/features/bookmarks/domain/repositories/bookmarks_repository.dart';
import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';
import 'package:meri/features/business_knowledge/data/providers.dart';

class InMemoryBookmarksRepository implements BookmarksRepository {
  InMemoryBookmarksRepository([Set<String>? initial])
      : _ids = initial != null ? Set.from(initial) : {};

  final Set<String> _ids;
  bool shouldThrow = false;

  @override
  Future<Set<String>> getBookmarkedEpisodeIds() async {
    if (shouldThrow) throw Exception('Storage error');
    return Set.from(_ids);
  }

  @override
  Future<void> addBookmark(String episodeId) async {
    if (shouldThrow) throw Exception('Storage error');
    _ids.add(episodeId);
  }

  @override
  Future<void> removeBookmark(String episodeId) async {
    if (shouldThrow) throw Exception('Storage error');
    _ids.remove(episodeId);
  }

  @override
  Future<bool> toggleBookmark(String episodeId) async {
    if (_ids.contains(episodeId)) {
      await removeBookmark(episodeId);
      return false;
    } else {
      await addBookmark(episodeId);
      return true;
    }
  }

  @override
  Future<bool> isBookmarked(String episodeId) async {
    return _ids.contains(episodeId);
  }
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
      "summary": "Logistics summary",
      "isFeatured": true,
      "tags": ["Logistics"],
      "guest": {
        "id": "g-101",
        "name": "Dawit Tadesse",
        "title": "Director",
        "company": "Nile Cold Chain",
        "bio": "Logistics leader"
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
      "summary": "Fintech summary",
      "isFeatured": false,
      "tags": ["Fintech"],
      "guest": {
        "id": "g-102",
        "name": "Bethlehem Assefa",
        "title": "CPO",
        "company": "Walia",
        "bio": "Product architect"
      },
      "insights": [],
      "quotations": []
    }
  ]
}
''';

void main() {
  group('BookmarksProvider and BookmarkedEpisodesProvider', () {
    late InMemoryBookmarksRepository repository;
    late ProviderContainer container;

    setUp(() {
      repository = InMemoryBookmarksRepository({'ep-101'});
      final dataSource = LocalJsonDataSource(loader: (_) async => testSampleJson);

      container = ProviderContainer(
        overrides: [
          bookmarksRepositoryProvider.overrideWithValue(repository),
          localJsonDataSourceProvider.overrideWithValue(dataSource),
        ],
      );
    });

    tearDown(() {
      container.dispose();
    });

    test('initial state restores bookmarks from persistence', () async {
      final bookmarks = await container.read(bookmarksProvider.future);
      expect(bookmarks, equals({'ep-101'}));
    });

    test('adding a bookmark updates state reactively', () async {
      await container.read(bookmarksProvider.future);
      await container.read(bookmarksProvider.notifier).addBookmark('ep-102');

      final updated = container.read(bookmarksProvider).value;
      expect(updated, contains('ep-102'));
      expect(await repository.getBookmarkedEpisodeIds(), contains('ep-102'));
    });

    test('removing a bookmark updates state reactively', () async {
      await container.read(bookmarksProvider.future);
      await container.read(bookmarksProvider.notifier).removeBookmark('ep-101');

      final updated = container.read(bookmarksProvider).value;
      expect(updated, isEmpty);
      expect(await repository.getBookmarkedEpisodeIds(), isEmpty);
    });

    test('toggling bookmark adds when absent and removes when present', () async {
      await container.read(bookmarksProvider.future);

      // Toggle off
      await container.read(bookmarksProvider.notifier).toggleBookmark('ep-101');
      expect(container.read(bookmarksProvider).value, isEmpty);

      // Toggle on
      await container.read(bookmarksProvider.notifier).toggleBookmark('ep-101');
      expect(container.read(bookmarksProvider).value, contains('ep-101'));
    });

    test('resolves bookmarked episodes from knowledge repository', () async {
      final episodes = await container.read(bookmarkedEpisodesProvider.future);
      expect(episodes.length, 1);
      expect(episodes.first.id, 'ep-101');
      expect(episodes.first.title, 'Scaling Cold Chain Logistics');
    });

    test('handles unresolved episode IDs safely without crashing', () async {
      // Add an ID that does NOT exist in the knowledge dataset
      await container.read(bookmarksProvider.future);
      await container.read(bookmarksProvider.notifier).addBookmark('ep-non-existent-999');

      final episodes = await container.read(bookmarkedEpisodesProvider.future);
      // ep-101 is resolved, ep-non-existent-999 is safely omitted
      expect(episodes.length, 1);
      expect(episodes.first.id, 'ep-101');
    });

    test('empty bookmark store resolves to empty episode list', () async {
      await container.read(bookmarksProvider.future);
      await container.read(bookmarksProvider.notifier).removeBookmark('ep-101');

      final episodes = await container.read(bookmarkedEpisodesProvider.future);
      expect(episodes, isEmpty);
    });

    test('handles persistence error gracefully by rolling back optimistic update', () async {
      await container.read(bookmarksProvider.future);
      repository.shouldThrow = true;

      // Try adding
      await container.read(bookmarksProvider.notifier).addBookmark('ep-102');
      // State should have rolled back to initial {'ep-101'}
      expect(container.read(bookmarksProvider).value, equals({'ep-101'}));
    });
  });
}
