import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../business_knowledge/data/providers.dart';
import '../../business_knowledge/domain/models/episode.dart';
import '../domain/repositories/bookmarks_repository.dart';
import 'datasources/bookmarks_local_data_source.dart';
import 'repositories/local_bookmarks_repository.dart';

/// Provider for the local storage data source backing bookmarks.
final bookmarksLocalDataSourceProvider = Provider<BookmarksLocalDataSource>((ref) {
  return SharedPreferencesBookmarksDataSource();
});

/// Provider for the [BookmarksRepository] abstraction.
final bookmarksRepositoryProvider = Provider<BookmarksRepository>((ref) {
  final dataSource = ref.watch(bookmarksLocalDataSourceProvider);
  return LocalBookmarksRepository(dataSource: dataSource);
});

/// AsyncNotifier managing the reactive in-memory and persistent set of bookmarked episode IDs.
class BookmarksNotifier extends AsyncNotifier<Set<String>> {
  @override
  Future<Set<String>> build() async {
    final repository = ref.watch(bookmarksRepositoryProvider);
    return repository.getBookmarkedEpisodeIds();
  }

  /// Adds [episodeId] to bookmarks if not already saved.
  Future<void> addBookmark(String episodeId) async {
    final cleanId = episodeId.trim();
    if (cleanId.isEmpty) return;

    final current = state.value ?? <String>{};
    if (current.contains(cleanId)) return;

    // Optimistic reactive update
    final updated = Set<String>.from(current)..add(cleanId);
    state = AsyncData(updated);

    final repository = ref.read(bookmarksRepositoryProvider);
    try {
      await repository.addBookmark(cleanId);
    } catch (e, stackTrace) {
      debugPrint('BookmarksNotifier: failed to add bookmark: $e\n$stackTrace');
      state = AsyncData(current); // Rollback on error
    }
  }

  /// Removes [episodeId] from bookmarks if currently saved.
  Future<void> removeBookmark(String episodeId) async {
    final cleanId = episodeId.trim();
    if (cleanId.isEmpty) return;

    final current = state.value ?? <String>{};
    if (!current.contains(cleanId)) return;

    // Optimistic reactive update
    final updated = Set<String>.from(current)..remove(cleanId);
    state = AsyncData(updated);

    final repository = ref.read(bookmarksRepositoryProvider);
    try {
      await repository.removeBookmark(cleanId);
    } catch (e, stackTrace) {
      debugPrint('BookmarksNotifier: failed to remove bookmark: $e\n$stackTrace');
      state = AsyncData(current); // Rollback on error
    }
  }

  /// Toggles the bookmark state of [episodeId].
  Future<void> toggleBookmark(String episodeId) async {
    final cleanId = episodeId.trim();
    if (cleanId.isEmpty) return;

    final current = state.value ?? <String>{};
    if (current.contains(cleanId)) {
      await removeBookmark(cleanId);
    } else {
      await addBookmark(cleanId);
    }
  }
}

/// Provider exposing the reactive set of bookmarked episode IDs.
final bookmarksProvider =
    AsyncNotifierProvider<BookmarksNotifier, Set<String>>(
  BookmarksNotifier.new,
);

/// Resolves the actual [Episode] objects corresponding to the current bookmarked IDs.
///
/// Unresolved or deleted episode IDs are omitted cleanly without throwing exceptions.
final bookmarkedEpisodesProvider = FutureProvider<List<Episode>>((ref) async {
  final bookmarkedIds = await ref.watch(bookmarksProvider.future);

  if (bookmarkedIds.isEmpty) {
    return <Episode>[];
  }

  final knowledgeRepository = ref.watch(knowledgeRepositoryProvider);
  final allEpisodes = await knowledgeRepository.getEpisodes();

  final episodesMap = {for (final ep in allEpisodes) ep.id: ep};
  final resolved = <Episode>[];
  for (final id in bookmarkedIds) {
    final episode = episodesMap[id];
    if (episode != null) {
      resolved.add(episode);
    }
  }
  return resolved;
});
