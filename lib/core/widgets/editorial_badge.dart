import 'package:flutter/material.dart';
import '../theme/app_colors.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

enum EditorialBadgeVariant {
  /// Meri Orange accent badge for highlights, masterclasses, and featured items.
  orange,

  /// Archive Sand badge for categories and topics.
  sand,

  /// Muted stone gray badge for secondary metadata, timestamps, and tags.
  muted,

  // Compatibility aliases
  gold,
  navy,
}

class EditorialBadge extends StatelessWidget {
  const EditorialBadge({
    super.key,
    required this.label,
    this.icon,
    this.variant = EditorialBadgeVariant.muted,
  });

  final String label;
  final IconData? icon;
  final EditorialBadgeVariant variant;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    Color backgroundColor;
    Color textColor;
    Color borderColor;

    switch (variant) {
      case EditorialBadgeVariant.orange:
      case EditorialBadgeVariant.gold:
        backgroundColor = isDark
            ? AppColors.meriOrange.withValues(alpha: 0.18)
            : AppColors.meriOrange.withValues(alpha: 0.10);
        textColor = isDark ? AppColors.meriOrangeLight : AppColors.meriOrange;
        borderColor = isDark
            ? AppColors.meriOrange.withValues(alpha: 0.4)
            : AppColors.meriOrange.withValues(alpha: 0.3);
        break;

      case EditorialBadgeVariant.sand:
        backgroundColor = isDark
            ? AppColors.archiveSand.withValues(alpha: 0.15)
            : AppColors.archiveSandLight;
        textColor = isDark ? AppColors.archiveSand : AppColors.inkBlack;
        borderColor = isDark
            ? AppColors.archiveSand.withValues(alpha: 0.3)
            : AppColors.archiveSandBorder;
        break;

      case EditorialBadgeVariant.navy:
      case EditorialBadgeVariant.muted:
        backgroundColor = isDark
            ? AppColors.darkSurfaceElevated
            : AppColors.archiveSandLight.withValues(alpha: 0.5);
        textColor = isDark ? AppColors.darkTextSecondary : AppColors.stoneGray;
        borderColor = isDark ? AppColors.darkBorder : AppColors.archiveSandBorder;
        break;
    }

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: AppRadius.roundedXs,
        border: Border.all(color: borderColor, width: 0.8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 12, color: textColor),
            const SizedBox(width: AppSpacing.xs),
          ],
          Text(
            label.toUpperCase(),
            style: AppTypography.eyebrow(color: textColor).copyWith(
              fontSize: 9.5,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}
