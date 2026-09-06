import 'package:public_file_saver/public_file_saver.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'hub_api.dart';
import 'models.dart';

class JobDownloadSettings {
  const JobDownloadSettings({
    required this.autoDownload,
    required this.directory,
    this.directoryUri = '',
  });

  final bool autoDownload;
  final String directory;
  final String directoryUri;
}

class JobImageStore {
  static const _enabledKey = 'job_auto_download_enabled';
  static const browserDownloadDirectory = '浏览器下载';
  final PublicFileSaver _publicFileSaver = PublicFileSaver();

  bool get usesPublicDownloads => false;
  bool get usesBrowserDownloads => true;
  bool get supportsDirectorySelection => false;

  Future<JobDownloadSettings> loadSettings() async {
    final preferences = await SharedPreferences.getInstance();
    return JobDownloadSettings(
      autoDownload: preferences.getBool(_enabledKey) ?? false,
      directory: browserDownloadDirectory,
    );
  }

  Future<void> saveSettings(JobDownloadSettings settings) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.setBool(_enabledKey, settings.autoDownload);
  }

  Future<JobDownloadSettings?> chooseAndroidDirectory({
    required bool autoDownload,
    String initialUri = '',
  }) async =>
      null;

  Future<JobDownloadSettings> resetAndroidDirectory({
    required bool autoDownload,
  }) async {
    final settings = JobDownloadSettings(
      autoDownload: autoDownload,
      directory: browserDownloadDirectory,
    );
    await saveSettings(settings);
    return settings;
  }

  Future<String> defaultDirectory() async => browserDownloadDirectory;

  Future<String> saveImage({
    required HubApi api,
    required String jobId,
    required RemoteJobImage image,
    required String directory,
  }) async {
    final bytes = await api.downloadJobImage(image);
    final jobPrefix = jobId.length <= 8 ? jobId : jobId.substring(0, 8);
    final filename = _safeFilename('${jobPrefix}_${image.filename}');
    final saved = await _publicFileSaver.saveBytes(
      bytes: bytes,
      fileName: filename,
      mimeType: image.contentType,
    );
    if (saved == null) {
      throw StateError('浏览器没有接受图片下载');
    }
    return filename;
  }

  Future<List<String>> saveAll({
    required HubApi api,
    required RemoteJobResult job,
    required String directory,
  }) async {
    final filenames = <String>[];
    for (final image in job.images) {
      filenames.add(
        await saveImage(
          api: api,
          jobId: job.id,
          image: image,
          directory: directory,
        ),
      );
    }
    return filenames;
  }

  String _safeFilename(String value) {
    final cleaned = value.replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1F]'), '_');
    return cleaned.trim().isEmpty ? 'generated-image.png' : cleaned.trim();
  }
}
