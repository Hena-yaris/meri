import 'dart:convert';
import 'package:flutter/services.dart';
import '../../../../core/constants/app_assets.dart';
import '../../domain/models/episode.dart';
import '../../domain/models/insight.dart';

/// Contract or function for loading raw JSON strings, allowing clean unit testing
/// without needing an active Flutter binding.
typedef AssetStringLoader = Future<String> Function(String path);

/// Data source responsible for loading and decoding bundled JSON business records.
class LocalJsonDataSource {
  LocalJsonDataSource({
    AssetStringLoader? loader,
    this._assetPath = AppAssets.sampleEpisodesJson,
  }) : _loader = loader ?? rootBundle.loadString;

  final AssetStringLoader _loader;
  final String _assetPath;

  List<Episode>? _cachedEpisodes;

  /// Loads and parses the bundled episodes JSON.
  Future<List<Episode>> loadEpisodes({bool forceRefresh = false}) async {
    if (_cachedEpisodes != null && !forceRefresh) {
      return _cachedEpisodes!;
    }

    try {
      final jsonString = await _loader(_assetPath);
      final dynamic decoded = jsonDecode(jsonString);

      if (decoded is! Map<String, dynamic> || !decoded.containsKey('episodes')) {
        throw const FormatException('Invalid JSON payload: missing "episodes" key');
      }

      final rawList = decoded['episodes'] as List<dynamic>;
      final episodes = rawList
          .map((item) => Episode.fromJson(item as Map<String, dynamic>))
          .toList();

      _cachedEpisodes = episodes;
      return episodes;
    } catch (e) {
      throw Exception('Failed to load local knowledge records from $_assetPath: $e');
    }
  }

  /// Extracts all insights across all loaded episodes.
  Future<List<Insight>> loadAllInsights() async {
    final episodes = await loadEpisodes();
    return episodes.expand((ep) => ep.insights).toList();
  }

  /// Clears in-memory cache.
  void clearCache() {
    _cachedEpisodes = null;
  }
}
