import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/editorial_badge.dart';
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
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: isDark ? 0.2 : 0.03),
                  blurRadius: 6,
                  offset: const Offset(0, 2),
                ),
              ],
            ),
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Top Meta: Episode Number + Duration
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    EditorialBadge(
                      label: 'Episode #${episode.episodeNumber}',
                      variant: EditorialBadgeVariant.sand,
                    ),
                    Row(
                      children: [
                        Icon(
                          Icons.schedule_rounded,
                          size: 13,
                          color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
                        ),
                        const SizedBox(width: AppSpacing.xs),
                        Text(
                          episode.formattedDuration,
                          style: AppTypography.labelSmall(
                            color: isDark
                                ? AppColors.darkTextMuted
                                : AppColors.stoneGray,
                          ),
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        _EpisodeBookmarkButton(episodeId: episode.id),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),

                // Episode Title (Playfair Display)
                Text(
                  episode.title,
                  style: AppTypography.titleMedium(
                    color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: AppSpacing.xs),

                // Guest Bylines
                Row(
                  children: [
                    CircleAvatar(
                      radius: 12,
                      backgroundColor: isDark
                          ? AppColors.darkSurfaceElevated
                          : AppColors.archiveSandLight,
                      child: Text(
                        _getInitials(episode.guest.name),
                        style: AppTypography.labelSmall(
                          color: isDark
                              ? AppColors.meriOrangeLight
                              : AppColors.meriOrange,
                        ).copyWith(fontSize: 10, fontWeight: FontWeight.w700),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        '${episode.guest.name} • ${episode.guest.company}',
                        style: AppTypography.bodySmall(
                          color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                        ).copyWith(fontWeight: FontWeight.w600),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),

                // Summary (Inter)
                Text(
                  episode.summary,
                  style: AppTypography.bodySmall(
                    color: isDark ? AppColors.darkTextSecondary : AppColors.stoneGray,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: AppSpacing.md),

                // Footer: Tags + Knowledge Counts
                Row(
                  children: [
                    if (episode.tags.isNotEmpty)
                      Expanded(
                        child: Wrap(
                          spacing: AppSpacing.xs,
                          runSpacing: AppSpacing.xxs,
                          children: episode.tags.take(2).map((tag) {
                            return EditorialBadge(
                              label: tag,
                              variant: EditorialBadgeVariant.muted,
                            );
                          }).toList(),
                        ),
                      ),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (episode.insights.isNotEmpty) ...[
                          Icon(
                            Icons.lightbulb_outline_rounded,
                            size: 13,
                            color: isDark
                                ? AppColors.darkTextMuted
                                : AppColors.stoneGray,
                          ),
                          const SizedBox(width: AppSpacing.xxs),
                          Text(
                            '${episode.insights.length}',
                            style: AppTypography.labelSmall(
                              color: isDark
                                  ? AppColors.darkTextMuted
                                  : AppColors.stoneGray,
                            ),
                          ),
                          const SizedBox(width: AppSpacing.sm),
                        ],
                        if (episode.quotations.isNotEmpty) ...[
                          Icon(
                            Icons.format_quote_rounded,
                            size: 13,
                            color: isDark
                                ? AppColors.darkTextMuted
                                : AppColors.stoneGray,
                          ),
                          const SizedBox(width: AppSpacing.xxs),
                          Text(
                            '${episode.quotations.length}',
                            style: AppTypography.labelSmall(
                              color: isDark
                                  ? AppColors.darkTextMuted
                                  : AppColors.stoneGray,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _getInitials(String name) {
    final parts = name.trim().split(RegExp(r'\s+'));
    if (parts.length >= 2) {
      return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
    }
    return parts.first.isNotEmpty ? parts.first[0].toUpperCase() : 'M';
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
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          ref.read(bookmarksProvider.notifier).toggleBookmark(episodeId);
        },
        child: Padding(
          padding: const EdgeInsets.only(left: AppSpacing.xs),
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
    );
  }
}

