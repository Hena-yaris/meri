import 'package:flutter/material.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/editorial_badge.dart';
import '../../../business_knowledge/domain/models/insight.dart';

/// Vertical editorial list displaying executive business takeaways.
class ExecutiveTakeawaysList extends StatelessWidget {
  const ExecutiveTakeawaysList({
    super.key,
    required this.insights,
    this.onInsightTap,
  });

  final List<Insight> insights;
  final ValueChanged<Insight>? onInsightTap;

  @override
  Widget build(BuildContext context) {
    if (insights.isEmpty) return const SizedBox.shrink();

    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
      child: Column(
        children: insights.asMap().entries.map((entry) {
          final index = entry.key;
          final insight = entry.value;
          final ordinal = (index + 1).toString().padLeft(2, '0');

          return Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
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
                onTap: onInsightTap != null ? () => onInsightTap!(insight) : null,
                borderRadius: AppRadius.cardRadius,
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Header Row: Ordinal & Category
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            ordinal,
                            style: AppTypography.eyebrow(
                              color: isDark
                                  ? AppColors.meriOrangeLight
                                  : AppColors.meriOrange,
                            ),
                          ),
                          EditorialBadge(
                            label: insight.category,
                            variant: EditorialBadgeVariant.sand,
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.xs),

                      // Headline
                      Text(
                        insight.title,
                        style: AppTypography.titleMedium(
                          color: isDark
                              ? AppColors.darkTextPrimary
                              : AppColors.inkBlack,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.xs),

                      // Concise Summary
                      Text(
                        insight.summary,
                        style: AppTypography.bodySmall(
                          color: isDark
                              ? AppColors.darkTextSecondary
                              : AppColors.stoneGray,
                        ),
                      ),

                      // Optional Practical Action
                      if (insight.practicalAction != null &&
                          insight.practicalAction!.trim().isNotEmpty) ...[
                        const SizedBox(height: AppSpacing.sm),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(
                              Icons.lightbulb_outline_rounded,
                              size: 14,
                              color: isDark
                                  ? AppColors.meriOrangeLight
                                  : AppColors.meriOrange,
                            ),
                            const SizedBox(width: AppSpacing.xs),
                            Expanded(
                              child: Text(
                                insight.practicalAction!,
                                style: AppTypography.labelSmall(
                                  color: isDark
                                      ? AppColors.meriOrangeLight
                                      : AppColors.meriOrange,
                                ).copyWith(fontWeight: FontWeight.w600),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}
