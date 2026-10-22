import 'package:flutter/material.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/editorial_badge.dart';
import '../../domain/models/episode.dart';

/// Displays the episode details modal bottom sheet.
///
/// Reused across HomeScreen and ExploreScreen for cohesive navigation.
void showEpisodeDetailsBottomSheet(BuildContext context, Episode episode) {
  final isDark = Theme.of(context).brightness == Brightness.dark;

  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: isDark ? AppColors.darkSurface : AppColors.paperLight,
    shape: const RoundedRectangleBorder(
      borderRadius: AppRadius.sheetRadius,
    ),
    builder: (context) {
      return DraggableScrollableSheet(
        initialChildSize: 0.65,
        maxChildSize: 0.9,
        minChildSize: 0.4,
        expand: false,
        builder: (context, scrollController) {
          return ListView(
            controller: scrollController,
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: isDark
                        ? AppColors.darkBorder
                        : AppColors.archiveSandBorder,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    'EPISODE #${episode.episodeNumber}',
                    style: AppTypography.eyebrow(
                      color: isDark
                          ? AppColors.meriOrangeLight
                          : AppColors.meriOrange,
                    ),
                  ),
                  Text(
                    episode.formattedDuration,
                    style: AppTypography.labelSmall(
                      color: isDark
                          ? AppColors.darkTextMuted
                          : AppColors.stoneGray,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                episode.title,
                style: AppTypography.titleLarge(
                  color: isDark
                      ? AppColors.darkTextPrimary
                      : AppColors.inkBlack,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                '${episode.guest.name} • ${episode.guest.company}',
                style: AppTypography.labelLarge(
                  color: isDark
                      ? AppColors.meriOrangeLight
                      : AppColors.meriOrange,
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              if (episode.tags.isNotEmpty) ...[
                Wrap(
                  spacing: AppSpacing.xs,
                  runSpacing: AppSpacing.xxs,
                  children: episode.tags.map((tag) {
                    return EditorialBadge(
                      label: tag,
                      variant: EditorialBadgeVariant.sand,
                    );
                  }).toList(),
                ),
                const SizedBox(height: AppSpacing.md),
              ],
              const Divider(),
              const SizedBox(height: AppSpacing.md),
              Text(
                'Summary',
                style: AppTypography.titleMedium(
                  color: isDark
                      ? AppColors.darkTextPrimary
                      : AppColors.inkBlack,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                episode.summary,
                style: AppTypography.bodyMedium(
                  color: isDark
                      ? AppColors.darkTextSecondary
                      : AppColors.stoneGray,
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              Text(
                'About the Guest',
                style: AppTypography.titleMedium(
                  color: isDark
                      ? AppColors.darkTextPrimary
                      : AppColors.inkBlack,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                episode.guest.bio,
                style: AppTypography.bodyMedium(
                  color: isDark
                      ? AppColors.darkTextSecondary
                      : AppColors.stoneGray,
                ),
              ),
              if (episode.quotations.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.lg),
                Text(
                  'Highlighted Quotation',
                  style: AppTypography.titleMedium(
                    color: isDark
                        ? AppColors.darkTextPrimary
                        : AppColors.inkBlack,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                Container(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    color: isDark
                        ? AppColors.darkSurfaceElevated
                        : AppColors.archiveSandLight.withValues(alpha: 0.5),
                    borderRadius: AppRadius.roundedSm,
                    border: Border(
                      left: BorderSide(
                        color: isDark
                            ? AppColors.meriOrangeLight
                            : AppColors.meriOrange,
                        width: 3,
                      ),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '“${episode.quotations.first.amharicQuote}”',
                        style: AppTypography.quotation(
                          color: isDark
                              ? AppColors.darkTextPrimary
                              : AppColors.inkBlack,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        episode.quotations.first.englishTranslation,
                        style: AppTypography.bodySmall(
                          color: isDark
                              ? AppColors.darkTextSecondary
                              : AppColors.stoneGray,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          );
        },
      );
    },
  );
}
