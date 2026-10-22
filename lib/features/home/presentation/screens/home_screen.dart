import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/async_value_widget.dart';
import '../../../../core/widgets/meri_wordmark.dart';
import '../controllers/home_controller.dart';
import '../widgets/episode_card.dart';
import '../widgets/featured_episode_hero.dart';
import '../widgets/insight_preview_strip.dart';
import '../widgets/section_header.dart';

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
        actions: [
          IconButton(
            tooltip: 'Search episodes',
            icon: const Icon(Icons.search_rounded, size: 22),
            onPressed: () => context.go('/explore'),
          ),
          IconButton(
            tooltip: 'Refresh library',
            icon: const Icon(Icons.refresh_rounded, size: 22),
            onPressed: () => ref.read(homeControllerProvider).refresh(),
          ),
          const SizedBox(width: AppSpacing.xs),
        ],
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
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.only(
                top: AppSpacing.sm,
                bottom: AppSpacing.xxl,
              ),
              children: [
                // 1. Featured Masterclass Section
                if (feed.featuredEpisode != null) ...[
                  const SectionHeader(
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

                // 2. High Priority Insights Strip
                if (feed.insights.isNotEmpty) ...[
                  const SectionHeader(
                    title: 'Actionable Insights',
                    eyebrow: 'Lessons & Strategies',
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  InsightPreviewStrip(
                    insights: feed.insights,
                    onInsightTap: (insight) {
                      _showInsightDetailsBottomSheet(context, insight, isDark);
                    },
                  ),
                  const SizedBox(height: AppSpacing.lg),
                ],

                // 3. Recent Episodes Library
                const SectionHeader(
                  title: 'Interview Archive',
                  eyebrow: 'Long-Form Business Transcripts',
                ),
                const SizedBox(height: AppSpacing.xs),
                ...feed.episodes.map((episode) {
                  return EpisodeCard(
                    episode: episode,
                    onTap: () {
                      context.push('/episode/${episode.id}');
                    },
                  );
                }),
                const SizedBox(height: AppSpacing.xl),

                // 4. Sample Dataset Disclaimer Notice
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
                  child: Container(
                    padding: const EdgeInsets.all(AppSpacing.md),
                    decoration: BoxDecoration(
                      color: isDark
                          ? AppColors.darkSurfaceElevated
                          : AppColors.archiveSandLight,
                      borderRadius: AppRadius.cardRadius,
                      border: Border.all(
                        color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
                      ),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          Icons.info_outline_rounded,
                          size: 18,
                          color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: Text(
                            'DEVELOPMENT SAMPLE DATASET: Illustrative synthetic profiles and insights modeled for foundation validation. Not actual Meri recordings.',
                            style: AppTypography.labelSmall(
                              color: isDark
                                  ? AppColors.darkTextMuted
                                  : AppColors.stoneGray,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  void _showInsightDetailsBottomSheet(
    BuildContext context,
    dynamic insight,
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
              const SizedBox(height: AppSpacing.md),
            ],
          ),
        );
      },
    );
  }
}
