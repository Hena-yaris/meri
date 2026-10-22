import '../../domain/models/episode.dart';
import '../../domain/models/insight.dart';
import '../../domain/repositories/knowledge_repository.dart';
import '../datasources/local_json_data_source.dart';

/// Concrete implementation of [KnowledgeRepository] pulling from bundled JSON assets.
class LocalKnowledgeRepository implements KnowledgeRepository {
  LocalKnowledgeRepository({required this._dataSource});

  final LocalJsonDataSource _dataSource;

  @override
  Future<List<Episode>> getEpisodes() async {
    final episodes = await _dataSource.loadEpisodes();
    // Return sorted newest first
    final sorted = List<Episode>.from(episodes)
      ..sort((a, b) => b.publishedAt.compareTo(a.publishedAt));
    return sorted;
  }

  @override
  Future<Episode?> getEpisodeById(String id) async {
    final episodes = await _dataSource.loadEpisodes();
    for (final episode in episodes) {
      if (episode.id == id) {
        return episode;
      }
    }
    return null;
  }

  @override
  Future<Episode?> getFeaturedEpisode() async {
    final episodes = await _dataSource.loadEpisodes();
    if (episodes.isEmpty) return null;

    for (final ep in episodes) {
      if (ep.isFeatured) return ep;
    }
    return episodes.first;
  }

  @override
  Future<List<Insight>> getFeaturedInsights() async {
    final episodes = await _dataSource.loadEpisodes();
    final allInsights = <Insight>[];
    for (final ep in episodes) {
      allInsights.addAll(ep.insights);
    }
    return allInsights;
  }

  @override
  Future<List<Episode>> searchEpisodes(String query, {String? category}) async {
    final trimmedQuery = query.trim().toLowerCase();
    final trimmedCategory = category?.trim().toLowerCase();

    final episodes = await getEpisodes();

    return episodes.where((ep) {
      // 1. Text Query Filter
      final bool matchesQuery;
      if (trimmedQuery.isEmpty) {
        matchesQuery = true;
      } else {
        final inTitle = ep.title.toLowerCase().contains(trimmedQuery);
        final inSummary = ep.summary.toLowerCase().contains(trimmedQuery);
        final inGuest = ep.guest.name.toLowerCase().contains(trimmedQuery) ||
            ep.guest.company.toLowerCase().contains(trimmedQuery) ||
            (ep.guest.industry?.toLowerCase().contains(trimmedQuery) ?? false);
        final inTags = ep.tags.any((tag) => tag.toLowerCase().contains(trimmedQuery));
        final inInsights = ep.insights.any((ins) =>
            ins.title.toLowerCase().contains(trimmedQuery) ||
            ins.summary.toLowerCase().contains(trimmedQuery));

        matchesQuery = inTitle || inSummary || inGuest || inTags || inInsights;
      }

      // 2. Category / Topic Filter
      final bool matchesCategory;
      if (trimmedCategory == null || trimmedCategory.isEmpty || trimmedCategory == 'all') {
        matchesCategory = true;
      } else {
        matchesCategory = _matchesCategory(ep, trimmedCategory);
      }

      return matchesQuery && matchesCategory;
    }).toList();
  }

  bool _matchesCategory(Episode ep, String category) {
    final catLower = category.toLowerCase();
    if (catLower == 'all') return true;

    // Split compound terms (e.g. "Export & Trade" -> ["export", "trade"])
    final keywords = catLower
        .split(RegExp(r'[\s&,/]+'))
        .where((k) => k.isNotEmpty && k != 'and')
        .toList();

    // Check tags
    for (final tag in ep.tags) {
      final tLower = tag.toLowerCase();
      if (tLower == catLower || tLower.contains(catLower) || catLower.contains(tLower)) {
        return true;
      }
      for (final kw in keywords) {
        if (tLower.contains(kw) || kw.contains(tLower)) {
          return true;
        }
      }
    }

    // Check insight categories
    for (final ins in ep.insights) {
      final iLower = ins.category.toLowerCase();
      if (iLower == catLower || iLower.contains(catLower) || catLower.contains(iLower)) {
        return true;
      }
      for (final kw in keywords) {
        if (iLower.contains(kw) || kw.contains(iLower)) {
          return true;
        }
      }
    }

    // Check guest industry
    final indLower = ep.guest.industry?.toLowerCase();
    if (indLower != null) {
      if (indLower == catLower || indLower.contains(catLower) || catLower.contains(indLower)) {
        return true;
      }
      for (final kw in keywords) {
        if (indLower.contains(kw) || kw.contains(indLower)) {
          return true;
        }
      }
    }

    return false;
  }
}
