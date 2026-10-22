import 'package:flutter/foundation.dart';
import 'package:url_launcher/url_launcher.dart';

/// Testable utility helper for validating YouTube URLs, appending timestamps,
/// and launching external playback.
class YouTubeUrlHelper {
  const YouTubeUrlHelper._();

  static const Set<String> _validHosts = {
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtu.be',
  };

  /// Validates whether [url] is a syntactically valid YouTube video link.
  ///
  /// Supports:
  /// - `https://www.youtube.com/watch?v=...`
  /// - `https://youtube.com/watch?v=...`
  /// - `https://m.youtube.com/watch?v=...`
  /// - `https://youtu.be/...`
  /// - `https://www.youtube.com/embed/...`
  /// - `https://www.youtube.com/v/...`
  /// - `https://www.youtube.com/shorts/...`
  static bool isValidYouTubeUrl(String? url) {
    if (url == null || url.trim().isEmpty) return false;
    final trimmed = url.trim();
    final uri = Uri.tryParse(trimmed);
    if (uri == null || !uri.hasScheme || !uri.hasAuthority) return false;
    if (uri.scheme != 'http' && uri.scheme != 'https') return false;

    final host = uri.host.toLowerCase();
    if (!_validHosts.contains(host)) return false;

    if (host == 'youtu.be') {
      return uri.pathSegments.isNotEmpty && uri.pathSegments.first.isNotEmpty;
    }

    if (uri.queryParameters.containsKey('v') &&
        uri.queryParameters['v']!.isNotEmpty) {
      return true;
    }

    if (uri.pathSegments.isNotEmpty) {
      final first = uri.pathSegments.first;
      if (first == 'embed' || first == 'v' || first == 'shorts') {
        return uri.pathSegments.length > 1 && uri.pathSegments[1].isNotEmpty;
      }
      if (first == 'watch') {
        return uri.queryParameters.containsKey('v') &&
            uri.queryParameters['v']!.isNotEmpty;
      }
    }

    return false;
  }

  /// Converts a validated [baseUrl] and optional [timestampSeconds] into a timestamped [Uri].
  ///
  /// - If [baseUrl] is null, empty, malformed, or not a recognized YouTube URL, returns `null`.
  /// - If [timestampSeconds] is negative, returns `null`.
  /// - If [timestampSeconds] is null, returns the validated base [Uri].
  /// - Replaces any existing `t` query parameter with the new value formatted as `${timestampSeconds}s`.
  static Uri? buildTimestampedUrl(String? baseUrl, int? timestampSeconds) {
    if (!isValidYouTubeUrl(baseUrl)) return null;
    if (timestampSeconds != null && timestampSeconds < 0) return null;

    final uri = Uri.parse(baseUrl!.trim());

    if (timestampSeconds == null) {
      return uri;
    }

    final newParams = Map<String, String>.from(uri.queryParameters);
    newParams['t'] = '${timestampSeconds}s';
    return uri.replace(queryParameters: newParams);
  }

  /// Launches a verified YouTube recording at [timestampSeconds].
  ///
  /// Safe against null, malformed, or failing launcher states.
  static Future<bool> launchYouTubeTimestamp({
    required String? baseUrl,
    required int? timestampSeconds,
    LaunchMode mode = LaunchMode.externalApplication,
  }) async {
    final uri = buildTimestampedUrl(baseUrl, timestampSeconds);
    if (uri == null) return false;

    try {
      return await launchUrl(uri, mode: mode);
    } catch (e) {
      debugPrint('YouTubeUrlHelper failed to launch $uri: $e');
      return false;
    }
  }

  /// Launches a verified YouTube recording from the beginning or its base URL.
  static Future<bool> launchYouTubeVideo({
    required String? baseUrl,
    LaunchMode mode = LaunchMode.externalApplication,
  }) async {
    return launchYouTubeTimestamp(
      baseUrl: baseUrl,
      timestampSeconds: null,
      mode: mode,
    );
  }
}
