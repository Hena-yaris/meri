import 'package:flutter/foundation.dart';

/// Represents an entrepreneurial insight, lesson, or mistake extracted from an interview.
@immutable
class Insight {
  const Insight({
    required this.id,
    required this.episodeId,
    required this.title,
    required this.summary,
    required this.category,
    required this.takeaways,
    this.practicalAction,
  });

  final String id;
  final String episodeId;
  final String title;
  final String summary;
  final String category;
  final List<String> takeaways;
  final String? practicalAction;

  Insight copyWith({
    String? id,
    String? episodeId,
    String? title,
    String? summary,
    String? category,
    List<String>? takeaways,
    String? practicalAction,
  }) {
    return Insight(
      id: id ?? this.id,
      episodeId: episodeId ?? this.episodeId,
      title: title ?? this.title,
      summary: summary ?? this.summary,
      category: category ?? this.category,
      takeaways: takeaways ?? this.takeaways,
      practicalAction: practicalAction ?? this.practicalAction,
    );
  }

  factory Insight.fromJson(Map<String, dynamic> json) {
    return Insight(
      id: json['id'] as String,
      episodeId: json['episodeId'] as String,
      title: json['title'] as String,
      summary: json['summary'] as String,
      category: json['category'] as String,
      takeaways: (json['takeaways'] as List<dynamic>)
          .map((e) => e.toString())
          .toList(),
      practicalAction: json['practicalAction'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'episodeId': episodeId,
      'title': title,
      'summary': summary,
      'category': category,
      'takeaways': takeaways,
      if (practicalAction != null) 'practicalAction': practicalAction,
    };
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Insight &&
          runtimeType == other.runtimeType &&
          id == other.id &&
          episodeId == other.episodeId &&
          title == other.title &&
          summary == other.summary &&
          category == other.category &&
          listEquals(takeaways, other.takeaways) &&
          practicalAction == other.practicalAction;

  @override
  int get hashCode => Object.hash(
        id,
        episodeId,
        title,
        summary,
        category,
        Object.hashAll(takeaways),
        practicalAction,
      );

  @override
  String toString() => 'Insight(id: $id, category: $category, title: $title)';
}
