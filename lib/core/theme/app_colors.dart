import 'package:flutter/material.dart';

/// Centralized design tokens for Meri's editorial brand foundation.
///
/// Designed around an authentic, culturally grounded Ethiopian publication aesthetic:
/// - Meri Orange: #F47724
/// - Ink Black: #191A18
/// - Warm Ivory: #F7F3EB
/// - Archive Sand: #D8C9AE
/// - Stone Gray: #686B67
abstract class AppColors {
  // ==========================================
  // Core Meri Brand Tokens
  // ==========================================

  /// Primary Brand Accent — vibrant, warm, culturally grounded.
  static const Color meriOrange = Color(0xFFF47724);

  /// Primary Editorial Ink & Dark Mode Canvas — deep, high-contrast, authentic.
  static const Color inkBlack = Color(0xFF191A18);

  /// Primary Light Canvas — warm paper tone inspired by archival publications.
  static const Color warmIvory = Color(0xFFF7F3EB);

  /// Archival Accent & Borders — tactile, sand/ochre muted tone.
  static const Color archiveSand = Color(0xFFD8C9AE);

  /// Functional Stone Neutral — metadata, captions, secondary typography.
  static const Color stoneGray = Color(0xFF686B67);

  // ==========================================
  // Light Editorial Palette (Warm Paper Tones)
  // ==========================================

  /// Card & container surface in light mode (clean paper contrast against ivory canvas).
  static const Color paperLight = Color(0xFFFCFAF7);

  /// Subtle container background for chips and highlighted sections.
  static const Color archiveSandLight = Color(0xFFEFE8DC);

  /// Subtle borders and divider rules in light mode.
  static const Color archiveSandBorder = Color(0xFFD8C9AE);

  /// Deeper archive tone for icons and emphasized badges.
  static const Color archiveSandDark = Color(0xFFB8A584);

  /// Secondary text color for readable body passages.
  static const Color inkCharcoal = Color(0xFF2E302D);

  /// Lighter stone gray for secondary metadata and disabled states.
  static const Color stoneGrayLight = Color(0xFF8A8D89);

  // ==========================================
  // Dark Editorial Palette (Ink Night Tones)
  // ==========================================

  /// Dark mode scaffold background (deep ink).
  static const Color darkCanvas = Color(0xFF121311);

  /// Dark mode card and sheet surface.
  static const Color darkSurface = Color(0xFF1E201D);

  /// Dark mode elevated elements (bottom sheets, dialogs).
  static const Color darkSurfaceElevated = Color(0xFF272A26);

  /// Dark mode outline and card border.
  static const Color darkBorder = Color(0xFF383B35);

  /// Dark mode primary text (warm ivory for eye comfort).
  static const Color darkTextPrimary = Color(0xFFF7F3EB);

  /// Dark mode secondary body text (archive sand).
  static const Color darkTextSecondary = Color(0xFFD8C9AE);

  /// Dark mode muted metadata and captions.
  static const Color darkTextMuted = Color(0xFF8A8D89);

  /// Slightly lifted Meri Orange for dark mode glow/accents.
  static const Color meriOrangeLight = Color(0xFFFF8B3D);

  // ==========================================
  // Status & Feedback Tokens
  // ==========================================

  static const Color success = Color(0xFF2E7D32);
  static const Color error = Color(0xFFBA1A1A);
  static const Color warning = Color(0xFFE65100);
  static const Color info = Color(0xFF0277BD);

  // ==========================================
  // Compatibility Aliases (Seamless Migration)
  // ==========================================

  static const Color ivoryCanvas = warmIvory;
  static const Color ivoryLightest = paperLight;
  static const Color ivorySurface = archiveSandLight;
  static const Color ivoryBorder = archiveSandBorder;

  static const Color inkPrimary = inkBlack;
  static const Color inkSecondary = stoneGray;
  static const Color inkMuted = stoneGrayLight;
  static const Color inkLight = stoneGrayLight;

  static const Color goldPrimary = meriOrange;
  static const Color goldLight = meriOrangeLight;
  static const Color goldDark = meriOrange;
  static const Color goldMuted = archiveSandLight;

  static const Color navyPrimary = inkBlack;
  static const Color navyDarkest = darkCanvas;
  static const Color navyDark = darkSurface;
  static const Color navyLight = darkSurfaceElevated;
  static const Color navySubtle = darkBorder;
}

