import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:astr_auto_anima_hub_client/core/courtyard_theme.dart';
import 'package:astr_auto_anima_hub_client/core/hub_api.dart';
import 'package:astr_auto_anima_hub_client/core/models.dart';
import 'package:astr_auto_anima_hub_client/features/lite/lite_job_history_page.dart';

class FavoriteStateApi extends HubApi {
  FavoriteStateApi() : super(baseUrl: 'http://test.invalid', token: 'test');
  String? lastFavorite;
  @override
  Future<Map<String, dynamic>> getImagePrompt(
          String jobId, String imageId) async =>
      {
        'available': true,
        'stage': '当次实际正向提示词',
        'positive': 'edited character, rain, watercolor',
        'negative': 'bad hands',
      };
  @override
  Future<RemoteJobPageResult> getRemoteJobs(
          {String kind = '',
          String status = '',
          int page = 1,
          int pageSize = 30}) async =>
      RemoteJobPageResult.fromJson({
        'page': 1,
        'pages': 1,
        'total': 1,
        'items': [
          {
            'id': 'job',
            'status': 'succeeded',
            'prompt_ids': ['pool-same'],
            'liked_prompt_ids': ['pool-same'],
            'liked_image_ids': ['image-a'],
            'images': [
              {
                'id': 'image-a',
                'prompt_id': 'pool-same',
                'user_addition': 'rain',
                'download_url': '/api/v1/lite/jobs/job/images/image-a'
              },
              {
                'id': 'image-b',
                'prompt_id': 'pool-same',
                'user_addition': 'snow',
                'download_url': '/api/v1/lite/jobs/job/images/image-b'
              },
            ]
          }
        ]
      });
  @override
  Future<PromptLikeResult> favoriteJobImage(
      {required String jobId, required String imageId}) async {
    lastFavorite = imageId;
    return const PromptLikeResult(
        action: 'liked', promptId: 'pool-same', savedPromptId: 'fav-new');
  }
}

void main() {
  testWidgets(
      'same source with different additions has separate image favorite state',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = FavoriteStateApi();
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: LiteJobHistoryPage(api: api))));
    await tester.pumpAndSettle();
    final selected = find.byWidgetPredicate(
        (widget) => widget is CourtyardIcon && widget.icon == Icons.thumb_up);
    expect(selected, findsOneWidget);
    await tester.tap(find.byTooltip('收藏本张完整提示词；取消请到个人收藏'));
    await tester.pumpAndSettle();
    expect(api.lastFavorite, 'image-b');
    expect(selected, findsNWidgets(2));
    await tester.tap(find.byTooltip('查看本张提示词').first);
    await tester.pumpAndSettle();
    expect(find.textContaining('edited character, rain, watercolor'),
        findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
