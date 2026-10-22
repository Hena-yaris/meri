/// Abstract contract governing bookmark persistence for Meri episodes.
abstract class BookmarksRepository {
  /// Loads all bookmarked episode IDs from persistent storage.
  Future<Set<String>> getBookmarkedEpisodeIds();

  /// Persists a new episode ID to bookmarks.
  Future<void> addBookmark(String episodeId);

  /// Removes an episode ID from bookmarks.
  Future<void> removeBookmark(String episodeId);

  /// Toggles an episode's bookmark status.
  ///
  /// Returns `true` if the episode is now bookmarked, or `false` if removed.
  Future<bool> toggleBookmark(String episodeId);

  /// Checks whether a specific episode ID is currently bookmarked.
  Future<bool> isBookmarked(String episodeId);
}
