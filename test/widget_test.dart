import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:meri/app/app.dart';
import 'package:meri/features/business_knowledge/data/datasources/local_json_data_source.dart';
import 'package:meri/features/business_knowledge/data/providers.dart';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  const testSampleJson = '''
  {
    "episodes": [
      {
        "id": "ep-101",
        "title": "Scaling Cold Chain Logistics Across Agricultural Corridors",
        "podcastTitle": "Meri Business Series",
        "episodeNumber": 101,
        "durationMinutes": 74,
        "publishedAt": "2026-09-12T08:00:00.000Z",
        "summary": "An in-depth exploration into the structural obstacles of agricultural freight.",
        "isFeatured": true,
        "tags": ["Logistics", "Agritech"],
        "guest": {
          "id": "guest-dawit",
          "name": "Dawit Tadesse",
          "title": "Founder",
          "company": "Nile Cold Chain",
          "bio": "Mechanical engineer turned entrepreneur."
        },
        "insights": [
          {
            "id": "ins-1",
            "episodeId": "ep-101",
            "title": "Decoupling Fleet Ownership",
            "summary": "Partnering with regional truck owners saves capital.",
            "category": "Operations",
            "takeaways": ["Heavy assets tie down working capital"]
          }
        ],
        "quotations": [
          {
            "id": "q-1",
            "episodeId": "ep-101",
            "amharicQuote": "የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት አይደለም።",
            "englishTranslation": "The real test in logistics is not buying trucks.",
            "speaker": "Dawit Tadesse",
            "timestampSeconds": 1420,
            "context": "Context quote."
          }
        ]
      }
    ]
  }
  ''';

  testWidgets('MeriApp boots, displays editorial masthead, tabs, and sample content', (tester) async {
    // Provide a mocked LocalJsonDataSource for hermetic widget testing
    final mockDataSource = LocalJsonDataSource(
      loader: (path) async => testSampleJson,
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          localJsonDataSourceProvider.overrideWithValue(mockDataSource),
        ],
        child: const MeriApp(),
      ),
    );

    // Initial pump
    await tester.pump();
    // Allow async providers to resolve
    await tester.pumpAndSettle();

    // Verify editorial masthead
    expect(find.text('MERI'), findsOneWidget);

    // Verify navigation tabs
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Explore'), findsOneWidget);
    expect(find.text('Bookmarks'), findsOneWidget);
    expect(find.text('Settings'), findsOneWidget);

    // Verify featured section and sample card
    expect(find.text('Masterclass Spotlight'), findsOneWidget);
    expect(find.text('Dawit Tadesse'), findsWidgets);
    expect(find.text('Scaling Cold Chain Logistics Across Agricultural Corridors'), findsOneWidget);

    // Verify Amharic quotation rendering
    expect(find.text('“የሎጂስቲክስ ስራ ትልቁ ፈተና መኪና መግዛት አይደለም።”'), findsOneWidget);

    // Test tab navigation to Explore
    await tester.tap(find.text('Explore'));
    await tester.pumpAndSettle();
    expect(find.text('Explore Knowledge'), findsOneWidget);

    // Test tab navigation to Settings
    await tester.tap(find.text('Settings'));
    await tester.pumpAndSettle();
    expect(find.text('Settings & About'), findsOneWidget);
  });
}
