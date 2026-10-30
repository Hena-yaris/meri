import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/async_value_widget.dart';
import '../../../business_knowledge/data/providers.dart';
import '../../../business_knowledge/domain/models/episode.dart';
import '../../../home/presentation/widgets/episode_card.dart';

class ExploreScreen extends ConsumerStatefulWidget {
  const ExploreScreen({super.key});

  static const List<String> topics = [
    'All',
    'Brand Strategy',
    'Creative Economy',
    'Service Operations',
    'Vocational Training',
  ];

  @override
  ConsumerState<ExploreScreen> createState() => _ExploreScreenState();
}

class _ExploreScreenState extends ConsumerState<ExploreScreen> {
  late final TextEditingController _searchController;

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController(
      text: ref.read(exploreSearchQueryProvider),
    );
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _clearSearch() {
    _searchController.clear();
    ref.read(exploreSearchQueryProvider.notifier).clear();
  }

  void _resetAllFilters() {
    _searchController.clear();
    ref.read(exploreSearchQueryProvider.notifier).clear();
    ref.read(exploreSelectedTopicProvider.notifier).clear();
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final activeQuery = ref.watch(exploreSearchQueryProvider);
    final activeTopic = ref.watch(exploreSelectedTopicProvider);
    final episodesAsync = ref.watch(exploreFilteredEpisodesProvider);
    final availableTopics = ref.watch(availableTopicsProvider);
    final displayedTopics = availableTopics.isNotEmpty ? availableTopics : ExploreScreen.topics;

    // Keep text controller synchronized if cleared externally
    ref.listen<String>(exploreSearchQueryProvider, (previous, next) {
      if (next != _searchController.text) {
        _searchController.text = next;
      }
    });

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Explore Knowledge',
          style: AppTypography.titleLarge(
            color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
          ),
        ),
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 1. Search Bar
          Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.md,
              vertical: AppSpacing.xs,
            ),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
              decoration: BoxDecoration(
                color: isDark ? AppColors.darkSurfaceElevated : AppColors.paperLight,
                borderRadius: AppRadius.cardRadius,
                border: Border.all(
                  color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
                ),
              ),
              child: TextField(
                controller: _searchController,
                onChanged: (query) {
                  ref.read(exploreSearchQueryProvider.notifier).setQuery(query);
                },
                style: AppTypography.bodyMedium(
                  color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
                ),
                decoration: InputDecoration(
                  hintText: 'Search by entrepreneur, industry, or concept...',
                  hintStyle: AppTypography.bodySmall(
                    color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
                  ),
                  icon: Icon(
                    Icons.search_rounded,
                    color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                    size: 20,
                  ),
                  suffixIcon: activeQuery.isNotEmpty
                      ? IconButton(
                          tooltip: 'Clear search',
                          icon: Icon(
                            Icons.close_rounded,
                            size: 18,
                            color: isDark
                                ? AppColors.darkTextMuted
                                : AppColors.stoneGray,
                          ),
                          onPressed: _clearSearch,
                        )
                      : null,
                  border: InputBorder.none,
                ),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.xs),

          // 2. Category / Topic Filters
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: Text(
              'CURATED INDUSTRY THEMES',
              style: AppTypography.eyebrow(
                color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          SizedBox(
            height: 38,
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
              scrollDirection: Axis.horizontal,
              itemCount: displayedTopics.length,
              separatorBuilder: (_, _) => const SizedBox(width: AppSpacing.xs),
              itemBuilder: (context, index) {
                final topic = displayedTopics[index];
                final isAll = topic.toLowerCase() == 'all';
                final isSelected = isAll
                    ? (activeTopic == null)
                    : (activeTopic?.toLowerCase() == topic.toLowerCase());

                return FilterChip(
                  label: Text(topic),
                  selected: isSelected,
                  showCheckmark: false,
                  labelStyle: AppTypography.labelSmall(
                    color: isSelected
                        ? (isDark ? AppColors.meriOrangeLight : AppColors.meriOrange)
                        : (isDark ? AppColors.darkTextPrimary : AppColors.inkBlack),
                  ).copyWith(
                    fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                  ),
                  backgroundColor:
                      isDark ? AppColors.darkSurface : AppColors.paperLight,
                  selectedColor: isDark
                      ? AppColors.darkSurfaceElevated
                      : AppColors.archiveSandLight,
                  side: BorderSide(
                    color: isSelected
                        ? (isDark ? AppColors.meriOrangeLight : AppColors.meriOrange)
                        : (isDark ? AppColors.darkBorder : AppColors.archiveSandBorder),
                    width: isSelected ? 1.5 : 1.0,
                  ),
                  shape: const RoundedRectangleBorder(
                    borderRadius: AppRadius.roundedSm,
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
                  onSelected: (_) {
                    ref.read(exploreSelectedTopicProvider.notifier).selectTopic(topic);
                  },
                );
              },
            ),
          ),
          const SizedBox(height: AppSpacing.sm),

          // 3. Results List with Loading, Error, and Custom Empty States
          Expanded(
            child: AsyncValueWidget<List<Episode>>(
              value: episodesAsync,
              loadingMessage: 'Searching entrepreneur knowledge archive...',
              onRetry: () => ref.refresh(exploreFilteredEpisodesProvider),
              data: (episodes) {
                if (episodes.isEmpty) {
                  return _buildNoResultsState(
                    context: context,
                    isDark: isDark,
                    activeQuery: activeQuery,
                    activeTopic: activeTopic,
                  );
                }

                return ListView.builder(
                  padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
                  itemCount: episodes.length + 1,
                  itemBuilder: (context, index) {
                    if (index == 0) {
                      return Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.md,
                          vertical: AppSpacing.xs,
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              'SHOWING ${episodes.length} EPISODE${episodes.length == 1 ? '' : 'S'}',
                              style: AppTypography.eyebrow(
                                color: isDark
                                    ? AppColors.darkTextMuted
                                    : AppColors.stoneGray,
                              ).copyWith(fontSize: 10),
                            ),
                            if (activeQuery.isNotEmpty || activeTopic != null)
                              TextButton(
                                onPressed: _resetAllFilters,
                                style: TextButton.styleFrom(
                                  padding: EdgeInsets.zero,
                                  minimumSize: Size.zero,
                                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                                ),
                                child: Text(
                                  'Clear filters',
                                  style: AppTypography.labelSmall(
                                    color: isDark
                                        ? AppColors.meriOrangeLight
                                        : AppColors.meriOrange,
                                  ),
                                ),
                              ),
                          ],
                        ),
                      );
                    }

                    final episode = episodes[index - 1];
                    return EpisodeCard(
                      episode: episode,
                      onTap: () {
                        context.push('/episode/${episode.id}');
                      },
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNoResultsState({
    required BuildContext context,
    required bool isDark,
    required String activeQuery,
    required String? activeTopic,
  }) {
    final criteria = <String>[];
    if (activeQuery.isNotEmpty) criteria.add('"$activeQuery"');
    if (activeTopic != null) criteria.add('theme: $activeTopic');
    final criteriaString = criteria.isNotEmpty ? criteria.join(' in ') : '';

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.search_off_rounded,
              size: 32,
              color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              'No Knowledge Records Found',
              style: AppTypography.titleMedium(
                color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              criteriaString.isNotEmpty
                  ? 'No interview records matched $criteriaString. Try broader terms or select "All".'
                  : 'No interview records match the selected criteria.',
              style: AppTypography.bodySmall(
                color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.md),
            OutlinedButton.icon(
              onPressed: _resetAllFilters,
              icon: const Icon(Icons.refresh_rounded, size: 16),
              label: const Text('Reset All Filters'),
              style: OutlinedButton.styleFrom(
                foregroundColor:
                    isDark ? AppColors.meriOrangeLight : AppColors.inkBlack,
                side: BorderSide(
                  color: isDark
                      ? AppColors.meriOrangeLight
                      : AppColors.archiveSandBorder,
                ),
                shape: const RoundedRectangleBorder(
                  borderRadius: AppRadius.buttonRadius,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
