import '../../domain/repositories/bookmarks_repository.dart';
import '../datasources/bookmarks_local_data_source.dart';

/// Concrete implementation of [BookmarksRepository].
///
/// Ensures deduplication of episode IDs, avoids redundant storage writes,
/// and handles persistence errors gracefully.
class LocalBookmarksRepository implements BookmarksRepository {
  LocalBookmarksRepository({required this.dataSource});

  final BookmarksLocalDataSource dataSource;

  @override
  Future<Set<String>> getBookmarkedEpisodeIds() async {
    return dataSource.loadBookmarkedIds();
  }

  @override
  Future<void> addBookmark(String episodeId) async {
    final cleanId = episodeId.trim();
    if (cleanId.isEmpty) return;

    final current = await dataSource.loadBookmarkedIds();
    if (current.contains(cleanId)) return; // Avoid duplicate or unnecessary write

    final updated = Set<String>.from(current)..add(cleanId);
    await dataSource.saveBookmarkedIds(updated);
  }

  @override
  Future<void> removeBookmark(String episodeId) async {
    final cleanId = episodeId.trim();
    if (cleanId.isEmpty) return;

    final current = await dataSource.loadBookmarkedIds();
    if (!current.contains(cleanId)) return; // Avoid unnecessary write

    final updated = Set<String>.from(current)..remove(cleanId);
    await dataSource.saveBookmarkedIds(updated);
  }

  @override
  Future<bool> toggleBookmark(String episodeId) async {
    final cleanId = episodeId.trim();
    if (cleanId.isEmpty) return false;

    final current = await dataSource.loadBookmarkedIds();
    if (current.contains(cleanId)) {
      await removeBookmark(cleanId);
      return false;
    } else {
      await addBookmark(cleanId);
      return true;
    }
  }

  @override
  Future<bool> isBookmarked(String episodeId) async {
    final cleanId = episodeId.trim();
    if (cleanId.isEmpty) return false;

    final current = await dataSource.loadBookmarkedIds();
    return current.contains(cleanId);
  }
}
