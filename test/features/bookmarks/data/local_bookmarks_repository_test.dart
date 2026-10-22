import 'package:flutter_test/flutter_test.dart';
import 'package:meri/features/bookmarks/data/datasources/bookmarks_local_data_source.dart';
import 'package:meri/features/bookmarks/data/repositories/local_bookmarks_repository.dart';

class FakeBookmarksLocalDataSource implements BookmarksLocalDataSource {
  Set<String> storedIds = {};
  bool shouldThrow = false;
  int saveCallCount = 0;

  @override
  Future<Set<String>> loadBookmarkedIds() async {
    if (shouldThrow) throw Exception('Disk read error');
    return Set<String>.from(storedIds);
  }

  @override
  Future<bool> saveBookmarkedIds(Set<String> ids) async {
    if (shouldThrow) throw Exception('Disk write error');
    saveCallCount++;
    storedIds = Set<String>.from(ids);
    return true;
  }
}

void main() {
  group('LocalBookmarksRepository', () {
    late FakeBookmarksLocalDataSource fakeDataSource;
    late LocalBookmarksRepository repository;

    setUp(() {
      fakeDataSource = FakeBookmarksLocalDataSource();
      repository = LocalBookmarksRepository(dataSource: fakeDataSource);
    });

    test('correct initial state for an empty store', () async {
      final bookmarks = await repository.getBookmarkedEpisodeIds();
      expect(bookmarks, isEmpty);
    });

    test('restoring bookmarks from persistence returns saved IDs', () async {
      fakeDataSource.storedIds = {'ep-101', 'ep-102'};
      final bookmarks = await repository.getBookmarkedEpisodeIds();
      expect(bookmarks, equals({'ep-101', 'ep-102'}));
    });

    test('adding a bookmark persists ID successfully', () async {
      await repository.addBookmark('ep-101');
      expect(await repository.getBookmarkedEpisodeIds(), contains('ep-101'));
      expect(await repository.isBookmarked('ep-101'), isTrue);
      expect(fakeDataSource.saveCallCount, 1);
    });

    test('removing a bookmark updates persistent storage', () async {
      fakeDataSource.storedIds = {'ep-101', 'ep-102'};
      await repository.removeBookmark('ep-101');
      expect(await repository.getBookmarkedEpisodeIds(), equals({'ep-102'}));
      expect(await repository.isBookmarked('ep-101'), isFalse);
      expect(fakeDataSource.saveCallCount, 1);
    });

    test('avoids duplicate IDs and avoids redundant writes', () async {
      fakeDataSource.storedIds = {'ep-101'};
      // Attempt to add duplicate
      await repository.addBookmark('ep-101');
      expect(fakeDataSource.saveCallCount, 0); // No write triggered
      expect(await repository.getBookmarkedEpisodeIds(), equals({'ep-101'}));

      // Attempt to remove nonexistent
      await repository.removeBookmark('ep-999');
      expect(fakeDataSource.saveCallCount, 0); // No write triggered
    });

    test('toggleBookmark toggles state appropriately', () async {
      // Add via toggle
      final added = await repository.toggleBookmark('ep-103');
      expect(added, isTrue);
      expect(await repository.isBookmarked('ep-103'), isTrue);

      // Remove via toggle
      final removed = await repository.toggleBookmark('ep-103');
      expect(removed, isFalse);
      expect(await repository.isBookmarked('ep-103'), isFalse);
    });

    test('ignores empty or whitespace IDs safely', () async {
      await repository.addBookmark('');
      await repository.addBookmark('   ');
      await repository.removeBookmark('');
      expect(fakeDataSource.saveCallCount, 0);
      expect(await repository.getBookmarkedEpisodeIds(), isEmpty);
    });

    test('graceful handling of persistence errors', () async {
      fakeDataSource.shouldThrow = true;
      expect(() => repository.addBookmark('ep-101'), throwsA(isA<Exception>()));
    });
  });
}
