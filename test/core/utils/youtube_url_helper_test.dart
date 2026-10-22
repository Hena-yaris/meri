import 'package:flutter_test/flutter_test.dart';
import 'package:meri/core/utils/youtube_url_helper.dart';

void main() {
  group('YouTubeUrlHelper.isValidYouTubeUrl', () {
    test('accepts valid standard youtube watch URLs', () {
      expect(
        YouTubeUrlHelper.isValidYouTubeUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ'),
        isTrue,
      );
      expect(
        YouTubeUrlHelper.isValidYouTubeUrl('https://youtube.com/watch?v=dQw4w9WgXcQ'),
        isTrue,
      );
      expect(
        YouTubeUrlHelper.isValidYouTubeUrl('http://www.youtube.com/watch?v=dQw4w9WgXcQ'),
        isTrue,
      );
      expect(
        YouTubeUrlHelper.isValidYouTubeUrl('https://m.youtube.com/watch?v=dQw4w9WgXcQ'),
        isTrue,
      );
    });

    test('accepts valid youtu.be short URLs', () {
      expect(
        YouTubeUrlHelper.isValidYouTubeUrl('https://youtu.be/dQw4w9WgXcQ'),
        isTrue,
      );
      expect(
        YouTubeUrlHelper.isValidYouTubeUrl('http://youtu.be/sample-102'),
        isTrue,
      );
    });

    test('accepts embed and shorts URLs', () {
      expect(
        YouTubeUrlHelper.isValidYouTubeUrl('https://www.youtube.com/embed/dQw4w9WgXcQ'),
        isTrue,
      );
      expect(
        YouTubeUrlHelper.isValidYouTubeUrl('https://www.youtube.com/shorts/dQw4w9WgXcQ'),
        isTrue,
      );
    });

    test('rejects null, empty, or whitespace strings', () {
      expect(YouTubeUrlHelper.isValidYouTubeUrl(null), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl(''), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl('   '), isFalse);
    });

    test('rejects malformed and non-HTTP URLs', () {
      expect(YouTubeUrlHelper.isValidYouTubeUrl('not a url'), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl('ftp://youtube.com/watch?v=123'), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl('://invalid'), isFalse);
    });

    test('rejects non-YouTube domains', () {
      expect(YouTubeUrlHelper.isValidYouTubeUrl('https://vimeo.com/12345'), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl('https://example.com/watch?v=dQw4w9WgXcQ'), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl('https://notyoutube.com/watch?v=123'), isFalse);
    });

    test('rejects YouTube URLs missing video IDs', () {
      expect(YouTubeUrlHelper.isValidYouTubeUrl('https://www.youtube.com'), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl('https://www.youtube.com/watch'), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl('https://www.youtube.com/watch?v='), isFalse);
      expect(YouTubeUrlHelper.isValidYouTubeUrl('https://youtu.be/'), isFalse);
    });
  });

  group('YouTubeUrlHelper.buildTimestampedUrl', () {
    test('appends timestamp to standard watch URL', () {
      final uri = YouTubeUrlHelper.buildTimestampedUrl(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        1420,
      );
      expect(uri, isNotNull);
      expect(uri!.scheme, 'https');
      expect(uri.host, 'www.youtube.com');
      expect(uri.path, '/watch');
      expect(uri.queryParameters['v'], 'dQw4w9WgXcQ');
      expect(uri.queryParameters['t'], '1420s');
    });

    test('appends timestamp to youtu.be short URL', () {
      final uri = YouTubeUrlHelper.buildTimestampedUrl(
        'https://youtu.be/dQw4w9WgXcQ',
        1845,
      );
      expect(uri, isNotNull);
      expect(uri!.host, 'youtu.be');
      expect(uri.path, '/dQw4w9WgXcQ');
      expect(uri.queryParameters['t'], '1845s');
    });

    test('replaces existing timestamp parameter cleanly', () {
      final uri = YouTubeUrlHelper.buildTimestampedUrl(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=50s',
        3600,
      );
      expect(uri, isNotNull);
      expect(uri!.queryParameters['t'], '3600s');
    });

    test('preserves existing additional query parameters', () {
      final uri = YouTubeUrlHelper.buildTimestampedUrl(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL12345&index=3',
        600,
      );
      expect(uri, isNotNull);
      expect(uri!.queryParameters['v'], 'dQw4w9WgXcQ');
      expect(uri.queryParameters['list'], 'PL12345');
      expect(uri.queryParameters['index'], '3');
      expect(uri.queryParameters['t'], '600s');
    });

    test('supports zero timestamp (0s)', () {
      final uri = YouTubeUrlHelper.buildTimestampedUrl(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        0,
      );
      expect(uri, isNotNull);
      expect(uri!.queryParameters['t'], '0s');
    });

    test('returns base URL as URI when timestamp is null', () {
      final uri = YouTubeUrlHelper.buildTimestampedUrl(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        null,
      );
      expect(uri, isNotNull);
      expect(uri!.queryParameters.containsKey('t'), isFalse);
      expect(uri.queryParameters['v'], 'dQw4w9WgXcQ');
    });

    test('returns null for negative timestamp', () {
      final uri = YouTubeUrlHelper.buildTimestampedUrl(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        -10,
      );
      expect(uri, isNull);
    });

    test('returns null for null, empty, or invalid base URL', () {
      expect(YouTubeUrlHelper.buildTimestampedUrl(null, 120), isNull);
      expect(YouTubeUrlHelper.buildTimestampedUrl('', 120), isNull);
      expect(YouTubeUrlHelper.buildTimestampedUrl('   ', 120), isNull);
      expect(YouTubeUrlHelper.buildTimestampedUrl('invalid url', 120), isNull);
      expect(YouTubeUrlHelper.buildTimestampedUrl('https://example.com/video', 120), isNull);
    });
  });
}
