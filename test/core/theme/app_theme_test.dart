import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:meri/core/theme/app_colors.dart';
import 'package:meri/core/theme/app_radius.dart';
import 'package:meri/core/theme/app_spacing.dart';
import 'package:meri/core/theme/app_theme.dart';
import 'package:meri/core/theme/app_typography.dart';
import 'package:meri/core/widgets/editorial_badge.dart';
import 'package:meri/core/widgets/meri_section_header.dart';
import 'package:meri/core/widgets/meri_wordmark.dart';

void main() {
  setUpAll(() {
    // In test environments, disable runtime network fetching to ensure hermetic execution
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  group('Meri Brand Design Tokens', () {
    test('Core 5 design token hex values match brand specification exactly', () {
      expect(AppColors.meriOrange, const Color(0xFFF47724));
      expect(AppColors.inkBlack, const Color(0xFF191A18));
      expect(AppColors.warmIvory, const Color(0xFFF7F3EB));
      expect(AppColors.archiveSand, const Color(0xFFD8C9AE));
      expect(AppColors.stoneGray, const Color(0xFF686B67));
    });

    test('Editorial typography styles use Playfair Display and Inter conventions', () {
      final headingStyle = AppTypography.titleLarge();
      expect(headingStyle.fontSize, 20);
      expect(headingStyle.fontFamily, contains('PlayfairDisplay'));

      final quoteStyle = AppTypography.quotation();
      expect(quoteStyle.fontSize, 15);
      expect(quoteStyle.fontFamily, contains('PlayfairDisplay'));

      final bodyStyle = AppTypography.bodyMedium();
      expect(bodyStyle.fontSize, 13);
      expect(bodyStyle.fontFamily, contains('Inter'));

      final eyebrowStyle = AppTypography.eyebrow();
      expect(eyebrowStyle.letterSpacing, 1.2);
      expect(eyebrowStyle.fontFamily, contains('Inter'));
    });

    test('Editorial radii are restrained and non-generic', () {
      expect(AppRadius.card, 8.0);
      expect(AppRadius.button, 8.0);
      expect(AppRadius.badge, 4.0);
      expect(AppRadius.sheet, 16.0);
    });

    test('AppSpacing adheres to standard scale', () {
      expect(AppSpacing.xs, 4.0);
      expect(AppSpacing.sm, 8.0);
      expect(AppSpacing.md, 16.0);
      expect(AppSpacing.lg, 24.0);
      expect(AppSpacing.xl, 32.0);
    });
  });

  group('Material 3 AppTheme', () {
    test('Light theme configures Warm Ivory canvas and Meri Orange primary with Material 3', () {
      final theme = AppTheme.lightTheme;

      expect(theme.useMaterial3, isTrue);
      expect(theme.scaffoldBackgroundColor, AppColors.warmIvory);
      expect(theme.colorScheme.primary, AppColors.meriOrange);
      expect(theme.colorScheme.surface, AppColors.paperLight);
      expect(theme.colorScheme.onSurface, AppColors.inkBlack);
      expect(theme.colorScheme.outline, AppColors.archiveSandBorder);
      expect(theme.appBarTheme.backgroundColor, AppColors.warmIvory);
    });

    test('Dark theme configures Ink Night canvas and high contrast with Material 3', () {
      final theme = AppTheme.darkTheme;

      expect(theme.useMaterial3, isTrue);
      expect(theme.scaffoldBackgroundColor, AppColors.darkCanvas);
      expect(theme.colorScheme.surface, AppColors.darkSurface);
      expect(theme.colorScheme.onSurface, AppColors.darkTextPrimary);
      expect(theme.colorScheme.outline, AppColors.darkBorder);
      expect(theme.appBarTheme.backgroundColor, AppColors.darkCanvas);
    });
  });

  group('Meri Brand Widgets', () {
    testWidgets('MeriWordmark renders wordmark and tagline in compact and expanded modes', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                MeriWordmark(isCompact: true),
                MeriWordmark(isCompact: false, tagline: 'Custom editorial tagline'),
              ],
            ),
          ),
        ),
      );

      expect(find.text('MERI'), findsNWidgets(2));
      expect(find.textContaining('The business behind the story.'), findsOneWidget);
      expect(find.text('Custom editorial tagline'), findsOneWidget);
    });

    testWidgets('MeriSectionHeader renders title, eyebrow, and accent bar', (tester) async {
      var actionTapped = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MeriSectionHeader(
              title: 'Masterclass Spotlight',
              eyebrow: 'Verified Entrepreneur Journey',
              actionLabel: 'View Archive',
              onActionPressed: () => actionTapped = true,
            ),
          ),
        ),
      );

      expect(find.text('Masterclass Spotlight'), findsOneWidget);
      expect(find.text('VERIFIED ENTREPRENEUR JOURNEY'), findsOneWidget);
      expect(find.text('View Archive'), findsOneWidget);

      await tester.tap(find.text('View Archive'));
      expect(actionTapped, isTrue);
    });

    testWidgets('EditorialBadge renders with orange, sand, and muted variants', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                EditorialBadge(label: 'AgriTech', variant: EditorialBadgeVariant.orange),
                EditorialBadge(label: 'Episode #101', variant: EditorialBadgeVariant.sand),
                EditorialBadge(label: 'Logistics', variant: EditorialBadgeVariant.muted),
              ],
            ),
          ),
        ),
      );

      expect(find.text('AGRITECH'), findsOneWidget);
      expect(find.text('EPISODE #101'), findsOneWidget);
      expect(find.text('LOGISTICS'), findsOneWidget);
    });

    testWidgets('EditorialBadge handles longer labels and interactive taps with semantics', (tester) async {
      var badgeTapped = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                EditorialBadge(
                  label: 'Transforming Informal Trades Through Standardized Accreditation',
                  maxLines: 2,
                  variant: EditorialBadgeVariant.sand,
                ),
                EditorialBadge(
                  label: 'Filter by Operations',
                  variant: EditorialBadgeVariant.orange,
                  onTap: () => badgeTapped = true,
                  semanticLabel: 'Filter by Operations category',
                  trailingIcon: Icons.arrow_forward_rounded,
                ),
              ],
            ),
          ),
        ),
      );

      expect(
        find.text('TRANSFORMING INFORMAL TRADES THROUGH STANDARDIZED ACCREDITATION'),
        findsOneWidget,
      );
      expect(find.text('FILTER BY OPERATIONS'), findsOneWidget);

      final interactiveFinder = find.bySemanticsLabel('Filter by Operations category');
      expect(interactiveFinder, findsOneWidget);

      await tester.tap(interactiveFinder);
      expect(badgeTapped, isTrue);
    });

    test('Material 3 AppTheme configures flat card, overlay, and hairline divider surfaces', () {
      final lightTheme = AppTheme.lightTheme;
      expect(lightTheme.cardTheme.elevation, 0);
      expect(lightTheme.cardTheme.shadowColor, Colors.transparent);
      expect(lightTheme.dividerTheme.thickness, 1);
      expect(lightTheme.bottomSheetTheme.elevation, 2);
      expect(lightTheme.dialogTheme.elevation, 3);
      expect(lightTheme.inputDecorationTheme.filled, isTrue);

      final darkTheme = AppTheme.darkTheme;
      expect(darkTheme.cardTheme.elevation, 0);
      expect(darkTheme.cardTheme.shadowColor, Colors.transparent);
      expect(darkTheme.dividerTheme.thickness, 1);
      expect(darkTheme.bottomSheetTheme.elevation, 2);
      expect(darkTheme.dialogTheme.elevation, 3);
      expect(darkTheme.inputDecorationTheme.filled, isTrue);
    });

    test('AppTypography provides full editorial headline and label hierarchy', () {
      final displaySmall = AppTypography.displaySmall();
      expect(displaySmall.fontSize, 22);

      final headlineLarge = AppTypography.headlineLarge();
      expect(headlineLarge.fontSize, 24);

      final titleSmall = AppTypography.titleSmall();
      expect(titleSmall.fontSize, 14);

      final labelMedium = AppTypography.labelMedium();
      expect(labelMedium.fontSize, 12);
    });
  });
}
