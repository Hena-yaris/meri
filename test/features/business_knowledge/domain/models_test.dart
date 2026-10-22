import 'package:flutter_test/flutter_test.dart';
import 'package:meri/features/business_knowledge/domain/models/episode.dart';
import 'package:meri/features/business_knowledge/domain/models/guest.dart';
import 'package:meri/features/business_knowledge/domain/models/insight.dart';
import 'package:meri/features/business_knowledge/domain/models/quotation.dart';

void main() {
  group('Guest Model', () {
    const guestJson = {
      'id': 'g-1',
      'name': 'Dawit Tadesse',
      'title': 'Managing Director',
      'company': 'Nile Cold Chain',
      'bio': 'Logistics entrepreneur.',
      'avatarUrl': 'https://example.com/avatar.jpg',
      'industry': 'Logistics',
    };

    test('parses from JSON correctly', () {
      final guest = Guest.fromJson(guestJson);
      expect(guest.id, 'g-1');
      expect(guest.name, 'Dawit Tadesse');
      expect(guest.title, 'Managing Director');
      expect(guest.company, 'Nile Cold Chain');
      expect(guest.bio, 'Logistics entrepreneur.');
      expect(guest.avatarUrl, 'https://example.com/avatar.jpg');
      expect(guest.industry, 'Logistics');
    });

    test('serializes to JSON correctly', () {
      final guest = Guest.fromJson(guestJson);
      expect(guest.toJson(), guestJson);
    });

    test('copyWith produces updated instance with value equality', () {
      final guest = Guest.fromJson(guestJson);
      final updated = guest.copyWith(company: 'Nile Logistics Group');
      expect(updated.company, 'Nile Logistics Group');
      expect(updated.name, guest.name);
      expect(updated == guest, isFalse);
    });
  });

  group('Insight Model', () {
    const insightJson = {
      'id': 'ins-1',
      'episodeId': 'ep-101',
      'title': 'Cold Chain Economics',
      'summary': 'Asset-light logistics.',
      'category': 'Operations',
      'takeaways': ['Cut upfront capex', 'Leverage telemetry'],
      'practicalAction': 'Audit vehicle fleet leasing.',
    };

    test('parses from JSON and serializes back symmetrically', () {
      final insight = Insight.fromJson(insightJson);
      expect(insight.id, 'ins-1');
      expect(insight.episodeId, 'ep-101');
      expect(insight.title, 'Cold Chain Economics');
      expect(insight.takeaways.length, 2);
      expect(insight.takeaways[0], 'Cut upfront capex');
      expect(insight.practicalAction, 'Audit vehicle fleet leasing.');
      expect(insight.toJson(), insightJson);
    });

    test('supports value equality', () {
      final a = Insight.fromJson(insightJson);
      final b = Insight.fromJson(insightJson);
      expect(a, equals(b));
      expect(a.hashCode, equals(b.hashCode));
    });
  });

  group('Quotation Model', () {
    const quotationJson = {
      'id': 'q-1',
      'episodeId': 'ep-101',
      'amharicQuote': 'የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት አይደለም።',
      'englishTranslation': 'The real challenge is not vehicle ownership.',
      'speaker': 'Dawit Tadesse',
      'timestampSeconds': 1420,
      'context': 'Discussing capital allocation.',
    };

    test('parses from JSON and formats timestamp correctly', () {
      final quote = Quotation.fromJson(quotationJson);
      expect(quote.id, 'q-1');
      expect(quote.amharicQuote, 'የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት አይደለም።');
      expect(quote.speaker, 'Dawit Tadesse');
      expect(quote.timestampSeconds, 1420);
      // 1420 seconds = 23 minutes 40 seconds
      expect(quote.formattedTimestamp, '23:40');
      expect(quote.toJson(), quotationJson);
    });

    test('formats timestamps over one hour properly', () {
      final quote = Quotation.fromJson({
        ...quotationJson,
        'timestampSeconds': 3665, // 1h 1m 5s
      });
      expect(quote.formattedTimestamp, '1:01:05');
    });
  });

  group('Episode Model', () {
    final episodeJson = {
      'id': 'ep-101',
      'title': 'Cold Chain Masterclass',
      'podcastTitle': 'Meri Business Series',
      'episodeNumber': 101,
      'durationMinutes': 74,
      'publishedAt': '2026-09-12T08:00:00.000Z',
      'summary': 'Deep dive into perishable logistics.',
      'isFeatured': true,
      'tags': ['Logistics', 'Agritech'],
      'audioUrl': 'https://sample-audio.meri.et/ep101.mp3',
      'coverImageUrl': null,
      'guest': {
        'id': 'g-1',
        'name': 'Dawit Tadesse',
        'title': 'Managing Director',
        'company': 'Nile Cold Chain',
        'bio': 'Logistics founder.',
        'avatarUrl': null,
        'industry': 'Logistics',
      },
      'insights': [
        {
          'id': 'ins-1',
          'episodeId': 'ep-101',
          'title': 'Fleet Optimization',
          'summary': 'Subcontracting vehicles.',
          'category': 'Operations',
          'takeaways': ['Telemetry is key'],
          'practicalAction': null,
        }
      ],
      'quotations': [
        {
          'id': 'q-1',
          'episodeId': 'ep-101',
          'amharicQuote': 'ዋናው ነገር መማር ነው።',
          'englishTranslation': 'The essence is learning.',
          'speaker': 'Dawit Tadesse',
          'timestampSeconds': 600,
          'context': 'Context snippet.',
        }
      ],
    };

    test('parses full episode with nested guest, insights, and quotations', () {
      final episode = Episode.fromJson(episodeJson);
      expect(episode.id, 'ep-101');
      expect(episode.episodeNumber, 101);
      expect(episode.guest.name, 'Dawit Tadesse');
      expect(episode.insights.length, 1);
      expect(episode.quotations.length, 1);
      expect(episode.formattedDuration, '1h 14m');
      expect(episode.isFeatured, isTrue);
      expect(episode.youtubeUrl, isNull);
    });

    test('formats sub-hour duration correctly', () {
      final episode = Episode.fromJson({
        ...episodeJson,
        'durationMinutes': 45,
      });
      expect(episode.formattedDuration, '45m');
    });

    test('parses and serializes youtubeUrl correctly when present', () {
      final withYoutube = {
        ...episodeJson,
        'youtubeUrl': 'https://www.youtube.com/watch?v=sample-ep101',
      };
      final episode = Episode.fromJson(withYoutube);
      expect(episode.youtubeUrl, 'https://www.youtube.com/watch?v=sample-ep101');

      final serialized = episode.toJson();
      expect(serialized['youtubeUrl'], 'https://www.youtube.com/watch?v=sample-ep101');
    });

    test('handles absent or null youtubeUrl cleanly in toJson', () {
      final episode = Episode.fromJson(episodeJson);
      expect(episode.youtubeUrl, isNull);
      final serialized = episode.toJson();
      expect(serialized.containsKey('youtubeUrl'), isFalse);
    });

    test('copyWith updates youtubeUrl cleanly', () {
      final episode = Episode.fromJson(episodeJson);
      final updated = episode.copyWith(
        youtubeUrl: 'https://youtu.be/updated-id',
      );
      expect(updated.youtubeUrl, 'https://youtu.be/updated-id');
      expect(updated.id, episode.id);
      expect(episode.youtubeUrl, isNull);
    });
  });
}

