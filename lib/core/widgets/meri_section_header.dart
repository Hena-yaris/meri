import 'package:flutter/material.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// Reusable editorial section heading component for Meri.
///
/// Designed to bring structural rhythm and authentic editorial elegance
/// to episode lists, insight sections, and category headers.
class MeriSectionHeader extends StatelessWidget {
  const MeriSectionHeader({
    super.key,
    required this.title,
    this.eyebrow,
    this.eyebrowColor,
    this.actionLabel,
    this.onActionPressed,
    this.showAccentBar = true,
    this.padding = const EdgeInsets.symmetric(
      horizontal: AppSpacing.md,
      vertical: AppSpacing.sm,
    ),
  });

  final String title;
  final String? eyebrow;
  final Color? eyebrowColor;
  final String? actionLabel;
  final VoidCallback? onActionPressed;
  final bool showAccentBar;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final primaryTextColor = isDark ? AppColors.darkTextPrimary : AppColors.inkBlack;
    final accentColor = isDark ? AppColors.meriOrangeLight : AppColors.meriOrange;
    final resolvedEyebrowColor = eyebrowColor ?? accentColor;

    return Padding(
      padding: padding,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                if (eyebrow != null) ...[
                  Text(
                    eyebrow!.toUpperCase(),
                    style: AppTypography.eyebrow(color: resolvedEyebrowColor),
                  ),
                  const SizedBox(height: AppSpacing.xxs),
                ],
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    if (showAccentBar) ...[
                      Container(
                        width: 3,
                        height: 18,
                        decoration: BoxDecoration(
                          color: accentColor,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                    ],
                    Expanded(
                      child: Text(
                        title,
                        style: AppTypography.titleLarge(color: primaryTextColor),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          if (actionLabel != null)
            Padding(
              padding: const EdgeInsets.only(left: AppSpacing.sm),
              child: TextButton(
                onPressed: onActionPressed,
                style: TextButton.styleFrom(
                  foregroundColor: accentColor,
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm,
                    vertical: AppSpacing.xs,
                  ),
                  minimumSize: const Size(48, 36),
                  tapTargetSize: MaterialTapTargetSize.padded,
                ),
                child: Text(
                  actionLabel!,
                  style: AppTypography.labelSmall(color: accentColor).copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
