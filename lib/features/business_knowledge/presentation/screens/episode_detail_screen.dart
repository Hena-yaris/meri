import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_radius.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../../../core/utils/youtube_url_helper.dart';
import '../../../../core/widgets/async_value_widget.dart';
import '../../../../core/widgets/editorial_badge.dart';
import '../../../../core/widgets/meri_section_header.dart';
import '../../../bookmarks/data/providers.dart';
import '../../data/providers.dart';
import '../../domain/models/episode.dart';
import '../../domain/models/guest.dart';
import '../../domain/models/insight.dart';
import '../../domain/models/quotation.dart';

/// Screen displaying the complete editorial details of an interview episode.
///
/// Features:
/// - Title, duration, summary, and tags.
/// - Featured guest background, company, industry, and bio.
/// - Full actionable insights with takeaways and practical actions.
/// - Primary quotations with Amharic script, English translation, and
///   actionable YouTube timestamps when a source URL is verified.
class EpisodeDetailScreen extends ConsumerWidget {
  const EpisodeDetailScreen({
    super.key,
    required this.episodeId,
  });

  final String episodeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final episodeAsync = ref.watch(episodeByIdProvider(episodeId));
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final isBookmarked =
        ref.watch(bookmarksProvider).value?.contains(episodeId) ?? false;

    final currentEpisode = episodeAsync.asData?.value;

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          tooltip: 'Back to archive',
          onPressed: () => context.pop(),
        ),
        title: Text(
          currentEpisode != null
              ? 'EPISODE #${currentEpisode.episodeNumber}'
              : 'Episode Details',
          style: AppTypography.eyebrow(
            color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
          ),
        ),
        actions: [
          IconButton(
            constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            icon: Icon(
              isBookmarked
                  ? Icons.bookmark_rounded
                  : Icons.bookmark_border_rounded,
              color: isBookmarked
                  ? (isDark ? AppColors.meriOrangeLight : AppColors.meriOrange)
                  : null,
            ),
            tooltip: isBookmarked ? 'Remove bookmark' : 'Bookmark episode',
            onPressed: () {
              ref.read(bookmarksProvider.notifier).toggleBookmark(episodeId);
            },
          ),
          if (currentEpisode?.youtubeUrl != null)
            IconButton(
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              icon: const Icon(Icons.play_circle_outline_rounded),
              tooltip: 'Watch on YouTube',
              onPressed: () {
                YouTubeUrlHelper.launchYouTubeVideo(
                  baseUrl: currentEpisode!.youtubeUrl,
                );
              },
            ),
        ],
      ),
      body: AsyncValueWidget<Episode?>(
        value: episodeAsync,
        loadingMessage: 'Loading episode record...',
        onRetry: () => ref.refresh(episodeByIdProvider(episodeId)),
        data: (episode) {
          if (episode == null) {
            return _buildNotFoundState(context, isDark);
          }
          return _buildContent(context, episode, isDark);
        },
      ),
    );
  }

  Widget _buildNotFoundState(BuildContext context, bool isDark) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                color: isDark
                    ? AppColors.darkSurfaceElevated
                    : AppColors.archiveSandLight,
                shape: BoxShape.circle,
                border: Border.all(
                  color: isDark
                      ? AppColors.darkBorder
                      : AppColors.archiveSandBorder,
                ),
              ),
              child: Icon(
                Icons.menu_book_outlined,
                size: 32,
                color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              'Episode Not Found',
              style: AppTypography.titleLarge(
                color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'The requested interview record ($episodeId) could not be located in the knowledge archive.',
              style: AppTypography.bodyMedium(
                color: isDark ? AppColors.darkTextSecondary : AppColors.stoneGray,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppSpacing.lg),
            OutlinedButton.icon(
              onPressed: () => context.pop(),
              icon: const Icon(Icons.arrow_back_rounded, size: 18),
              label: const Text('Return to Archive'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildContent(BuildContext context, Episode episode, bool isDark) {
    final dateFormat = DateFormat.yMMMMd();
    final publishedDateStr = dateFormat.format(episode.publishedAt);

    return ListView(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.md,
      ),
      children: [
        // =====================================================================
        // A. Episode Header
        // =====================================================================
        _buildEpisodeHeader(context, episode, publishedDateStr, isDark),
        const SizedBox(height: AppSpacing.md),
        const Divider(),
        const SizedBox(height: AppSpacing.sm),

        // =====================================================================
        // B. Guest Dossier
        // =====================================================================
        const MeriSectionHeader(
          title: 'Featured Entrepreneur',
          eyebrow: 'Guest Dossier',
          padding: EdgeInsets.zero,
        ),
        const SizedBox(height: AppSpacing.xs),
        _buildGuestCard(context, episode.guest, isDark),
        const SizedBox(height: AppSpacing.lg),

        // =====================================================================
        // C. Executive Briefing
        // =====================================================================
        const MeriSectionHeader(
          title: 'Executive Summary',
          eyebrow: 'Episode Overview',
          padding: EdgeInsets.zero,
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          episode.summary,
          style: AppTypography.bodyLarge(
            color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
          ),
        ),
        const SizedBox(height: AppSpacing.md),

        MeriSectionHeader(
          title: 'Strategic Insights',
          eyebrow: episode.insights.isEmpty
              ? 'No Documented Lessons'
              : '${episode.insights.length} Actionable Lessons',
          padding: EdgeInsets.zero,
        ),
        const SizedBox(height: AppSpacing.xs),
        if (episode.insights.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
            child: Text(
              'No strategic insights recorded for this interview.',
              style: AppTypography.bodyMedium(
                color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
              ),
            ),
          )
        else
          ...episode.insights.asMap().entries.map((entry) {
            return _buildInsightCard(context, entry.value, entry.key, isDark);
          }),
        const SizedBox(height: AppSpacing.lg),

        // =====================================================================
        // D. Original Amharic Quotations
        // =====================================================================
        MeriSectionHeader(
          title: 'Direct Quotations',
          eyebrow: episode.quotations.isEmpty
              ? 'No Recorded Quotes'
              : '${episode.quotations.length} Primary Source Quotes',
          padding: EdgeInsets.zero,
        ),
        const SizedBox(height: AppSpacing.xs),
        if (episode.quotations.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
            child: Text(
              'No direct quotations recorded for this interview.',
              style: AppTypography.bodyMedium(
                color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
              ),
            ),
          )
        else
          ...episode.quotations.map((quotation) {
            return _buildQuotationCard(
              context: context,
              quotation: quotation,
              youtubeUrl: episode.youtubeUrl,
              isDark: isDark,
            );
          }),
        const SizedBox(height: AppSpacing.lg),

        // =====================================================================
        // E. Original Interview (YouTube Recording)
        // =====================================================================
        if (episode.youtubeUrl != null) ...[
          const MeriSectionHeader(
            title: 'Original Interview',
            eyebrow: 'Primary Video Source',
            padding: EdgeInsets.zero,
          ),
          const SizedBox(height: AppSpacing.xs),
          _buildYouTubeHeroBanner(context, episode.youtubeUrl!, isDark),
          const SizedBox(height: AppSpacing.lg),
        ],

        // =====================================================================
        // F. Dataset / Publication Note
        // =====================================================================
        _buildDevelopmentDisclaimer(isDark),
        const SizedBox(height: AppSpacing.xxl),
      ],
    );
  }

  Widget _buildEpisodeHeader(
    BuildContext context,
    Episode episode,
    String publishedDateStr,
    bool isDark,
  ) {
    final primaryTextColor =
        isDark ? AppColors.darkTextPrimary : AppColors.inkBlack;
    final secondaryTextColor =
        isDark ? AppColors.darkTextSecondary : AppColors.stoneGray;
    final accentColor =
        isDark ? AppColors.meriOrangeLight : AppColors.meriOrange;

    final bylineParts = [
      if (episode.guest.name.trim().isNotEmpty) episode.guest.name.trim(),
      if (episode.guest.company.trim().isNotEmpty) episode.guest.company.trim(),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Subdued metadata: Episode number and duration (overflow-proof)
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Text(
                '${episode.podcastTitle.toUpperCase()} • #${episode.episodeNumber}',
                style: AppTypography.eyebrow(color: accentColor),
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Text(
              episode.formattedDuration,
              style: AppTypography.labelSmall(color: secondaryTextColor),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.xs),

        // Primary Headline
        Text(
          episode.title,
          style: AppTypography.displayMedium(color: primaryTextColor),
        ),

        // Guest Byline
        if (bylineParts.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.xs),
          Text(
            bylineParts.join(' • '),
            style: AppTypography.labelLarge(color: accentColor),
          ),
        ],
        const SizedBox(height: AppSpacing.xs),

        // Publication date
        Row(
          children: [
            Icon(
              Icons.calendar_today_outlined,
              size: 14,
              color: secondaryTextColor,
            ),
            const SizedBox(width: AppSpacing.xs),
            Expanded(
              child: Text(
                publishedDateStr,
                style: AppTypography.bodySmall(color: secondaryTextColor),
              ),
            ),
          ],
        ),

        // Topic labels
        if (episode.tags.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xxs,
            children: episode.tags.map((tag) {
              return EditorialBadge(
                label: tag,
                variant: EditorialBadgeVariant.sand,
              );
            }).toList(),
          ),
        ],
      ],
    );
  }

  Widget _buildYouTubeHeroBanner(
    BuildContext context,
    String youtubeUrl,
    bool isDark,
  ) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? AppColors.darkSurface : AppColors.paperLight,
        borderRadius: AppRadius.cardRadius,
        border: Border.all(
          color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
        ),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final isNarrow = constraints.maxWidth < 360;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Container(
                    width: 44,
                    height: 44,
                    decoration: const BoxDecoration(
                      color: AppColors.meriOrange,
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(
                      Icons.play_arrow_rounded,
                      color: Colors.white,
                      size: 28,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Verified YouTube Recording',
                          style: AppTypography.titleMedium(
                            color: isDark
                                ? AppColors.darkTextPrimary
                                : AppColors.inkBlack,
                          ),
                        ),
                        Text(
                          'Open original full-length video interview',
                          style: AppTypography.bodySmall(
                            color: isDark
                                ? AppColors.darkTextSecondary
                                : AppColors.stoneGray,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (!isNarrow) ...[
                    const SizedBox(width: AppSpacing.sm),
                    FilledButton.tonal(
                      onPressed: () {
                        YouTubeUrlHelper.launchYouTubeVideo(baseUrl: youtubeUrl);
                      },
                      style: FilledButton.styleFrom(
                        minimumSize: const Size(64, 48),
                        backgroundColor: isDark
                            ? AppColors.meriOrange.withValues(alpha: 0.25)
                            : AppColors.meriOrange.withValues(alpha: 0.15),
                        foregroundColor: isDark
                            ? AppColors.meriOrangeLight
                            : AppColors.meriOrange,
                      ),
                      child: const Text('Watch'),
                    ),
                  ],
                ],
              ),
              if (isNarrow) ...[
                const SizedBox(height: AppSpacing.sm),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.tonal(
                    onPressed: () {
                      YouTubeUrlHelper.launchYouTubeVideo(baseUrl: youtubeUrl);
                    },
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(double.infinity, 48),
                      backgroundColor: isDark
                          ? AppColors.meriOrange.withValues(alpha: 0.25)
                          : AppColors.meriOrange.withValues(alpha: 0.15),
                      foregroundColor: isDark
                          ? AppColors.meriOrangeLight
                          : AppColors.meriOrange,
                    ),
                    child: const Text('Watch'),
                  ),
                ),
              ],
            ],
          );
        },
      ),
    );
  }

  Widget _buildGuestCard(BuildContext context, Guest guest, bool isDark) {
    final initials = guest.name.trim().isNotEmpty
        ? guest.name
            .trim()
            .split(RegExp(r'\s+'))
            .map((e) => e.isNotEmpty ? e[0] : '')
            .take(2)
            .join()
            .toUpperCase()
        : 'G';

    final bylineParts = [
      if (guest.title.trim().isNotEmpty) guest.title.trim(),
      if (guest.company.trim().isNotEmpty) guest.company.trim(),
    ];

    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? AppColors.darkSurface : AppColors.paperLight,
        borderRadius: AppRadius.cardRadius,
        border: Border.all(
          color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Container(
                width: 52,
                height: 52,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: isDark
                      ? AppColors.meriOrange.withValues(alpha: 0.2)
                      : AppColors.archiveSandLight,
                  border: Border.all(
                    color: isDark
                        ? AppColors.darkBorder
                        : AppColors.archiveSandBorder,
                  ),
                ),
                clipBehavior: Clip.antiAlias,
                child: (guest.avatarUrl != null &&
                        guest.avatarUrl!.trim().isNotEmpty)
                    ? Image.network(
                        guest.avatarUrl!,
                        fit: BoxFit.cover,
                        errorBuilder: (context, error, stackTrace) => Center(
                          child: Text(
                            initials,
                            style: AppTypography.titleMedium(
                              color: isDark
                                  ? AppColors.meriOrangeLight
                                  : AppColors.meriOrange,
                            ),
                          ),
                        ),
                      )
                    : Center(
                        child: Text(
                          initials,
                          style: AppTypography.titleMedium(
                            color: isDark
                                ? AppColors.meriOrangeLight
                                : AppColors.meriOrange,
                          ),
                        ),
                      ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      guest.name,
                      style: AppTypography.titleMedium(
                        color: isDark
                            ? AppColors.darkTextPrimary
                            : AppColors.inkBlack,
                      ),
                    ),
                    if (bylineParts.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.xxs),
                      Text(
                        bylineParts.join(' • '),
                        style: AppTypography.bodySmall(
                          color: isDark
                              ? AppColors.darkTextSecondary
                              : AppColors.stoneGray,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          if (guest.industry != null && guest.industry!.trim().isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            EditorialBadge(
              label: guest.industry!,
              variant: EditorialBadgeVariant.orange,
            ),
          ],
          if (guest.bio.trim().isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(
              guest.bio,
              style: AppTypography.bodyMedium(
                color: isDark
                    ? AppColors.darkTextSecondary
                    : AppColors.inkCharcoal,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildInsightCard(
    BuildContext context,
    Insight insight,
    int index,
    bool isDark,
  ) {
    final ordinal = 'INSIGHT ${(index + 1).toString().padLeft(2, '0')}';

    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? AppColors.darkSurface : AppColors.paperLight,
        borderRadius: AppRadius.cardRadius,
        border: Border.all(
          color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xxs,
            children: [
              Text(
                ordinal,
                style: AppTypography.eyebrow(
                  color: isDark
                      ? AppColors.meriOrangeLight
                      : AppColors.meriOrange,
                ).copyWith(fontSize: 10),
              ),
              if (insight.category.trim().isNotEmpty)
                EditorialBadge(
                  label: insight.category,
                  variant: EditorialBadgeVariant.sand,
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            insight.title,
            style: AppTypography.titleMedium(
              color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            insight.summary,
            style: AppTypography.bodyMedium(
              color: isDark
                  ? AppColors.darkTextSecondary
                  : AppColors.inkCharcoal,
            ),
          ),
          if (insight.takeaways.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Key Takeaways',
              style: AppTypography.eyebrow(
                color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
              ).copyWith(fontSize: 10),
            ),
            const SizedBox(height: AppSpacing.xxs),
            ...insight.takeaways.map((takeaway) {
              return Padding(
                padding: const EdgeInsets.only(
                  bottom: AppSpacing.xs,
                  left: AppSpacing.xs,
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(top: 6, right: AppSpacing.xs),
                      child: Container(
                        width: 5,
                        height: 5,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: isDark
                              ? AppColors.meriOrangeLight
                              : AppColors.meriOrange,
                        ),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        takeaway,
                        style: AppTypography.bodySmall(
                          color: isDark
                              ? AppColors.darkTextSecondary
                              : AppColors.stoneGray,
                        ),
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
          if (insight.practicalAction != null &&
              insight.practicalAction!.trim().isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xs),
            Container(
              clipBehavior: Clip.antiAlias,
              decoration: BoxDecoration(
                color: isDark
                    ? AppColors.darkSurfaceElevated
                    : AppColors.archiveSandLight.withValues(alpha: 0.5),
                borderRadius: AppRadius.roundedSm,
                border: Border.all(
                  color: isDark
                      ? AppColors.darkBorder
                      : AppColors.archiveSandBorder,
                ),
              ),
              child: IntrinsicHeight(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Container(
                      width: 3,
                      color: isDark
                          ? AppColors.meriOrangeLight
                          : AppColors.meriOrange,
                    ),
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.all(AppSpacing.sm),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Icon(
                                  Icons.lightbulb_outline_rounded,
                                  size: 14,
                                  color: isDark
                                      ? AppColors.meriOrangeLight
                                      : AppColors.meriOrange,
                                ),
                                const SizedBox(width: AppSpacing.xs),
                                Text(
                                  'PRACTICAL ACTION',
                                  style: AppTypography.eyebrow(
                                    color: isDark
                                        ? AppColors.meriOrangeLight
                                        : AppColors.meriOrange,
                                  ).copyWith(fontSize: 10),
                                ),
                              ],
                            ),
                            const SizedBox(height: AppSpacing.xxs),
                            Text(
                              insight.practicalAction!,
                              style: AppTypography.bodySmall(
                                color: isDark
                                    ? AppColors.darkTextPrimary
                                    : AppColors.inkBlack,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildQuotationCard({
    required BuildContext context,
    required Quotation quotation,
    required String? youtubeUrl,
    required bool isDark,
  }) {
    final hasVerifiedSource = youtubeUrl != null &&
        youtubeUrl.trim().isNotEmpty &&
        quotation.timestampSeconds >= 0 &&
        YouTubeUrlHelper.isValidYouTubeUrl(youtubeUrl);

    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: isDark ? AppColors.darkSurface : AppColors.paperLight,
        borderRadius: AppRadius.cardRadius,
        border: Border.all(
          color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
        ),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              width: 3.5,
              color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Original Amharic text in upright Ethiopic typography
                    Text(
                      '“${quotation.amharicQuote}”',
                      style: AppTypography.amharicQuotation(
                        color: isDark ? AppColors.darkTextPrimary : AppColors.inkBlack,
                      ),
                    ),

                    // English translation only when supplied
                    if (quotation.englishTranslation.trim().isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        quotation.englishTranslation,
                        style: AppTypography.bodySmall(
                          color: isDark
                              ? AppColors.darkTextSecondary
                              : AppColors.stoneGray,
                        ),
                      ),
                    ],

                    // Context if available
                    if (quotation.context.trim().isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        quotation.context,
                        style: AppTypography.bodySmall(
                          color: isDark ? AppColors.darkTextMuted : AppColors.stoneGrayLight,
                        ).copyWith(fontStyle: FontStyle.italic),
                      ),
                    ],

                    const SizedBox(height: AppSpacing.sm),
                    const Divider(),
                    const SizedBox(height: AppSpacing.xs),

                    // Footer: Speaker & Actionable or Static Timestamp
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Expanded(
                          child: Text(
                            quotation.speaker,
                            style: AppTypography.labelLarge(
                              color: isDark
                                  ? AppColors.darkTextPrimary
                                  : AppColors.inkBlack,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (hasVerifiedSource)
                          InkWell(
                            onTap: () {
                              YouTubeUrlHelper.launchYouTubeTimestamp(
                                baseUrl: youtubeUrl,
                                timestampSeconds: quotation.timestampSeconds,
                              );
                            },
                            borderRadius: AppRadius.roundedSm,
                            child: ConstrainedBox(
                              constraints: const BoxConstraints(
                                minWidth: 48,
                                minHeight: 48,
                              ),
                              child: Container(
                                alignment: Alignment.center,
                                padding: const EdgeInsets.symmetric(
                                  horizontal: AppSpacing.sm,
                                  vertical: AppSpacing.xs,
                                ),
                                decoration: BoxDecoration(
                                  color: isDark
                                      ? AppColors.meriOrange.withValues(alpha: 0.18)
                                      : AppColors.meriOrange.withValues(alpha: 0.10),
                                  borderRadius: AppRadius.roundedSm,
                                  border: Border.all(
                                    color: isDark
                                        ? AppColors.meriOrangeLight.withValues(alpha: 0.5)
                                        : AppColors.meriOrange.withValues(alpha: 0.4),
                                  ),
                                ),
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(
                                      Icons.play_arrow_rounded,
                                      size: 16,
                                      color: isDark
                                          ? AppColors.meriOrangeLight
                                          : AppColors.meriOrange,
                                    ),
                                    const SizedBox(width: AppSpacing.xxs),
                                    Text(
                                      '${quotation.formattedTimestamp} • Watch',
                                      style: AppTypography.labelSmall(
                                        color: isDark
                                            ? AppColors.meriOrangeLight
                                            : AppColors.meriOrange,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          )
                        else
                          // Static non-interactive timestamp badge
                          ConstrainedBox(
                            constraints: const BoxConstraints(
                              minHeight: 36,
                            ),
                            child: Container(
                              alignment: Alignment.center,
                              padding: const EdgeInsets.symmetric(
                                horizontal: AppSpacing.sm,
                                vertical: AppSpacing.xs,
                              ),
                              decoration: BoxDecoration(
                                color: isDark
                                    ? AppColors.darkSurfaceElevated
                                    : AppColors.archiveSandLight,
                                borderRadius: AppRadius.roundedSm,
                                border: Border.all(
                                  color: isDark
                                      ? AppColors.darkBorder
                                      : AppColors.archiveSandBorder,
                                ),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(
                                    Icons.schedule_rounded,
                                    size: 14,
                                    color: isDark
                                        ? AppColors.darkTextMuted
                                        : AppColors.stoneGray,
                                  ),
                                  const SizedBox(width: AppSpacing.xxs),
                                  Text(
                                    quotation.formattedTimestamp,
                                    style: AppTypography.labelSmall(
                                      color: isDark
                                          ? AppColors.darkTextMuted
                                          : AppColors.stoneGray,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDevelopmentDisclaimer(bool isDark) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark
            ? AppColors.darkSurfaceElevated
            : AppColors.archiveSandLight,
        borderRadius: AppRadius.cardRadius,
        border: Border.all(
          color: isDark ? AppColors.darkBorder : AppColors.archiveSandBorder,
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            Icons.info_outline_rounded,
            size: 18,
            color: isDark ? AppColors.meriOrangeLight : AppColors.meriOrange,
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              'EDITORIAL ARCHIVE EDITION: Curated business knowledge briefing based on a linked source interview. Select quotations link directly to timestamps in the original interview recording.',
              style: AppTypography.labelSmall(
                color: isDark ? AppColors.darkTextMuted : AppColors.stoneGray,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
