import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/editorial_badge.dart';
import '../../../../core/widgets/meri_section_header.dart';
import '../../../../core/widgets/meri_wordmark.dart';

/// Editorial Settings, Colophon, and Architecture screen.
///
/// Presents an honest, restrained overview of the Meri companion application,
/// its journalistic mission, typography heritage, local data source, and
/// on-device notebook persistence without misleading or inert controls.
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final primaryTextColor =
        isDark ? AppColors.darkTextPrimary : AppColors.inkBlack;
    final secondaryTextColor =
        isDark ? AppColors.darkTextSecondary : AppColors.stoneGray;
    final accentColor =
        isDark ? AppColors.meriOrangeLight : AppColors.meriOrange;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Settings & About',
          style: AppTypography.titleLarge(color: primaryTextColor),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        children: [
          // ===================================================================
          // 1. Publication Colophon & Mission
          // ===================================================================
          const MeriSectionHeader(
            title: 'About Meri',
            eyebrow: 'Publication Colophon',
            padding: EdgeInsets.zero,
          ),
          const SizedBox(height: AppSpacing.xs),
          _buildCard(
            isDark: isDark,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const MeriWordmark(
                  isCompact: false,
                  fontSize: 22,
                  tagline: 'The business behind the story.',
                ),
                const SizedBox(height: AppSpacing.sm),
                Wrap(
                  spacing: AppSpacing.xs,
                  runSpacing: AppSpacing.xxs,
                  children: const [
                    EditorialBadge(
                      label: 'VERSION 1.0.0',
                      variant: EditorialBadgeVariant.orange,
                    ),
                    EditorialBadge(
                      label: 'EDITORIAL EDITION',
                      variant: EditorialBadgeVariant.sand,
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                Text(
                  'Meri is a business-knowledge companion to long-form Meri Podcast interviews. It distills actionable executive takeaways, operational frameworks, and primary-source quotations from Ethiopian entrepreneurs without replacing the original full-length conversations.',
                  style: AppTypography.bodySmall(color: secondaryTextColor),
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  'Composed in Playfair Display for editorial headlines, Inter for functional reading, and authentic upright Ethiopic script for Amharic quotations.',
                  style: AppTypography.bodySmall(color: secondaryTextColor),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.lg),

          // ===================================================================
          // 2. Knowledge Architecture & Storage
          // ===================================================================
          const MeriSectionHeader(
            title: 'System & Archive',
            eyebrow: 'Knowledge Architecture',
            padding: EdgeInsets.zero,
          ),
          const SizedBox(height: AppSpacing.xs),
          _buildInfoTile(
            icon: Icons.menu_book_outlined,
            title: 'Knowledge Archive',
            subtitle: 'Bundled Local Dataset (Episode #199)',
            description:
                'Hermetic offline archive featuring Wengelawit (Liya) Gole, Founder & CEO of International Makeup School and Dura by Liya. Architected to support future episode archives.',
            isDark: isDark,
          ),
          const SizedBox(height: AppSpacing.xs),
          _buildInfoTile(
            icon: Icons.play_circle_outline_rounded,
            title: 'Interview Media',
            subtitle: 'YouTube Video & Audio',
            description:
                'Full-length interviews and timestamped quotations open directly in external video applications to preserve creator attribution and streaming fidelity.',
            isDark: isDark,
          ),
          const SizedBox(height: AppSpacing.xs),
          _buildInfoTile(
            icon: Icons.bookmark_border_rounded,
            title: 'Personal Notebook',
            subtitle: 'On-Device Storage (SharedPreferences)',
            description:
                'Bookmarked episodes and notes are stored strictly on your device for immediate offline reference, requiring no cloud account or external tracking.',
            isDark: isDark,
          ),
          const SizedBox(height: AppSpacing.lg),

          // ===================================================================
          // 3. Reading Environment & Appearance
          // ===================================================================
          const MeriSectionHeader(
            title: 'Reading Environment',
            eyebrow: 'Display & Contrast',
            padding: EdgeInsets.zero,
          ),
          const SizedBox(height: AppSpacing.xs),
          _buildInfoTile(
            icon: Icons.palette_outlined,
            title: 'Visual Palette',
            subtitle: isDark
                ? 'Ink Black Dark Mode (Ink Night)'
                : 'Warm Ivory Light Mode (Warm Paper)',
            description:
                'The editorial reading palette harmonizes with your system appearance settings to ensure high legibility and eye comfort.',
            isDark: isDark,
          ),
          const SizedBox(height: AppSpacing.lg),

          // ===================================================================
          // 4. Archive Navigation Action
          // ===================================================================
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => context.go('/explore'),
              style: OutlinedButton.styleFrom(
                minimumSize: const Size(double.infinity, 48),
                side: BorderSide(
                  color: isDark
                      ? AppColors.darkBorder
                      : AppColors.archiveSandBorder,
                ),
                foregroundColor: primaryTextColor,
              ),
              icon: Icon(Icons.explore_outlined, size: 18, color: accentColor),
              label: const Text('Explore Knowledge Archive'),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),

          // ===================================================================
          // 5. Attribution & Heritage
          // ===================================================================
          const MeriSectionHeader(
            title: 'Attribution',
            eyebrow: 'Credits & Production',
            padding: EdgeInsets.zero,
          ),
          const SizedBox(height: AppSpacing.xs),
          _buildCard(
            isDark: isDark,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Meri Podcast • Addis Ababa, Ethiopia',
                  style: AppTypography.titleSmall(color: primaryTextColor),
                ),
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  'Dedicated to documenting authentic Ethiopian business knowledge, industrial entrepreneurship, and creative enterprises.',
                  style: AppTypography.bodySmall(color: secondaryTextColor),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  'All original interview rights, audio, and video belong to Meri Podcast.',
                  style: AppTypography.labelSmall(
                    color: isDark
                        ? AppColors.darkTextMuted
                        : AppColors.stoneGray,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.xxl),
        ],
      ),
    );
  }

  Widget _buildCard({
    required Widget child,
    required bool isDark,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? AppColors.darkSurface : AppColors.paperLight,
        borderRadius: AppRadius.cardRadius,
        border: Border.all(
          color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
        ),
      ),
      child: child,
    );
  }

  Widget _buildInfoTile({
    required IconData icon,
    required String title,
    required String subtitle,
    required String description,
    required bool isDark,
  }) {
    final primaryTextColor =
        isDark ? AppColors.darkTextPrimary : AppColors.inkBlack;
    final secondaryTextColor =
        isDark ? AppColors.darkTextSecondary : AppColors.stoneGray;
    final accentColor =
        isDark ? AppColors.meriOrangeLight : AppColors.meriOrange;

    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? AppColors.darkSurface : AppColors.paperLight,
        borderRadius: AppRadius.cardRadius,
        border: Border.all(
          color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: isDark
                  ? AppColors.darkSurfaceElevated
                  : AppColors.archiveSandLight,
              shape: BoxShape.circle,
              border: Border.all(
                color: isDark
                    ? AppColors.darkBorder
                    : AppColors.archiveSandBorder,
              ),
            ),
            child: Icon(
              icon,
              size: 18,
              color: accentColor,
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: AppTypography.labelLarge(color: primaryTextColor),
                ),
                Text(
                  subtitle,
                  style: AppTypography.labelSmall(
                    color: accentColor,
                  ).copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  description,
                  style: AppTypography.bodySmall(color: secondaryTextColor),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
