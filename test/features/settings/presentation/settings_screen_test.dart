import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:meri/features/settings/presentation/screens/settings_screen.dart';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  Widget buildSettingsTestWidget({
    String? navigatedRoute,
    void Function(String route)? onNavigate,
  }) {
    final router = GoRouter(
      initialLocation: '/settings',
      routes: [
        GoRoute(
          path: '/settings',
          builder: (context, state) => const SettingsScreen(),
        ),
        GoRoute(
          path: '/explore',
          builder: (context, state) {
            onNavigate?.call('/explore');
            return const Scaffold(body: Text('Explore Destination'));
          },
        ),
      ],
    );

    return MaterialApp.router(
      routerConfig: router,
    );
  }

  group('SettingsScreen Presentation Tests', () {
    testWidgets('renders colophon, architecture sections, and attribution', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(buildSettingsTestWidget());
      await tester.pumpAndSettle();

      // 1. Header
      expect(find.text('Settings & About'), findsOneWidget);

      // 2. Colophon
      expect(find.text('About Meri'), findsOneWidget);
      expect(find.text('PUBLICATION COLOPHON'), findsOneWidget);
      expect(find.text('The business behind the story.'), findsOneWidget);
      expect(find.text('VERSION 1.0.0'), findsOneWidget);
      expect(find.text('EDITORIAL EDITION'), findsOneWidget);
      expect(find.textContaining('business-knowledge companion'), findsOneWidget);
      expect(find.textContaining('Playfair Display'), findsOneWidget);

      // 3. System & Architecture
      expect(find.text('System & Archive'), findsOneWidget);
      expect(find.text('KNOWLEDGE ARCHITECTURE'), findsOneWidget);
      expect(find.text('Knowledge Archive'), findsOneWidget);
      expect(find.text('Bundled Local Dataset (Episode #199)'), findsOneWidget);
      expect(find.text('Interview Media'), findsOneWidget);
      expect(find.text('YouTube Video & Audio'), findsOneWidget);
      expect(find.text('Personal Notebook'), findsOneWidget);
      expect(find.text('On-Device Storage (SharedPreferences)'), findsOneWidget);

      // 4. Reading Environment
      expect(find.text('Reading Environment'), findsOneWidget);
      expect(find.text('Visual Palette'), findsOneWidget);

      // 5. Attribution
      expect(find.text('Attribution'), findsOneWidget);
      expect(find.text('Meri Podcast • Addis Ababa, Ethiopia'), findsOneWidget);
    });

    testWidgets('omits misleading inert playback rate, cloud sync, and decorative switches', (tester) async {
      await tester.pumpWidget(buildSettingsTestWidget());
      await tester.pumpAndSettle();

      // No fake playback rate
      expect(find.text('Default Playback Rate'), findsNothing);
      expect(find.text('1.0x Normal Speed'), findsNothing);

      // No unverified cloud sync claims
      expect(find.text('Cloud Synchronization'), findsNothing);
      expect(find.textContaining('Supabase Repository'), findsNothing);

      // No decorative switches
      expect(find.byType(Switch), findsNothing);
    });

    testWidgets('explore action maintains >= 48x48 hit target and navigates correctly', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      String? routedTo;

      await tester.pumpWidget(buildSettingsTestWidget(
        onNavigate: (route) => routedTo = route,
      ));
      await tester.pumpAndSettle();

      final exploreButtonFinder = find.widgetWithText(OutlinedButton, 'Explore Knowledge Archive');
      expect(exploreButtonFinder, findsOneWidget);

      // Verify hit target >= 48x48
      final buttonSize = tester.getSize(exploreButtonFinder);
      expect(buttonSize.width, greaterThanOrEqualTo(48.0));
      expect(buttonSize.height, greaterThanOrEqualTo(48.0));

      // Tap action
      await tester.tap(exploreButtonFinder);
      await tester.pumpAndSettle();

      expect(routedTo, equals('/explore'));
      expect(find.text('Explore Destination'), findsOneWidget);
    });

    testWidgets('remains usable and overflow-free under 1.5x accessibility text scale on narrow viewport', (tester) async {
      tester.view.physicalSize = const Size(360, 1200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      final router = GoRouter(
        initialLocation: '/settings',
        routes: [
          GoRoute(
            path: '/settings',
            builder: (context, state) => MediaQuery(
              data: MediaQuery.of(context).copyWith(
                textScaler: const TextScaler.linear(1.5),
              ),
              child: const SettingsScreen(),
            ),
          ),
        ],
      );

      await tester.pumpWidget(
        MaterialApp.router(
          routerConfig: router,
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Settings & About'), findsOneWidget);
      expect(find.text('About Meri'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
