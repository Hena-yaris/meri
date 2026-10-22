import 'package:flutter/foundation.dart';

/// Represents an original-language quotation linked to an interview timestamp.
@immutable
class Quotation {
  const Quotation({
    required this.id,
    required this.episodeId,
    required this.amharicQuote,
    required this.englishTranslation,
    required this.speaker,
    required this.timestampSeconds,
    required this.context,
  });

  final String id;
  final String episodeId;
  final String amharicQuote;
  final String englishTranslation;
  final String speaker;
  final int timestampSeconds;
  final String context;

  /// Returns a formatted timestamp string, e.g. "23:40" or "1:05:20".
  String get formattedTimestamp {
    final hours = timestampSeconds ~/ 3600;
    final minutes = (timestampSeconds % 3600) ~/ 60;
    final seconds = timestampSeconds % 60;

    final minutesStr = minutes.toString().padLeft(hours > 0 ? 2 : 1, '0');
    final secondsStr = seconds.toString().padLeft(2, '0');

    if (hours > 0) {
      return '$hours:$minutesStr:$secondsStr';
    }
    return '$minutesStr:$secondsStr';
  }

  Quotation copyWith({
    String? id,
    String? episodeId,
    String? amharicQuote,
    String? englishTranslation,
    String? speaker,
    int? timestampSeconds,
    String? context,
  }) {
    return Quotation(
      id: id ?? this.id,
      episodeId: episodeId ?? this.episodeId,
      amharicQuote: amharicQuote ?? this.amharicQuote,
      englishTranslation: englishTranslation ?? this.englishTranslation,
      speaker: speaker ?? this.speaker,
      timestampSeconds: timestampSeconds ?? this.timestampSeconds,
      context: context ?? this.context,
    );
  }

  factory Quotation.fromJson(Map<String, dynamic> json) {
    return Quotation(
      id: json['id'] as String,
      episodeId: json['episodeId'] as String,
      amharicQuote: json['amharicQuote'] as String,
      englishTranslation: json['englishTranslation'] as String,
      speaker: json['speaker'] as String,
      timestampSeconds: (json['timestampSeconds'] as num).toInt(),
      context: json['context'] as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'episodeId': episodeId,
      'amharicQuote': amharicQuote,
      'englishTranslation': englishTranslation,
      'speaker': speaker,
      'timestampSeconds': timestampSeconds,
      'context': context,
    };
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Quotation &&
          runtimeType == other.runtimeType &&
          id == other.id &&
          episodeId == other.episodeId &&
          amharicQuote == other.amharicQuote &&
          englishTranslation == other.englishTranslation &&
          speaker == other.speaker &&
          timestampSeconds == other.timestampSeconds &&
          context == other.context;

  @override
  int get hashCode => Object.hash(
        id,
        episodeId,
        amharicQuote,
        englishTranslation,
        speaker,
        timestampSeconds,
        context,
      );

  @override
  String toString() =>
      'Quotation(id: $id, speaker: $speaker, at: $formattedTimestamp)';
}
