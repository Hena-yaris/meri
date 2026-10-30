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
    final primaryTextColor = isDark ? AppColors.darkTextPrimary : AppColors.inkBlack;
    final secondaryTextColor = isDark ? AppColors.darkTextSecondary : AppColors.stoneGray;
    final accentColor = isDark ? AppColors.meriOrangeLight : AppColors.meriOrange;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
      child: Material(
        color: isDark ? AppColors.darkSurface : AppColors.paperLight,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.cardRadius,
          side: BorderSide(
            color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
            width: 1,
          ),
        ),
        child: InkWell(
          onTap: onTap,
          borderRadius: AppRadius.cardRadius,
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 1. Episode Number, Duration, and Bookmark Control
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    EditorialBadge(
                      label: 'Episode #${episode.episodeNumber} • ${episode.formattedDuration}',
                      variant: EditorialBadgeVariant.sand,
                    ),
                    _FeaturedBookmarkButton(episodeId: episode.id),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),

                // 2. Prominent Editorial Headline
                Text(
                  episode.title,
                  style: AppTypography.headlineLarge(color: primaryTextColor),
                ),
                const SizedBox(height: AppSpacing.xs),

                // 3. Guest Name and Professional Role
                Text(
                  episode.guest.name,
                  style: AppTypography.titleMedium(
                    color: primaryTextColor,
                  ).copyWith(fontWeight: FontWeight.w700),
                ),
                if (episode.guest.title.isNotEmpty || episode.guest.company.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.xxs),
                  Text(
                    [
                      if (episode.guest.title.isNotEmpty) episode.guest.title,
                      if (episode.guest.company.isNotEmpty) episode.guest.company,
                    ].join(', '),
                    style: AppTypography.bodySmall(
                      color: accentColor,
                    ).copyWith(fontWeight: FontWeight.w600),
                  ),
                ],
                const SizedBox(height: AppSpacing.sm),

                // Summary Excerpt
                Text(
                  episode.summary,
                  style: AppTypography.bodyMedium(color: secondaryTextColor),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),

                // 4. Authentic Amharic Quotation Callout (if available)
                if (quotation != null) ...[
                  const SizedBox(height: AppSpacing.md),
                  Container(
                    padding: const EdgeInsets.only(
                      left: AppSpacing.md,
                      top: AppSpacing.xxs,
                      bottom: AppSpacing.xxs,
                    ),
                    decoration: BoxDecoration(
                      border: Border(
                        left: BorderSide(
                          color: accentColor,
                          width: 2.5,
                        ),
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '“${quotation.amharicQuote}”',
                          style: AppTypography.amharicQuotation(
                            color: primaryTextColor,
                            fontSize: 14.5,
                          ),
                        ),
                        if (quotation.englishTranslation.trim().isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.xxs),
                          Text(
                            quotation.englishTranslation,
                            style: AppTypography.bodySmall(
                              color: secondaryTextColor,
                            ),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ],
                    ),
                  ),
                ],

                // 5. Clear Action to Read Full Briefing
                const SizedBox(height: AppSpacing.md),
                const Divider(),
                const SizedBox(height: AppSpacing.sm),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Read Full Briefing',
                      style: AppTypography.labelLarge(
                        color: accentColor,
                      ).copyWith(fontWeight: FontWeight.w700),
                    ),
                    Icon(
                      Icons.arrow_forward_rounded,
                      size: 16,
                      color: accentColor,
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
                  ? AppColors.meriOrangeLight
                  : AppColors.archiveSand,
            ),
          ),
        ),
      ),
    );
  }
}

