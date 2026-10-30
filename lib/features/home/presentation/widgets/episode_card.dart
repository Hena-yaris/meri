import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../bookmarks/data/providers.dart';
import '../../../business_knowledge/domain/models/episode.dart';

/// Editorial list card representing an interview archive episode.
///
/// Styled as an archival paper card in light mode and ink card in dark mode.
class EpisodeCard extends StatelessWidget {
  const EpisodeCard({
    super.key,
    required this.episode,
    this.onTap,
  });

  final Episode episode;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.xs,
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: AppRadius.cardRadius,
          child: Container(
            decoration: BoxDecoration(
              color: isDark ? AppColors.darkSurface : AppColors.paperLight,
              borderRadius: AppRadius.cardRadius,
              border: Border.all(
                color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
                width: 1,
              ),
            ),
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 1. Episode Number, Duration Subdued Metadata & Bookmark Control
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Text(
                      'EPISODE #${episode.episodeNumber} • ${episode.formattedDuration.toUpperCase()}',
                      style: AppTypography.eyebrow(
                        color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
                      ).copyWith(fontSize: 10.5, letterSpacing: 0.8),
                    ),
                    _EpisodeBookmarkButton(episodeId: episode.id),
                  ],
                ),
                const SizedBox(height: AppSpacing.xs),

                // 2. Primary Headline (Playfair Display)
                Text(
                  episode.title,
                  style: AppTypography.titleMedium(
                    color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
                  ).copyWith(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    height: 1.3,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: AppSpacing.xs),

                // 3. Guest Name and Organization
                Row(
                  children: [
                    if (episode.guest.avatarUrl != null &&
                        episode.guest.avatarUrl!.trim().isNotEmpty) ...[
                      Container(
                        width: 20,
                        height: 20,
                        margin: const EdgeInsets.only(right: AppSpacing.xs),
                        decoration: const BoxDecoration(shape: BoxShape.circle),
                        clipBehavior: Clip.antiAlias,
                        child: Image.network(
                          episode.guest.avatarUrl!,
                          fit: BoxFit.cover,
                          errorBuilder: (_, _, _) => const SizedBox.shrink(),
                        ),
                      ),
                    ],
                    Expanded(
                      child: Text(
                        [
                          episode.guest.name,
                          if (episode.guest.company.isNotEmpty) episode.guest.company,
                        ].join(' • '),
                        style: AppTypography.bodySmall(
                          color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                        ).copyWith(fontWeight: FontWeight.w600),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.xs),

                // 4. Concise Summary (Inter)
                Text(
                  episode.summary,
                  style: AppTypography.bodySmall(
                    color: isDark ? AppColors.darkTextSecondary : AppColors.stoneGray,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),

                // 5. Topic Labels as Understated Text
                if (episode.tags.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    episode.tags.join('  •  ').toUpperCase(),
                    style: AppTypography.eyebrow(
                      color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
                    ).copyWith(fontSize: 10, letterSpacing: 0.8),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _EpisodeBookmarkButton extends ConsumerWidget {
  const _EpisodeBookmarkButton({required this.episodeId});

  final String episodeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bookmarksAsync = ref.watch(bookmarksProvider);
    final isBookmarked = bookmarksAsync.value?.contains(episodeId) ?? false;
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Semantics(
      button: true,
      label: isBookmarked ? 'Remove bookmark' : 'Bookmark episode',
      child: SizedBox(
        width: 48,
        height: 48,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () {
            ref.read(bookmarksProvider.notifier).toggleBookmark(episodeId);
          },
          child: Center(
            child: Icon(
              isBookmarked
                  ? Icons.bookmark_rounded
                  : Icons.bookmark_border_rounded,
              size: 20,
              color: isBookmarked
                  ? (isDark ? AppColors.meriOrangeLight : AppColors.meriOrange)
                  : (isDark ? AppColors.darkTextMuted : AppColors.stoneGray),
            ),
          ),
        ),
      ),
    );
  }
}

