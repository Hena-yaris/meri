import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../business_knowledge/data/providers.dart';
import '../../../business_knowledge/domain/models/episode.dart';
import '../../../business_knowledge/domain/models/insight.dart';

/// Consolidated data model for the Home screen editorial layout.
class HomeFeedData {
  const HomeFeedData({
    required this.featuredEpisode,
    required this.episodes,
    required this.insights,
  });

  final Episode? featuredEpisode;
  final List<Episode> episodes;
  final List<Insight> insights;
}

/// Fetches and coordinates data needed for the Home feed.
final homeFeedProvider = FutureProvider<HomeFeedData>((ref) async {
  final repository = ref.watch(knowledgeRepositoryProvider);

  final featuredFuture = repository.getFeaturedEpisode();
  final episodesFuture = repository.getEpisodes();
  final insightsFuture = repository.getFeaturedInsights();

  final results = await Future.wait([
    featuredFuture,
    episodesFuture,
    insightsFuture,
  ]);

  return HomeFeedData(
    featuredEpisode: results[0] as Episode?,
    episodes: results[1] as List<Episode>,
    insights: results[2] as List<Insight>,
  );
});

/// Controller providing actions for the Home screen (refresh, search, etc.).
class HomeController {
  HomeController(this.ref);

  final Ref ref;

  /// Force refreshes the data source and invalidates all feed providers.
  Future<void> refresh() async {
    final dataSource = ref.read(localJsonDataSourceProvider);
    dataSource.clearCache();
    ref.invalidate(homeFeedProvider);
    ref.invalidate(episodesProvider);
    ref.invalidate(featuredEpisodeProvider);
    ref.invalidate(featuredInsightsProvider);
    await ref.read(homeFeedProvider.future);
  }
}

final homeControllerProvider = Provider<HomeController>((ref) {
  return HomeController(ref);
});
