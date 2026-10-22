import 'package:flutter/material.dart';

/// Design tokens for standardized, restrained border radii.
///
/// Designed with an editorial ethos: subtle, crisp corners that convey
/// permanence and readability rather than exaggerated pill-shaped cards.
abstract class AppRadius {
  // Primitive Radius Values
  static const double xs = 4.0;
  static const double sm = 8.0;
  static const double md = 12.0;
  static const double lg = 16.0;
  static const double xl = 20.0;
  static const double full = 999.0;

  // Semantic Component Radii
  static const double card = sm;
  static const double button = sm;
  static const double badge = xs;
  static const double sheet = lg;

  // Pre-constructed BorderRadius Objects
  static const BorderRadius roundedXs = BorderRadius.all(Radius.circular(xs));
  static const BorderRadius roundedSm = BorderRadius.all(Radius.circular(sm));
  static const BorderRadius roundedMd = BorderRadius.all(Radius.circular(md));
  static const BorderRadius roundedLg = BorderRadius.all(Radius.circular(lg));
  static const BorderRadius roundedXl = BorderRadius.all(Radius.circular(xl));
  static const BorderRadius roundedFull = BorderRadius.all(Radius.circular(full));

  // Semantic BorderRadius Objects
  static const BorderRadius cardRadius = BorderRadius.all(Radius.circular(card));
  static const BorderRadius buttonRadius = BorderRadius.all(Radius.circular(button));
  static const BorderRadius sheetRadius = BorderRadius.vertical(top: Radius.circular(sheet));
}
