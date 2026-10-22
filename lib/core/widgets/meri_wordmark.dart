import 'package:flutter/material.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// Reusable brand wordmark and masthead for Meri.
///
/// Embodies the brand direction:
/// - Product: Meri, an Ethiopian business knowledge app built from long-form entrepreneur interviews.
/// - Brand tagline: "The business behind the story."
/// - Visual character: premium editorial, authentic, culturally grounded, readable.
class MeriWordmark extends StatelessWidget {
  const MeriWordmark({
    super.key,
    this.tagline,
    this.isCompact = true,
    this.fontSize = 20,
    this.showTagline = true,
  });

  /// Custom tagline override. Defaults to the official brand tagline: "The business behind the story."
  final String? tagline;

  /// Whether to render in a compact inline row (for AppBars) or vertical editorial lockup (for headers/About).
  final bool isCompact;

  /// Base font size for the MERI letters.
  final double fontSize;

  /// Whether to render the tagline.
  final bool showTagline;

  static const String defaultTagline = 'The business behind the story.';

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final primaryColor = isDark ? AppColors.darkTextPrimary : AppColors.inkBlack;
    final mutedColor = isDark ? AppColors.darkTextMuted : AppColors.stoneGray;
    final dotColor = isDark ? AppColors.meriOrangeLight : AppColors.meriOrange;
    final activeTagline = tagline ?? defaultTagline;

    if (isCompact) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Text(
            'MERI',
            style: AppTypography.wordmark(color: primaryColor).copyWith(
              fontSize: fontSize,
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          Container(
            width: fontSize * 0.25,
            height: fontSize * 0.25,
            decoration: BoxDecoration(
              color: dotColor,
              shape: BoxShape.circle,
            ),
          ),
          if (showTagline) ...[
            const SizedBox(width: AppSpacing.sm),
            Flexible(
              child: Text(
                '•  $activeTagline',
                style: AppTypography.eyebrow(color: mutedColor).copyWith(
                  fontSize: fontSize * 0.45,
                  letterSpacing: 0.8,
                  fontWeight: FontWeight.w500,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ],
      );
    }

    // Stacked Editorial Masthead lockup
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(
              'MERI',
              style: AppTypography.wordmark(color: primaryColor).copyWith(
                fontSize: fontSize,
              ),
            ),
            const SizedBox(width: AppSpacing.xs),
            Container(
              width: fontSize * 0.25,
              height: fontSize * 0.25,
              margin: EdgeInsets.only(bottom: fontSize * 0.1),
              decoration: BoxDecoration(
                color: dotColor,
                shape: BoxShape.circle,
              ),
            ),
          ],
        ),
        if (showTagline) ...[
          const SizedBox(height: AppSpacing.xxs),
          Text(
            activeTagline,
            style: AppTypography.bodySmall(color: mutedColor).copyWith(
              fontStyle: FontStyle.italic,
              fontSize: fontSize * 0.55,
            ),
          ),
        ],
      ],
    );
  }
}
