import 'package:flutter/material.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/editorial_badge.dart';
import '../../../business_knowledge/domain/models/insight.dart';

/// Horizontal strip displaying actionable entrepreneur business lessons.
class InsightPreviewStrip extends StatelessWidget {
  const InsightPreviewStrip({
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
    final textScale = MediaQuery.textScalerOf(context).scale(1.0).clamp(1.0, 1.8);
    final stripHeight = (196.0 * textScale).clamp(196.0, 270.0);
    final cardWidth = (280.0 * (1.0 + (textScale - 1.0) * 0.35)).clamp(280.0, 360.0);

    return SizedBox(
      height: stripHeight,
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
        scrollDirection: Axis.horizontal,
        itemCount: insights.length,
        separatorBuilder: (_, _) => const SizedBox(width: AppSpacing.md),
        itemBuilder: (context, index) {
          final insight = insights[index];
          return Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: onInsightTap != null ? () => onInsightTap!(insight) : null,
              borderRadius: AppRadius.cardRadius,
              child: Container(
                width: cardWidth,
                decoration: BoxDecoration(
                  color: isDark ? AppColors.darkSurface : AppColors.paperLight,
                  borderRadius: AppRadius.cardRadius,
                  border: Border.all(
                    color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
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
                    EditorialBadge(
                      label: insight.category,
                      variant: EditorialBadgeVariant.orange,
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      insight.title,
                      style: AppTypography.titleMedium(
                        color: isDark
                            ? AppColors.darkTextPrimary
                            : AppColors.inkBlack,
                      ).copyWith(fontSize: 14),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: AppSpacing.xxs),
                    Expanded(
                      child: Text(
                        insight.summary,
                        style: AppTypography.bodySmall(
                          color: isDark
                              ? AppColors.darkTextSecondary
                              : AppColors.stoneGray,
                        ),
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (insight.practicalAction != null) ...[
                      const SizedBox(height: AppSpacing.xs),
                      Row(
                        children: [
                          Icon(
                            Icons.insights_rounded,
                            size: 13,
                            color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                          ),
                          const SizedBox(width: AppSpacing.xs),
                          Expanded(
                            child: Text(
                              insight.practicalAction!,
                              style: AppTypography.labelSmall(
                                color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                              ).copyWith(fontSize: 10, fontWeight: FontWeight.w600),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
