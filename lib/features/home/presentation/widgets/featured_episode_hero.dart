import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/editorial_badge.dart';
import '../../../bookmarks/data/providers.dart';
import '../../../business_knowledge/domain/models/episode.dart';

/// Featured editorial masterclass spotlight hero.
///
/// Anchored by Meri Ink Black and Warm Ivory, with restrained Meri Orange
/// accents and Archive Sand quotation styling.
class FeaturedEpisodeHero extends StatelessWidget {
  const FeaturedEpisodeHero({
    super.key,
    required this.episode,
    this.onTap,
  });

  final Episode episode;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final quotation = episode.quotations.isNotEmpty ? episode.quotations.first : null;
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: AppRadius.cardRadius,
          child: Container(
            decoration: BoxDecoration(
              // Solid editorial Ink Black card with subtle texture for high contrast
              color: isDark ? AppColors.darkSurface : AppColors.inkBlack,
              borderRadius: AppRadius.cardRadius,
              border: Border.all(
                color: isDark ? AppColors.darkBorder : AppColors.inkBlack,
                width: 1,
              ),
              boxShadow: [
                BoxShadow(
                  color: AppColors.inkBlack.withValues(alpha: isDark ? 0.3 : 0.08),
                  blurRadius: 12,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Top Header: Eyebrow & Duration
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    EditorialBadge(
                      label: 'Masterclass • #${episode.episodeNumber}',
                      variant: EditorialBadgeVariant.orange,
                    ),
                    Row(
                      children: [
                        const Icon(
                          Icons.schedule_rounded,
                          size: 13,
                          color: AppColors.archiveSand,
                        ),
                        const SizedBox(width: AppSpacing.xs),
                        Text(
                          episode.formattedDuration,
                          style: AppTypography.labelSmall(
                            color: AppColors.archiveSand,
                          ),
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        _FeaturedBookmarkButton(episodeId: episode.id),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),

                // Episode Title (Playfair Display)
                Text(
                  episode.title,
                  style: AppTypography.titleLarge(
                    color: AppColors.warmIvory,
                  ).copyWith(fontSize: 21, height: 1.3),
                ),
                const SizedBox(height: AppSpacing.sm),

                // Summary (Inter)
                Text(
                  episode.summary,
                  style: AppTypography.bodyMedium(
                    color: AppColors.archiveSand,
                  ),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: AppSpacing.md),

                // Featured Quote callout if available
                if (quotation != null) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.md,
                      vertical: AppSpacing.sm,
                    ),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.06),
                      borderRadius: AppRadius.roundedXs,
                      border: const Border(
                        left: BorderSide(
                          color: AppColors.meriOrange,
                          width: 3,
                        ),
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '“${quotation.amharicQuote}”',
                          style: AppTypography.quotation(
                            color: AppColors.warmIvory,
                          ).copyWith(fontSize: 13.5),
                        ),
                        const SizedBox(height: AppSpacing.xs),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Expanded(
                              child: Text(
                                quotation.englishTranslation,
                                style: AppTypography.bodySmall(
                                  color: AppColors.archiveSand,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            Text(
                              '@ ${quotation.formattedTimestamp}',
                              style: AppTypography.labelSmall(
                                color: AppColors.stoneGrayLight,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: AppSpacing.md),
                ],

                // Guest Info Bar & Action
                Divider(
                  color: Colors.white.withValues(alpha: 0.12),
                  height: 1,
                ),
                const SizedBox(height: AppSpacing.md),
                Row(
                  children: [
                    CircleAvatar(
                      radius: 18,
                      backgroundColor: AppColors.meriOrange,
                      child: Text(
                        _getInitials(episode.guest.name),
                        style: AppTypography.labelLarge(
                          color: Colors.white,
                        ).copyWith(fontSize: 13, fontWeight: FontWeight.w700),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            episode.guest.name,
                            style: AppTypography.labelLarge(
                              color: AppColors.warmIvory,
                            ),
                          ),
                          Text(
                            '${episode.guest.title}, ${episode.guest.company}',
                            style: AppTypography.bodySmall(
                              color: AppColors.stoneGrayLight,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.all(AppSpacing.xs),
                      decoration: BoxDecoration(
                        color: AppColors.meriOrange.withValues(alpha: 0.18),
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.arrow_forward_rounded,
                        size: 15,
                        color: AppColors.meriOrange,
                      ),
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

class _FeaturedBookmarkButton extends ConsumerWidget {
  const _FeaturedBookmarkButton({required this.episodeId});

  final String episodeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bookmarksAsync = ref.watch(bookmarksProvider);
    final isBookmarked = bookmarksAsync.value?.contains(episodeId) ?? false;

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
                ? AppColors.meriOrangeLight
                : AppColors.archiveSand,
          ),
        ),
      ),
    );
  }
}

