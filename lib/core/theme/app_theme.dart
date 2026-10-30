import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'app_colors.dart';
import 'app_radius.dart';
import 'app_spacing.dart';
import 'app_typography.dart';

/// Centralized Material 3 theme configurations for Meri.
///
/// Embodies a premium, authentic Ethiopian business publication aesthetic:
/// - Editorial warmth with Warm Ivory paper backgrounds and crisp Ink Black typography.
/// - Restrained cultural character anchored by Meri Orange accents and Archive Sand rules.
/// - High legibility, restrained radii, flat tactile surfaces, and zero excessive gradients.
abstract class AppTheme {
  // ==========================================
  // Light Editorial Theme (Warm Paper)
  // ==========================================
  static ThemeData get lightTheme {
    final base = ThemeData.light(useMaterial3: true);

    const colorScheme = ColorScheme(
      brightness: Brightness.light,
      primary: AppColors.meriOrange,
      onPrimary: Colors.white,
      primaryContainer: AppColors.archiveSandLight,
      onPrimaryContainer: AppColors.inkBlack,
      secondary: AppColors.inkBlack,
      onSecondary: AppColors.warmIvory,
      secondaryContainer: AppColors.archiveSandLight,
      onSecondaryContainer: AppColors.inkBlack,
      tertiary: AppColors.archiveSand,
      onTertiary: AppColors.inkBlack,
      error: AppColors.error,
      onError: Colors.white,
      surface: AppColors.paperLight,
      onSurface: AppColors.inkBlack,
      surfaceContainerHighest: AppColors.archiveSandLight,
      surfaceContainer: AppColors.warmIvory,
      outline: AppColors.archiveSandBorder,
      outlineVariant: Color(0xFFE5DAC9),
    );

    return base.copyWith(
      scaffoldBackgroundColor: AppColors.warmIvory,
      colorScheme: colorScheme,
      textTheme: AppTypography.createTextTheme(
        AppColors.inkBlack,
        AppColors.stoneGray,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.warmIvory,
        elevation: 0,
        scrolledUnderElevation: 0.5,
        surfaceTintColor: Colors.transparent,
        systemOverlayStyle: SystemUiOverlayStyle.dark,
        centerTitle: false,
        titleTextStyle: AppTypography.titleLarge(color: AppColors.inkBlack),
        iconTheme: const IconThemeData(color: AppColors.inkBlack),
      ),
      cardTheme: CardThemeData(
        color: AppColors.paperLight,
        elevation: 0,
        shadowColor: Colors.transparent,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.cardRadius,
          side: const BorderSide(color: AppColors.archiveSandBorder, width: 1),
        ),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: AppColors.paperLight,
        surfaceTintColor: Colors.transparent,
        elevation: 2,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.sheetRadius,
          side: BorderSide(color: AppColors.archiveSandBorder, width: 1),
        ),
        clipBehavior: Clip.antiAlias,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: AppColors.paperLight,
        surfaceTintColor: Colors.transparent,
        elevation: 3,
        shape: const RoundedRectangleBorder(
          borderRadius: AppRadius.roundedSm,
          side: BorderSide(color: AppColors.archiveSandBorder, width: 1),
        ),
        titleTextStyle: AppTypography.titleLarge(color: AppColors.inkBlack),
        contentTextStyle: AppTypography.bodyMedium(color: AppColors.stoneGray),
      ),
      popupMenuTheme: const PopupMenuThemeData(
        color: AppColors.paperLight,
        surfaceTintColor: Colors.transparent,
        elevation: 2,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.roundedSm,
          side: BorderSide(color: AppColors.archiveSandBorder, width: 1),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.paperLight,
        border: const OutlineInputBorder(
          borderRadius: AppRadius.roundedSm,
          borderSide: BorderSide(color: AppColors.archiveSandBorder, width: 1),
        ),
        enabledBorder: const OutlineInputBorder(
          borderRadius: AppRadius.roundedSm,
          borderSide: BorderSide(color: AppColors.archiveSandBorder, width: 1),
        ),
        focusedBorder: const OutlineInputBorder(
          borderRadius: AppRadius.roundedSm,
          borderSide: BorderSide(color: AppColors.meriOrange, width: 1.5),
        ),
        hintStyle: AppTypography.bodySmall(color: AppColors.stoneGray),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: AppColors.warmIvory,
        indicatorColor: AppColors.archiveSandLight,
        elevation: 0,
        height: 68,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return AppTypography.labelSmall(color: AppColors.meriOrange)
                .copyWith(fontWeight: FontWeight.w700);
          }
          return AppTypography.labelSmall(color: AppColors.stoneGray);
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return const IconThemeData(color: AppColors.meriOrange, size: 24);
          }
          return const IconThemeData(color: AppColors.stoneGray, size: 22);
        }),
      ),
      dividerTheme: const DividerThemeData(
        color: AppColors.archiveSandBorder,
        thickness: 1,
        space: 1,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.archiveSandLight,
        selectedColor: AppColors.archiveSand,
        disabledColor: AppColors.archiveSandBorder,
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.sm,
          vertical: AppSpacing.xs,
        ),
        labelStyle: AppTypography.labelSmall(color: AppColors.inkBlack),
        shape: const RoundedRectangleBorder(
          borderRadius: AppRadius.roundedSm,
          side: BorderSide(color: AppColors.archiveSandBorder),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.meriOrange,
          foregroundColor: Colors.white,
          elevation: 0,
          textStyle: AppTypography.labelLarge(color: Colors.white),
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.buttonRadius,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.sm,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.inkBlack,
          side: const BorderSide(color: AppColors.archiveSandBorder),
          textStyle: AppTypography.labelLarge(color: AppColors.inkBlack),
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.buttonRadius,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.sm,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.meriOrange,
          textStyle: AppTypography.labelLarge(color: AppColors.meriOrange),
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.buttonRadius,
          ),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: AppColors.inkBlack,
        contentTextStyle: AppTypography.bodySmall(color: AppColors.warmIvory),
        shape: const RoundedRectangleBorder(
          borderRadius: AppRadius.roundedSm,
        ),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  // ==========================================
  // Dark Editorial Theme (Ink Night)
  // ==========================================
  static ThemeData get darkTheme {
    final base = ThemeData.dark(useMaterial3: true);

    const colorScheme = ColorScheme(
      brightness: Brightness.dark,
      primary: AppColors.meriOrangeLight,
      onPrimary: AppColors.inkBlack,
      primaryContainer: AppColors.darkSurfaceElevated,
      onPrimaryContainer: AppColors.darkTextPrimary,
      secondary: AppColors.archiveSand,
      onSecondary: AppColors.inkBlack,
      secondaryContainer: AppColors.darkSurfaceElevated,
      onSecondaryContainer: AppColors.darkTextPrimary,
      tertiary: AppColors.stoneGray,
      onTertiary: AppColors.darkCanvas,
      error: AppColors.error,
      onError: Colors.white,
      surface: AppColors.darkSurface,
      onSurface: AppColors.darkTextPrimary,
      surfaceContainerHighest: AppColors.darkSurfaceElevated,
      surfaceContainer: AppColors.darkSurface,
      outline: AppColors.darkBorder,
      outlineVariant: Color(0xFF2E312B),
    );

    return base.copyWith(
      scaffoldBackgroundColor: AppColors.darkCanvas,
      colorScheme: colorScheme,
      textTheme: AppTypography.createTextTheme(
        AppColors.darkTextPrimary,
        AppColors.darkTextSecondary,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.darkCanvas,
        elevation: 0,
        scrolledUnderElevation: 0.5,
        surfaceTintColor: Colors.transparent,
        systemOverlayStyle: SystemUiOverlayStyle.light,
        centerTitle: false,
        titleTextStyle: AppTypography.titleLarge(color: AppColors.darkTextPrimary),
        iconTheme: const IconThemeData(color: AppColors.darkTextPrimary),
      ),
      cardTheme: CardThemeData(
        color: AppColors.darkSurface,
        elevation: 0,
        shadowColor: Colors.transparent,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.cardRadius,
          side: const BorderSide(color: AppColors.darkBorder, width: 1),
        ),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: AppColors.darkSurface,
        surfaceTintColor: Colors.transparent,
        elevation: 2,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.sheetRadius,
          side: BorderSide(color: AppColors.darkBorder, width: 1),
        ),
        clipBehavior: Clip.antiAlias,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: AppColors.darkSurface,
        surfaceTintColor: Colors.transparent,
        elevation: 3,
        shape: const RoundedRectangleBorder(
          borderRadius: AppRadius.roundedSm,
          side: BorderSide(color: AppColors.darkBorder, width: 1),
        ),
        titleTextStyle: AppTypography.titleLarge(color: AppColors.darkTextPrimary),
        contentTextStyle: AppTypography.bodyMedium(color: AppColors.darkTextSecondary),
      ),
      popupMenuTheme: const PopupMenuThemeData(
        color: AppColors.darkSurface,
        surfaceTintColor: Colors.transparent,
        elevation: 2,
        shape: RoundedRectangleBorder(
          borderRadius: AppRadius.roundedSm,
          side: BorderSide(color: AppColors.darkBorder, width: 1),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.darkSurfaceElevated,
        border: const OutlineInputBorder(
          borderRadius: AppRadius.roundedSm,
          borderSide: BorderSide(color: AppColors.darkBorder, width: 1),
        ),
        enabledBorder: const OutlineInputBorder(
          borderRadius: AppRadius.roundedSm,
          borderSide: BorderSide(color: AppColors.darkBorder, width: 1),
        ),
        focusedBorder: const OutlineInputBorder(
          borderRadius: AppRadius.roundedSm,
          borderSide: BorderSide(color: AppColors.meriOrangeLight, width: 1.5),
        ),
        hintStyle: AppTypography.bodySmall(color: AppColors.darkTextMuted),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: AppColors.darkCanvas,
        indicatorColor: AppColors.darkSurfaceElevated,
        elevation: 0,
        height: 68,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return AppTypography.labelSmall(color: AppColors.meriOrangeLight)
                .copyWith(fontWeight: FontWeight.w700);
          }
          return AppTypography.labelSmall(color: AppColors.darkTextMuted);
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return const IconThemeData(color: AppColors.meriOrangeLight, size: 24);
          }
          return const IconThemeData(color: AppColors.darkTextMuted, size: 22);
        }),
      ),
      dividerTheme: const DividerThemeData(
        color: AppColors.darkBorder,
        thickness: 1,
        space: 1,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.darkSurfaceElevated,
        selectedColor: AppColors.meriOrange.withValues(alpha: 0.2),
        disabledColor: AppColors.darkBorder,
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.sm,
          vertical: AppSpacing.xs,
        ),
        labelStyle: AppTypography.labelSmall(color: AppColors.darkTextPrimary),
        shape: const RoundedRectangleBorder(
          borderRadius: AppRadius.roundedSm,
          side: BorderSide(color: AppColors.darkBorder),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.meriOrange,
          foregroundColor: Colors.white,
          elevation: 0,
          textStyle: AppTypography.labelLarge(color: Colors.white),
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.buttonRadius,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.sm,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.darkTextPrimary,
          side: const BorderSide(color: AppColors.darkBorder),
          textStyle: AppTypography.labelLarge(color: AppColors.darkTextPrimary),
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.buttonRadius,
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.sm,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.meriOrangeLight,
          textStyle: AppTypography.labelLarge(color: AppColors.meriOrangeLight),
          shape: const RoundedRectangleBorder(
            borderRadius: AppRadius.buttonRadius,
          ),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: AppColors.darkSurfaceElevated,
        contentTextStyle: AppTypography.bodySmall(color: AppColors.darkTextPrimary),
        shape: const RoundedRectangleBorder(
          borderRadius: AppRadius.roundedSm,
        ),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }
}
