import 'package:flutter_test/flutter_test.dart';
import 'package:meri/features/bookmarks/data/datasources/bookmarks_local_data_source.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('SharedPreferencesBookmarksDataSource', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('loads empty set when no key exists', () async {
      final dataSource = SharedPreferencesBookmarksDataSource();
      final ids = await dataSource.loadBookmarkedIds();
      expect(ids, isEmpty);
    });

    test('loads existing saved IDs', () async {
      SharedPreferences.setMockInitialValues({
        SharedPreferencesBookmarksDataSource.key: ['ep-101', 'ep-102'],
      });
      final dataSource = SharedPreferencesBookmarksDataSource();
      final ids = await dataSource.loadBookmarkedIds();
      expect(ids, equals({'ep-101', 'ep-102'}));
    });

    test('saves bookmarked IDs successfully', () async {
      final dataSource = SharedPreferencesBookmarksDataSource();
      final success = await dataSource.saveBookmarkedIds({'ep-101', 'ep-103'});
      expect(success, isTrue);

      final loaded = await dataSource.loadBookmarkedIds();
      expect(loaded, equals({'ep-101', 'ep-103'}));
    });
  });
}
