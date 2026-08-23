import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:public_file_saver/public_file_saver.dart';
import 'package:saf/saf.dart';
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
  static const _directoryKey = 'job_download_directory';
  static const _directoryUriKey = 'job_download_directory_uri';
  static const androidPublicDirectory = 'Downloads/AstrAutoAnima';
  final PublicFileSaver _publicFileSaver = PublicFileSaver();
  final Saf _saf = Saf();

  bool get usesPublicDownloads => Platform.isAndroid;

  Future<JobDownloadSettings> loadSettings() async {
    final preferences = await SharedPreferences.getInstance();
    final storedDirectory = preferences.getString(_directoryKey) ?? '';
    final directoryUri = preferences.getString(_directoryUriKey) ?? '';
    return JobDownloadSettings(
      autoDownload: preferences.getBool(_enabledKey) ?? false,
      directory: usesPublicDownloads && directoryUri.isEmpty
          ? androidPublicDirectory
          : storedDirectory,
      directoryUri: usesPublicDownloads ? directoryUri : '',
    );
  }

  Future<void> saveSettings(JobDownloadSettings settings) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.setBool(_enabledKey, settings.autoDownload);
    await preferences.setString(
      _directoryKey,
      settings.directory,
    );
    await preferences.setString(_directoryUriKey, settings.directoryUri);
  }

  Future<JobDownloadSettings?> chooseAndroidDirectory({
    required bool autoDownload,
    String initialUri = '',
  }) async {
    if (!usesPublicDownloads) return null;
    final selected = await _saf.pickDirectory(
      initialUri: initialUri.trim().isEmpty ? null : initialUri.trim(),
    );
    if (selected == null) return null;
    final name = selected.name.trim();
    final settings = JobDownloadSettings(
      autoDownload: autoDownload,
      directory: name.isEmpty ? selected.uri : name,
      directoryUri: selected.uri,
    );
    await saveSettings(settings);
    return settings;
  }

  Future<JobDownloadSettings> resetAndroidDirectory({
    required bool autoDownload,
  }) async {
    final settings = JobDownloadSettings(
      autoDownload: autoDownload,
      directory: androidPublicDirectory,
    );
    await saveSettings(settings);
    return settings;
  }

  Future<String> defaultDirectory() async {
    if (usesPublicDownloads) return androidPublicDirectory;
    Directory? root = await getDownloadsDirectory();
    root ??= await getApplicationDocumentsDirectory();
    return _join(root.path, 'AstrAutoAnima');
  }

  Future<String> saveImage({
    required HubApi api,
    required String jobId,
    required RemoteJobImage image,
    required String directory,
  }) async {
    final bytes = await api.downloadJobImage(image);
    final jobPrefix = jobId.length <= 8 ? jobId : jobId.substring(0, 8);
    final filename = _safeFilename('${jobPrefix}_${image.filename}');
    if (usesPublicDownloads) {
      final settings = await loadSettings();
      if (settings.directoryUri.trim().isNotEmpty) {
        final saved = await _saf.writeFileBytes(
          settings.directoryUri,
          filename,
          image.contentType,
          bytes,
        );
        return saved.uri;
      }
      final saved = await _publicFileSaver.saveBytes(
        bytes: bytes,
        fileName: filename,
        mimeType: image.contentType,
        subDir: 'AstrAutoAnima',
      );
      if (saved == null || !saved.isSuccess) {
        throw StateError('Android 公共下载目录写入失败');
      }
      return saved.path ?? saved.uri ?? androidPublicDirectory;
    }
    final targetDirectory = Directory(
      directory.trim().isEmpty ? await defaultDirectory() : directory.trim(),
    );
    await targetDirectory.create(recursive: true);
    final path = await _unusedPath(targetDirectory, filename);
    await File(path).writeAsBytes(bytes, flush: true);
    return path;
  }

  Future<List<String>> saveAll({
    required HubApi api,
    required RemoteJobResult job,
    required String directory,
  }) async {
    final paths = <String>[];
    for (final image in job.images) {
      paths.add(
        await saveImage(
          api: api,
          jobId: job.id,
          image: image,
          directory: directory,
        ),
      );
    }
    return paths;
  }

  String _join(String left, String right) {
    final separator = Platform.pathSeparator;
    return '${left.replaceAll(RegExp(r'[\\/]+$'), '')}$separator$right';
  }

  String _safeFilename(String value) {
    final cleaned = value.replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1F]'), '_');
    return cleaned.trim().isEmpty ? 'generated-image.png' : cleaned.trim();
  }

  Future<String> _unusedPath(Directory directory, String filename) async {
    final separator = Platform.pathSeparator;
    final dot = filename.lastIndexOf('.');
    final stem = dot > 0 ? filename.substring(0, dot) : filename;
    final extension = dot > 0 ? filename.substring(dot) : '';
    var candidate = '${directory.path}$separator$filename';
    var index = 2;
    while (await File(candidate).exists()) {
      candidate = '${directory.path}$separator$stem ($index)$extension';
      index += 1;
    }
    return candidate;
  }
}
