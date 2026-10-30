import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/async_value_widget.dart';
import '../../../business_knowledge/domain/models/episode.dart';
import '../../../home/presentation/widgets/episode_card.dart';
import '../../data/providers.dart';

/// Screen displaying the user's saved/bookmarked interview episodes.
class BookmarksScreen extends ConsumerWidget {
  const BookmarksScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final savedEpisodesAsync = ref.watch(bookmarkedEpisodesProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Saved Knowledge',
          style: AppTypography.titleLarge(
            color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
          ),
        ),
      ),
      body: AsyncValueWidget<List<Episode>>(
        value: savedEpisodesAsync,
        loadingMessage: 'Loading saved knowledge...',
        onRetry: () => ref.refresh(bookmarkedEpisodesProvider),
        data: (episodes) {
          if (episodes.isEmpty) {
            return _buildEmptyState(context, isDark);
          }
          return _buildEpisodeList(context, episodes, isDark);
        },
      ),
    );
  }

  Widget _buildEmptyState(BuildContext context, bool isDark) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: isDark
                    ? AppColors.darkSurfaceElevated
                    : AppColors.archiveSandLight,
                shape: BoxShape.circle,
                border: Border.all(
                  color: isDark
                      ? AppColors.darkBorder
                      : AppColors.archiveSandBorder,
                ),
              ),
              child: Icon(
                Icons.bookmark_border_rounded,
                size: 26,
                color: isDark
                    ? AppColors.meriOrangeLight
                    : AppColors.meriOrange,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              'Your Knowledge Notebook is Empty',
              style: AppTypography.titleLarge(
                color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Save insightful entrepreneur interviews and masterclasses to build your personal business knowledge notebook.',
              style: AppTypography.bodySmall(
                color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.lg),
            OutlinedButton.icon(
              onPressed: () => context.go('/explore'),
              icon: const Icon(Icons.explore_outlined, size: 18),
              label: const Text('Explore Knowledge Archive'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEpisodeList(
    BuildContext context,
    List<Episode> episodes,
    bool isDark,
  ) {
    return ListView.builder(
      padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
      itemCount: episodes.length + 1,
      itemBuilder: (context, index) {
        if (index == 0) {
          return Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.md,
              vertical: AppSpacing.sm,
            ),
            child: Text(
              'SAVED KNOWLEDGE ARCHIVE • ${episodes.length} EPISODE${episodes.length == 1 ? '' : 'S'}',
              style: AppTypography.eyebrow(
                color: isDark
                    ? AppColors.meriOrangeLight
                    : AppColors.meriOrange,
              ).copyWith(fontSize: 10),
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
  }
}
