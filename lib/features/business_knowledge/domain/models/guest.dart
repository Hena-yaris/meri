import 'package:flutter/foundation.dart';

/// Represents a verified entrepreneur or business leader featured on Meri.
@immutable
class Guest {
  const Guest({
    required this.id,
    required this.name,
    required this.title,
    required this.company,
    required this.bio,
    this.avatarUrl,
    this.industry,
  });

  final String id;
  final String name;
  final String title;
  final String company;
  final String bio;
  final String? avatarUrl;
  final String? industry;

  Guest copyWith({
    String? id,
    String? name,
    String? title,
    String? company,
    String? bio,
    String? avatarUrl,
    String? industry,
  }) {
    return Guest(
      id: id ?? this.id,
      name: name ?? this.name,
      title: title ?? this.title,
      company: company ?? this.company,
      bio: bio ?? this.bio,
      avatarUrl: avatarUrl ?? this.avatarUrl,
      industry: industry ?? this.industry,
    );
  }

  factory Guest.fromJson(Map<String, dynamic> json) {
    return Guest(
      id: json['id'] as String,
      name: json['name'] as String,
      title: json['title'] as String,
      company: json['company'] as String,
      bio: json['bio'] as String,
      avatarUrl: json['avatarUrl'] as String?,
      industry: json['industry'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'title': title,
      'company': company,
      'bio': bio,
      if (avatarUrl != null) 'avatarUrl': avatarUrl,
      if (industry != null) 'industry': industry,
    };
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Guest &&
          runtimeType == other.runtimeType &&
          id == other.id &&
          name == other.name &&
          title == other.title &&
          company == other.company &&
          bio == other.bio &&
          avatarUrl == other.avatarUrl &&
          industry == other.industry;

  @override
  int get hashCode => Object.hash(
        id,
        name,
        title,
        company,
        bio,
        avatarUrl,
        industry,
      );

  @override
  String toString() =>
      'Guest(id: $id, name: $name, company: $company, title: $title)';
}
