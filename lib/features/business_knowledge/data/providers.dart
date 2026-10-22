import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../domain/models/episode.dart';
import '../domain/models/insight.dart';
import '../domain/repositories/knowledge_repository.dart';
import 'datasources/local_json_data_source.dart';
import 'repositories/local_knowledge_repository.dart';

/// Provider for the local JSON data source.
final localJsonDataSourceProvider = Provider<LocalJsonDataSource>((ref) {
  return LocalJsonDataSource();
});

/// Provider for the [KnowledgeRepository] interface.
/// Decouples UI and presentation from whether data is supplied by JSON or Supabase.
final knowledgeRepositoryProvider = Provider<KnowledgeRepository>((ref) {
  final dataSource = ref.watch(localJsonDataSourceProvider);
  return LocalKnowledgeRepository(dataSource: dataSource);
});

/// Provides the full list of episodes, loaded asynchronously.
final episodesProvider = FutureProvider<List<Episode>>((ref) async {
  final repository = ref.watch(knowledgeRepositoryProvider);
  return repository.getEpisodes();
});

/// Provides the featured masterclass episode for the home hero section.
final featuredEpisodeProvider = FutureProvider<Episode?>((ref) async {
  final repository = ref.watch(knowledgeRepositoryProvider);
  return repository.getFeaturedEpisode();
});

/// Provides featured insights across all episodes.
final featuredInsightsProvider = FutureProvider<List<Insight>>((ref) async {
  final repository = ref.watch(knowledgeRepositoryProvider);
  return repository.getFeaturedInsights();
});

/// Provides a single episode by its unique identifier.
final episodeByIdProvider =
    FutureProvider.family<Episode?, String>((ref, id) async {
  final repository = ref.watch(knowledgeRepositoryProvider);
  return repository.getEpisodeById(id);
});


// =========================================================================
// Explore Search & Filtering State Providers
// =========================================================================

/// State notifier managing the active search query in the Explore screen.
class ExploreSearchQueryNotifier extends Notifier<String> {
  @override
  String build() => '';

  void setQuery(String query) => state = query;
  void clear() => state = '';
}

final exploreSearchQueryProvider =
    NotifierProvider<ExploreSearchQueryNotifier, String>(
  ExploreSearchQueryNotifier.new,
);

/// State notifier managing the active category/topic filter in Explore.
/// A `null` value indicates that all categories are shown.
class ExploreSelectedTopicNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  void selectTopic(String? topic) {
    if (topic == null || topic.toLowerCase() == 'all') {
      state = null;
    } else if (state == topic) {
      // Toggle off when re-tapping active topic
      state = null;
    } else {
      state = topic;
    }
  }

  void clear() => state = null;
}

final exploreSelectedTopicProvider =
    NotifierProvider<ExploreSelectedTopicNotifier, String?>(
  ExploreSelectedTopicNotifier.new,
);

/// Provides the list of episodes derived from the active search query and topic filter.
final exploreFilteredEpisodesProvider =
    FutureProvider<List<Episode>>((ref) async {
  final repository = ref.watch(knowledgeRepositoryProvider);
  final query = ref.watch(exploreSearchQueryProvider);
  final topic = ref.watch(exploreSelectedTopicProvider);

  return repository.searchEpisodes(query, category: topic);
});
