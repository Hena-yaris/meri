import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Data source contract for persisting bookmarked episode IDs.
abstract class BookmarksLocalDataSource {
  /// Loads all bookmarked episode IDs.
  Future<Set<String>> loadBookmarkedIds();

  /// Persists the updated set of bookmarked episode IDs.
  Future<bool> saveBookmarkedIds(Set<String> ids);
}

/// SharedPreferences implementation of [BookmarksLocalDataSource].
class SharedPreferencesBookmarksDataSource implements BookmarksLocalDataSource {
  SharedPreferencesBookmarksDataSource({this.preferences});

  final SharedPreferences? preferences;

  static const String key = 'meri_bookmarked_episode_ids';

  Future<SharedPreferences> _getPrefs() async {
    return preferences ?? await SharedPreferences.getInstance();
  }

  @override
  Future<Set<String>> loadBookmarkedIds() async {
    try {
      final prefs = await _getPrefs();
      final list = prefs.getStringList(key);
      if (list == null) return <String>{};
      return list.toSet();
    } catch (e, stackTrace) {
      debugPrint('SharedPreferencesBookmarksDataSource: failed to load bookmarks: $e\n$stackTrace');
      return <String>{};
    }
  }

  @override
  Future<bool> saveBookmarkedIds(Set<String> ids) async {
    try {
      final prefs = await _getPrefs();
      return await prefs.setStringList(key, ids.toList());
    } catch (e, stackTrace) {
      debugPrint('SharedPreferencesBookmarksDataSource: failed to save bookmarks: $e\n$stackTrace');
      return false;
    }
  }
}
