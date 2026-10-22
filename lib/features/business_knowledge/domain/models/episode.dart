import 'package:flutter/foundation.dart';
import 'guest.dart';
import 'insight.dart';
import 'quotation.dart';

/// Represents a structured long-form business podcast episode.
@immutable
class Episode {
  const Episode({
    required this.id,
    required this.title,
    required this.podcastTitle,
    required this.episodeNumber,
    required this.durationMinutes,
    required this.publishedAt,
    required this.summary,
    required this.guest,
    required this.insights,
    required this.quotations,
    required this.tags,
    this.audioUrl,
    this.coverImageUrl,
    this.youtubeUrl,
    this.isFeatured = false,
  });

  final String id;
  final String title;
  final String podcastTitle;
  final int episodeNumber;
  final int durationMinutes;
  final DateTime publishedAt;
  final String summary;
  final Guest guest;
  final List<Insight> insights;
  final List<Quotation> quotations;
  final List<String> tags;
  final String? audioUrl;
  final String? coverImageUrl;

  /// Optional verified YouTube recording URL for timestamp-based navigation.
  final String? youtubeUrl;
  final bool isFeatured;

  String get formattedDuration {
    final hours = durationMinutes ~/ 60;
    final mins = durationMinutes % 60;
    if (hours > 0) {
      return '${hours}h ${mins}m';
    }
    return '${mins}m';
  }

  Episode copyWith({
    String? id,
    String? title,
    String? podcastTitle,
    int? episodeNumber,
    int? durationMinutes,
    DateTime? publishedAt,
    String? summary,
    Guest? guest,
    List<Insight>? insights,
    List<Quotation>? quotations,
    List<String>? tags,
    String? audioUrl,
    String? coverImageUrl,
    String? youtubeUrl,
    bool? isFeatured,
  }) {
    return Episode(
      id: id ?? this.id,
      title: title ?? this.title,
      podcastTitle: podcastTitle ?? this.podcastTitle,
      episodeNumber: episodeNumber ?? this.episodeNumber,
      durationMinutes: durationMinutes ?? this.durationMinutes,
      publishedAt: publishedAt ?? this.publishedAt,
      summary: summary ?? this.summary,
      guest: guest ?? this.guest,
      insights: insights ?? this.insights,
      quotations: quotations ?? this.quotations,
      tags: tags ?? this.tags,
      audioUrl: audioUrl ?? this.audioUrl,
      coverImageUrl: coverImageUrl ?? this.coverImageUrl,
      youtubeUrl: youtubeUrl ?? this.youtubeUrl,
      isFeatured: isFeatured ?? this.isFeatured,
    );
  }

  factory Episode.fromJson(Map<String, dynamic> json) {
    return Episode(
      id: json['id'] as String,
      title: json['title'] as String,
      podcastTitle: json['podcastTitle'] as String? ?? 'Meri Podcast',
      episodeNumber: (json['episodeNumber'] as num).toInt(),
      durationMinutes: (json['durationMinutes'] as num).toInt(),
      publishedAt: DateTime.parse(json['publishedAt'] as String),
      summary: json['summary'] as String,
      guest: Guest.fromJson(json['guest'] as Map<String, dynamic>),
      insights: (json['insights'] as List<dynamic>? ?? [])
          .map((e) => Insight.fromJson(e as Map<String, dynamic>))
          .toList(),
      quotations: (json['quotations'] as List<dynamic>? ?? [])
          .map((e) => Quotation.fromJson(e as Map<String, dynamic>))
          .toList(),
      tags: (json['tags'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      audioUrl: json['audioUrl'] as String?,
      coverImageUrl: json['coverImageUrl'] as String?,
      youtubeUrl: json['youtubeUrl'] as String?,
      isFeatured: json['isFeatured'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'title': title,
      'podcastTitle': podcastTitle,
      'episodeNumber': episodeNumber,
      'durationMinutes': durationMinutes,
      'publishedAt': publishedAt.toIso8601String(),
      'summary': summary,
      'guest': guest.toJson(),
      'insights': insights.map((e) => e.toJson()).toList(),
      'quotations': quotations.map((e) => e.toJson()).toList(),
      'tags': tags,
      if (audioUrl != null) 'audioUrl': audioUrl,
      if (coverImageUrl != null) 'coverImageUrl': coverImageUrl,
      if (youtubeUrl != null) 'youtubeUrl': youtubeUrl,
      'isFeatured': isFeatured,
    };
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Episode &&
          runtimeType == other.runtimeType &&
          id == other.id &&
          title == other.title &&
          podcastTitle == other.podcastTitle &&
          episodeNumber == other.episodeNumber &&
          durationMinutes == other.durationMinutes &&
          publishedAt == other.publishedAt &&
          summary == other.summary &&
          guest == other.guest &&
          listEquals(insights, other.insights) &&
          listEquals(quotations, other.quotations) &&
          listEquals(tags, other.tags) &&
          audioUrl == other.audioUrl &&
          coverImageUrl == other.coverImageUrl &&
          youtubeUrl == other.youtubeUrl &&
          isFeatured == other.isFeatured;

  @override
  int get hashCode => Object.hash(
        id,
        title,
        podcastTitle,
        episodeNumber,
        durationMinutes,
        publishedAt,
        summary,
        guest,
        Object.hashAll(insights),
        Object.hashAll(quotations),
        Object.hashAll(tags),
        audioUrl,
        coverImageUrl,
        youtubeUrl,
        isFeatured,
      );

  @override
  String toString() =>
      'Episode(id: $id, ep: #$episodeNumber, title: $title, guest: ${guest.name})';
}
