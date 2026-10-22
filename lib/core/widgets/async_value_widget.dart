import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/app_colors.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// Reusable widget for rendering [AsyncValue] states with consistent editorial styling.
class AsyncValueWidget<T> extends StatelessWidget {
  const AsyncValueWidget({
    super.key,
    required this.value,
    required this.data,
    this.onRetry,
    this.loadingMessage = 'Loading business records...',
    this.emptyMessage = 'No knowledge records found.',
    this.isEmpty,
  });

  final AsyncValue<T> value;
  final Widget Function(T data) data;
  final VoidCallback? onRetry;
  final String loadingMessage;
  final String emptyMessage;
  final bool Function(T data)? isEmpty;

  @override
  Widget build(BuildContext context) {
    return value.when(
      data: (item) {
        if (isEmpty != null && isEmpty!(item)) {
          return _EditorialEmptyState(message: emptyMessage, onRetry: onRetry);
        }
        return data(item);
      },
      loading: () => _EditorialLoadingState(message: loadingMessage),
      error: (error, stack) => _EditorialErrorState(
        error: error,
        onRetry: onRetry,
      ),
    );
  }
}

class _EditorialLoadingState extends StatelessWidget {
  const _EditorialLoadingState({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 32,
              height: 32,
              child: CircularProgressIndicator(
                strokeWidth: 2.5,
                valueColor: AlwaysStoppedAnimation<Color>(
                  isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              message,
              style: AppTypography.bodySmall(
                color: isDark ? AppColors.darkTextSecondary : AppColors.stoneGray,
              ),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

class _EditorialErrorState extends StatelessWidget {
  const _EditorialErrorState({required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.lg),
          decoration: BoxDecoration(
            color: isDark ? AppColors.darkSurfaceElevated : AppColors.paperLight,
            borderRadius: AppRadius.cardRadius,
            border: Border.all(
              color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
            ),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.error_outline_rounded,
                size: 36,
                color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                'Unable to Load Records',
                style: AppTypography.titleMedium(
                  color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                error.toString(),
                style: AppTypography.bodySmall(
                  color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
                ),
                textAlign: TextAlign.center,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
              if (onRetry != null) ...[
                const SizedBox(height: AppSpacing.md),
                OutlinedButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh_rounded, size: 16),
                  label: const Text('Retry'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor:
                        isDark ? AppColors.meriOrangeLight : AppColors.inkBlack,
                    side: BorderSide(
                      color: isDark ? AppColors.meriOrangeLight : AppColors.archiveSandBorder,
                    ),
                    shape: const RoundedRectangleBorder(
                      borderRadius: AppRadius.buttonRadius,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _EditorialEmptyState extends StatelessWidget {
  const _EditorialEmptyState({required this.message, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.auto_stories_outlined,
              size: 48,
              color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              'No Entries Available',
              style: AppTypography.titleMedium(
                color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              message,
              style: AppTypography.bodySmall(
                color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
              ),
              textAlign: TextAlign.center,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: AppSpacing.md),
              TextButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh_rounded, size: 16),
                label: const Text('Refresh Library'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
