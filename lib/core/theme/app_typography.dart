import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'app_colors.dart';

/// Centralized editorial typography tokens for Meri.
///
/// Implements Meri's editorial brand typography:
/// - Playfair Display: Major editorial headings, section titles, and selected quotations.
/// - Inter: Functional body text, navigation, buttons, labels, and metadata.
///
/// Robust system font fallbacks ('Georgia'/'serif' and 'Roboto'/'sans-serif')
/// ensure graceful offline degradation if network font loading is delayed.
abstract class AppTypography {
  // ==========================================
  // Editorial Serif Headings (Playfair Display)
  // ==========================================

  /// Large editorial banner title (e.g., hero titles, feature headlines).
  static TextStyle displayLarge({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 32,
        fontWeight: FontWeight.w800,
        letterSpacing: -0.5,
        height: 1.25,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Secondary editorial heading.
  static TextStyle displayMedium({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 26,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.3,
        height: 1.3,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Primary screen and section heading.
  static TextStyle titleLarge({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.2,
        height: 1.35,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Card titles, subheadings, and sheet headers.
  static TextStyle titleMedium({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.1,
        height: 1.4,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Compact editorial title for nested cards or minor sections.
  static TextStyle titleSmall({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.05,
        height: 1.4,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Compact editorial display for sub-hero highlights.
  static TextStyle displaySmall({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 22,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.2,
        height: 1.35,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Prominent editorial section headline.
  static TextStyle headlineLarge({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 24,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.3,
        height: 1.3,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Medium editorial section headline.
  static TextStyle headlineMedium({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.2,
        height: 1.35,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Compact editorial section headline.
  static TextStyle headlineSmall({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.1,
        height: 1.4,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Distinctive editorial quotation style for English quotations.
  static TextStyle quotation({
    Color color = AppColors.inkBlack,
    bool isItalic = true,
  }) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 15,
        fontWeight: FontWeight.w500,
        fontStyle: isItalic ? FontStyle.italic : FontStyle.normal,
        height: 1.6,
        letterSpacing: 0.1,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  /// Authentic upright typography for Amharic quotations and Ethiopic script.
  ///
  /// Prevents culturally and typographically invalid faux-italics (oblique distortion)
  /// on Ge'ez fidel characters while maintaining proper line height and a resilient
  /// system fallback chain ('Noto Serif Ethiopic', 'Noto Sans Ethiopic', 'Nyala').
  static TextStyle amharicQuotation({
    Color color = AppColors.inkBlack,
    double fontSize = 16,
  }) {
    return TextStyle(
      fontSize: fontSize,
      fontWeight: FontWeight.w500,
      fontStyle: FontStyle.normal, // Ethiopic scripts must strictly remain upright
      height: 1.65,
      letterSpacing: 0.0, // Preserve standard Ge'ez kerning and fidel vowel marks
      color: color,
      fontFamilyFallback: const [
        'Noto Serif Ethiopic',
        'Noto Sans Ethiopic',
        'Nyala',
        'Abyssinica SIL',
        'serif',
      ],
    );
  }

  /// Brand wordmark typography for "MERI" editorial masthead.
  static TextStyle wordmark({Color color = AppColors.inkBlack}) {
    return GoogleFonts.playfairDisplay(
      textStyle: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w900,
        letterSpacing: 2.2,
        height: 1.2,
        color: color,
        fontFamilyFallback: const ['Georgia', 'serif'],
      ),
    );
  }

  // ==========================================
  // Functional Sans-Serif Body & Interface (Inter)
  // ==========================================

  /// Primary reading body text with enhanced line-height for editorial legibility.
  static TextStyle bodyLarge({Color color = AppColors.inkBlack}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 15,
        fontWeight: FontWeight.w400,
        height: 1.6,
        letterSpacing: 0.15,
        color: color,
        fontFamilyFallback: const ['Roboto', 'sans-serif'],
      ),
    );
  }

  /// Standard body copy for cards, summaries, and dialogs.
  static TextStyle bodyMedium({Color color = AppColors.stoneGray}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 13,
        fontWeight: FontWeight.w400,
        height: 1.5,
        letterSpacing: 0.1,
        color: color,
        fontFamilyFallback: const ['Roboto', 'sans-serif'],
      ),
    );
  }

  /// Secondary metadata, timestamps, and compact descriptions.
  static TextStyle bodySmall({Color color = AppColors.stoneGray}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w400,
        height: 1.4,
        letterSpacing: 0.1,
        color: color,
        fontFamilyFallback: const ['Roboto', 'sans-serif'],
      ),
    );
  }

  /// Section category eyebrows, badge labels, and tracked sub-headers.
  static TextStyle eyebrow({Color color = AppColors.meriOrange}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 11,
        fontWeight: FontWeight.w700,
        letterSpacing: 1.2,
        height: 1.2,
        color: color,
        fontFamilyFallback: const ['Roboto', 'sans-serif'],
      ),
    );
  }

  /// Interactive button text, prominent chip labels, and navigation labels.
  static TextStyle labelLarge({Color color = AppColors.inkBlack}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.2,
        color: color,
        fontFamilyFallback: const ['Roboto', 'sans-serif'],
      ),
    );
  }

  /// Medium functional label for secondary buttons, filters, and chips.
  static TextStyle labelMedium({Color color = AppColors.inkBlack}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.3,
        color: color,
        fontFamilyFallback: const ['Roboto', 'sans-serif'],
      ),
    );
  }

  /// Fine metadata, tags, and badge chips.
  static TextStyle labelSmall({Color color = AppColors.stoneGray}) {
    return GoogleFonts.inter(
      textStyle: TextStyle(
        fontSize: 10,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.4,
        color: color,
        fontFamilyFallback: const ['Roboto', 'sans-serif'],
      ),
    );
  }

  /// Builds a cohesive Material 3 [TextTheme] binding Playfair Display and Inter.
  static TextTheme createTextTheme(Color primaryTextColor, Color secondaryTextColor) {
    return TextTheme(
      displayLarge: displayLarge(color: primaryTextColor),
      displayMedium: displayMedium(color: primaryTextColor),
      displaySmall: displaySmall(color: primaryTextColor),
      headlineLarge: headlineLarge(color: primaryTextColor),
      headlineMedium: headlineMedium(color: primaryTextColor),
      headlineSmall: headlineSmall(color: primaryTextColor),
      titleLarge: titleLarge(color: primaryTextColor),
      titleMedium: titleMedium(color: primaryTextColor),
      titleSmall: titleSmall(color: primaryTextColor),
      bodyLarge: bodyLarge(color: primaryTextColor),
      bodyMedium: bodyMedium(color: secondaryTextColor),
      bodySmall: bodySmall(color: secondaryTextColor),
      labelLarge: labelLarge(color: primaryTextColor),
      labelMedium: labelMedium(color: primaryTextColor),
      labelSmall: labelSmall(color: secondaryTextColor),
    );
  }
}
