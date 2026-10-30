import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/async_value_widget.dart';
import '../../../../core/widgets/meri_section_header.dart';
import '../../../../core/widgets/meri_wordmark.dart';
import '../../../business_knowledge/domain/models/insight.dart';
import '../controllers/home_controller.dart';
import '../widgets/episode_card.dart';
import '../widgets/executive_takeaways_list.dart';
import '../widgets/featured_episode_hero.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final feedAsync = ref.watch(homeFeedProvider);
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: const MeriWordmark(
          isCompact: true,
          tagline: 'The business behind the story.',
        ),
      ),
      body: RefreshIndicator(
        color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
        backgroundColor: isDark ? AppColors.darkSurface : AppColors.paperLight,
        onRefresh: () => ref.read(homeControllerProvider).refresh(),
        child: AsyncValueWidget<HomeFeedData>(
          value: feedAsync,
          loadingMessage: 'Loading verified entrepreneur interviews...',
          emptyMessage: 'No podcast records currently loaded.',
          isEmpty: (data) => data.episodes.isEmpty,
          onRetry: () => ref.read(homeControllerProvider).refresh(),
          data: (feed) {
            final archiveEpisodes = feed.episodes
                .where((ep) => ep.id != feed.featuredEpisode?.id)
                .toList();

            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.only(
                top: AppSpacing.sm,
                bottom: AppSpacing.xxl,
              ),
              children: [
                // 1. Featured Masterclass Section
                if (feed.featuredEpisode != null) ...[
                  const MeriSectionHeader(
                    title: 'Masterclass Spotlight',
                    eyebrow: 'Verified Entrepreneur Journey',
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  FeaturedEpisodeHero(
                    episode: feed.featuredEpisode!,
                    onTap: () {
                      context.push('/episode/${feed.featuredEpisode!.id}');
                    },
                  ),
                  const SizedBox(height: AppSpacing.lg),
                ],

                // 2. Vertically Flowing Executive Takeaways
                if (feed.insights.isNotEmpty) ...[
                  const MeriSectionHeader(
                    title: 'Executive Takeaways',
                    eyebrow: 'Strategic Insights',
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  ExecutiveTakeawaysList(
                    insights: feed.insights,
                    onInsightTap: (insight) {
                      _showInsightDetailsBottomSheet(context, insight, isDark);
                    },
                  ),
                  const SizedBox(height: AppSpacing.lg),
                ],

                // 3. Interview Archive (Only for genuine non-featured archive episodes)
                if (archiveEpisodes.isNotEmpty) ...[
                  const MeriSectionHeader(
                    title: 'Interview Archive',
                    eyebrow: 'Long-Form Business Transcripts',
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  ...archiveEpisodes.map((episode) {
                    return EpisodeCard(
                      episode: episode,
                      onTap: () {
                        context.push('/episode/${episode.id}');
                      },
                    );
                  }),
                  const SizedBox(height: AppSpacing.xl),
                ] else ...[
                  // Understated Editorial Footer inviting topic exploration
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.md,
                      vertical: AppSpacing.md,
                    ),
                    child: Center(
                      child: Column(
                        children: [
                          const Divider(),
                          const SizedBox(height: AppSpacing.lg),
                          Text(
                            'EXPLORE THEMATIC ARCHIVE',
                            style: AppTypography.eyebrow(
                              color: isDark
                                  ? AppColors.darkTextMuted
                                  : AppColors.stoneGray,
                            ),
                          ),
                          const SizedBox(height: AppSpacing.xs),
                          Text(
                            'Browse our index of entrepreneurial themes, operational frameworks, and verified business insights.',
                            textAlign: TextAlign.center,
                            style: AppTypography.bodySmall(
                              color: isDark
                                  ? AppColors.darkTextSecondary
                                  : AppColors.stoneGray,
                            ),
                          ),
                          const SizedBox(height: AppSpacing.md),
                          OutlinedButton.icon(
                            onPressed: () => context.go('/explore'),
                            icon: const Icon(Icons.explore_outlined, size: 18),
                            label: const Text('Browse Topic Index'),
                          ),
                          const SizedBox(height: AppSpacing.sm),
                        ],
                      ),
                    ),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }

  void _showInsightDetailsBottomSheet(
    BuildContext context,
    Insight insight,
    bool isDark,
  ) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: isDark ? AppColors.darkSurface : AppColors.paperLight,
      shape: const RoundedRectangleBorder(
        borderRadius: AppRadius.sheetRadius,
      ),
      builder: (context) {
        return Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                insight.category.toUpperCase(),
                style: AppTypography.eyebrow(
                  color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                insight.title,
                style: AppTypography.titleLarge(
                  color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                insight.summary,
                style: AppTypography.bodyMedium(
                  color: isDark ? AppColors.darkTextSecondary : AppColors.stoneGray,
                ),
              ),
              if (insight.practicalAction != null && insight.practicalAction!.trim().isNotEmpty) ...[
                const SizedBox(height: AppSpacing.md),
                Container(
                  padding: const EdgeInsets.all(AppSpacing.sm),
                  decoration: BoxDecoration(
                    color: isDark ? AppColors.darkSurfaceElevated : AppColors.archiveSandLight,
                    borderRadius: AppRadius.roundedSm,
                    border: Border.all(
                      color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
                    ),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(
                        Icons.lightbulb_outline_rounded,
                        size: 16,
                        color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                        child: Text(
                          insight.practicalAction!,
                          style: AppTypography.bodySmall(
                            color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: AppSpacing.md),
            ],
          ),
        );
      },
    );
  }
}
