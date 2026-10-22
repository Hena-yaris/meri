import 'package:flutter_test/flutter_test.dart';
import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';
import 'package:meri/features/business_knowledge/data/repositories/local_knowledge_repository.dart';

void main() {
  group('LocalKnowledgeRepository', () {
    const testJson = '''
    {
      "episodes": [
        {
          "id": "ep-old",
          "title": "Earlier Episode",
          "podcastTitle": "Meri Series",
          "episodeNumber": 1,
          "durationMinutes": 50,
          "publishedAt": "2026-08-01T00:00:00.000Z",
          "summary": "Older story on textile exports",
          "isFeatured": false,
          "tags": ["Export", "Textiles"],
          "guest": {
            "id": "g-1",
            "name": "Almaz Bekele",
            "title": "Founder",
            "company": "Sheba Weavers",
            "bio": "Textile pioneer",
            "industry": "Manufacturing"
          },
          "insights": [
            {
              "id": "ins-1",
              "episodeId": "ep-old",
              "title": "Export Quality Controls",
              "summary": "Strict QA avoids returns",
              "category": "Operations",
              "takeaways": ["Inspect every lot"]
            }
          ],
          "quotations": []
        },
        {
          "id": "ep-new",
          "title": "Newer Episode on Cold Chain",
          "podcastTitle": "Meri Series",
          "episodeNumber": 2,
          "durationMinutes": 75,
          "publishedAt": "2026-09-15T00:00:00.000Z",
          "summary": "Cold storage logistics story",
          "isFeatured": true,
          "tags": ["Logistics", "Agritech"],
          "guest": {
            "id": "g-2",
            "name": "Dawit Tadesse",
            "title": "Managing Director",
            "company": "Nile Cold Chain",
            "bio": "Logistics entrepreneur",
            "industry": "Logistics"
          },
          "insights": [
            {
              "id": "ins-2",
              "episodeId": "ep-new",
              "title": "Telemetry Over Fleet Size",
              "summary": "Sensor networks save capital",
              "category": "Technology",
              "takeaways": ["Fit sensors on partner trucks"]
            }
          ],
          "quotations": []
        }
      ]
    }
    ''';

    late LocalKnowledgeRepository repository;

    setUp(() {
      final dataSource = LocalJsonDataSource(
        loader: (path) async => testJson,
      );
      repository = LocalKnowledgeRepository(dataSource: dataSource);
    });

    test('getEpisodes returns all episodes sorted newest first', () async {
      final episodes = await repository.getEpisodes();
      expect(episodes.length, 2);
      expect(episodes[0].id, 'ep-new'); // 2026-09-15
      expect(episodes[1].id, 'ep-old'); // 2026-08-01
    });

    test('getEpisodeById returns matching episode or null', () async {
      final found = await repository.getEpisodeById('ep-new');
      expect(found, isNotNull);
      expect(found?.guest.name, 'Dawit Tadesse');

      final notFound = await repository.getEpisodeById('ep-unknown');
      expect(notFound, isNull);
    });

    test('getFeaturedEpisode returns episode marked as isFeatured', () async {
      final featured = await repository.getFeaturedEpisode();
      expect(featured, isNotNull);
      expect(featured?.id, 'ep-new');
      expect(featured?.isFeatured, isTrue);
    });

    test('getFeaturedInsights aggregates insights across all episodes', () async {
      final insights = await repository.getFeaturedInsights();
      expect(insights.length, 2);
      final titles = insights.map((i) => i.title).toList();
      expect(titles, containsAll(['Export Quality Controls', 'Telemetry Over Fleet Size']));
    });

    test('searchEpisodes matches title, guest, company, and tags case-insensitively', () async {
      // Search by company
      final byCompany = await repository.searchEpisodes('sheba');
      expect(byCompany.length, 1);
      expect(byCompany.first.id, 'ep-old');

      // Search by guest name
      final byGuest = await repository.searchEpisodes('dawit');
      expect(byGuest.length, 1);
      expect(byGuest.first.id, 'ep-new');

      // Search by tag
      final byTag = await repository.searchEpisodes('agritech');
      expect(byTag.length, 1);
      expect(byTag.first.id, 'ep-new');

      // Empty query returns all episodes
      final all = await repository.searchEpisodes('');
      expect(all.length, 2);
    });

    test('searchEpisodes filters by category topic correctly', () async {
      final exportEpisodes = await repository.searchEpisodes('', category: 'Export');
      expect(exportEpisodes.length, 1);
      expect(exportEpisodes.first.id, 'ep-old');

      final logisticsEpisodes = await repository.searchEpisodes('', category: 'Logistics');
      expect(logisticsEpisodes.length, 1);
      expect(logisticsEpisodes.first.id, 'ep-new');

      // Category "All" returns all episodes
      final allCategories = await repository.searchEpisodes('', category: 'All');
      expect(allCategories.length, 2);

      // Non-matching category returns empty
      final emptyCategory = await repository.searchEpisodes('', category: 'Biotech');
      expect(emptyCategory, isEmpty);
    });

    test('searchEpisodes supports combined query and category filtering', () async {
      // Matching both query and category
      final matchingBoth = await repository.searchEpisodes('sheba', category: 'Export');
      expect(matchingBoth.length, 1);
      expect(matchingBoth.first.id, 'ep-old');

      // Query matches, but category does not
      final mismatched = await repository.searchEpisodes('sheba', category: 'Logistics');
      expect(mismatched, isEmpty);
    });
  });
}
