import 'package:flutter/material.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/widgets/meri_wordmark.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Settings & About',
          style: AppTypography.titleLarge(
            color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.md),
        children: [
          _SectionTitle(title: 'PREFERENCES', isDark: isDark),
          _SettingTile(
            icon: Icons.palette_outlined,
            title: 'Theme & Appearance',
            subtitle: isDark ? 'Dark Editorial Mode (Ink Night)' : 'Light Paper Tone (Warm Ivory)',
            onTap: () {},
            isDark: isDark,
          ),
          _SettingTile(
            icon: Icons.speed_rounded,
            title: 'Default Playback Rate',
            subtitle: '1.0x Normal Speed',
            onTap: () {},
            isDark: isDark,
          ),
          const SizedBox(height: AppSpacing.lg),
          _SectionTitle(title: 'DATA & ARCHIVE', isDark: isDark),
          _SettingTile(
            icon: Icons.storage_rounded,
            title: 'Knowledge Source',
            subtitle: 'Bundled Local JSON Archive (Verified Dataset)',
            onTap: () {},
            isDark: isDark,
          ),
          _SettingTile(
            icon: Icons.cloud_done_outlined,
            title: 'Cloud Synchronization',
            subtitle: 'Supabase Repository (Scheduled Next)',
            onTap: () {},
            isDark: isDark,
          ),
          const SizedBox(height: AppSpacing.lg),
          _SectionTitle(title: 'ABOUT MERI', isDark: isDark),
          Container(
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: isDark ? AppColors.darkSurface : AppColors.paperLight,
              borderRadius: AppRadius.cardRadius,
              border: Border.all(
                color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const MeriWordmark(
                  isCompact: false,
                  fontSize: 22,
                  tagline: 'The business behind the story.',
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  'v1.0.0 • Foundation Release',
                  style: AppTypography.labelSmall(
                    color: isDark
                        ? AppColors.darkTextMuted
                        : AppColors.stoneGray,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  'Meri distills actionable business knowledge and strategies from verified Ethiopian entrepreneur interviews. Grounded in authentic editorial publishing principles with Playfair Display and Inter.',
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
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, required this.isDark});

  final String title;
  final bool isDark;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
        left: AppSpacing.xs,
        bottom: AppSpacing.xs,
        top: AppSpacing.sm,
      ),
      child: Text(
        title,
        style: AppTypography.eyebrow(
          color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
        ),
      ),
    );
  }
}

class _SettingTile extends StatelessWidget {
  const _SettingTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
    required this.isDark,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
  final bool isDark;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: Material(
        color: isDark ? AppColors.darkSurface : AppColors.paperLight,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.cardRadius,
          side: BorderSide(
            color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
          ),
        ),
        child: ListTile(
          leading: Icon(
            icon,
            color: isDark ? AppColors.meriOrangeLight : AppColors.inkBlack,
            size: 22,
          ),
          title: Text(
            title,
            style: AppTypography.labelLarge(
              color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
            ).copyWith(fontSize: 14),
          ),
          subtitle: Text(
            subtitle,
            style: AppTypography.bodySmall(
              color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
            ),
          ),
          trailing: Icon(
            Icons.chevron_right_rounded,
            color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
            size: 20,
          ),
          onTap: onTap,
        ),
      ),
    );
  }
}
