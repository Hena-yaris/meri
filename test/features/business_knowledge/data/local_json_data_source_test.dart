import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';

void main() {
  group('LocalJsonDataSource', () {
    const validJson = '''
    {
      "episodes": [
        {
          "id": "ep-1",
          "title": "Cold Chain Tech",
          "podcastTitle": "Meri Series",
          "episodeNumber": 1,
          "durationMinutes": 60,
          "publishedAt": "2026-09-01T00:00:00.000Z",
          "summary": "Summary text",
          "isFeatured": true,
          "tags": ["Agritech"],
          "guest": {
            "id": "g-1",
            "name": "Dawit T.",
            "title": "CEO",
            "company": "ColdCo",
            "bio": "Bio"
          },
          "insights": [
            {
              "id": "ins-1",
              "episodeId": "ep-1",
              "title": "Insight 1",
              "summary": "Summary",
              "category": "Logistics",
              "takeaways": ["Takeaway 1"]
            }
          ],
          "quotations": []
        }
      ]
    }
    ''';

    test('loads and parses episodes from JSON loader', () async {
      var loadCallCount = 0;
      final dataSource = LocalJsonDataSource(
        loader: (path) async {
          loadCallCount++;
          return validJson;
        },
      );

      final episodes = await dataSource.loadEpisodes();
      expect(episodes.length, 1);
      expect(episodes.first.id, 'ep-1');
      expect(episodes.first.guest.name, 'Dawit T.');
      expect(loadCallCount, 1);

      // Second call should hit in-memory cache without calling loader again
      final cachedEpisodes = await dataSource.loadEpisodes();
      expect(cachedEpisodes.length, 1);
      expect(loadCallCount, 1);

      // Force refresh should trigger loader again
      await dataSource.loadEpisodes(forceRefresh: true);
      expect(loadCallCount, 2);
    });

    test('throws Exception when JSON is missing "episodes" root key', () async {
      final dataSource = LocalJsonDataSource(
        loader: (path) async => jsonEncode({'invalid': true}),
      );

      expect(
        () => dataSource.loadEpisodes(),
        throwsA(isA<Exception>()),
      );
    });

    test('extracts all insights across episodes with loadAllInsights', () async {
      final dataSource = LocalJsonDataSource(
        loader: (path) async => validJson,
      );

      final insights = await dataSource.loadAllInsights();
      expect(insights.length, 1);
      expect(insights.first.title, 'Insight 1');
    });
  });
}
