import '../models/episode.dart';
import '../models/insight.dart';

/// Abstract contract governing business knowledge retrieval.
///
/// Implementations may supply data from bundled JSON assets,
/// remote Supabase tables, or local caching layers.
abstract class KnowledgeRepository {
  /// Fetches all verified interview episodes.
  Future<List<Episode>> getEpisodes();

  /// Fetches a specific episode by its unique identifier.
  Future<Episode?> getEpisodeById(String id);

  /// Fetches the currently highlighted / featured masterclass episode.
  Future<Episode?> getFeaturedEpisode();

  /// Retrieves prioritized entrepreneurial insights across episodes.
  Future<List<Insight>> getFeaturedInsights();

  /// Searches episodes by guest name, title, industry, or tags,
  /// with optional category/topic filtering.
  Future<List<Episode>> searchEpisodes(String query, {String? category});
}
