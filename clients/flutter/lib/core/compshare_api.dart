import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

class CompShareConfig {
  const CompShareConfig({
    this.publicKey = '',
    this.privateKey = '',
    this.region = '',
    this.zone = '',
    this.uhostId = '',
  });

  final String publicKey;
  final String privateKey;
  final String region;
  final String zone;
  final String uhostId;

  bool get isConfigured =>
      publicKey.isNotEmpty &&
      privateKey.isNotEmpty &&
      region.isNotEmpty &&
      zone.isNotEmpty &&
      uhostId.isNotEmpty;
}

class CompShareConfigStore {
  static const _publicKey = 'compshare_public_key';
  static const _privateKey = 'compshare_private_key';
  static const _region = 'compshare_region';
  static const _zone = 'compshare_zone';
  static const _uhostId = 'compshare_uhost_id';
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  Future<CompShareConfig> load() async {
    final values = await _storage.readAll();
    return CompShareConfig(
      publicKey: values[_publicKey] ?? '',
      privateKey: values[_privateKey] ?? '',
      region: values[_region] ?? '',
      zone: values[_zone] ?? '',
      uhostId: values[_uhostId] ?? '',
    );
  }

  Future<void> save(CompShareConfig config) async {
    await Future.wait([
      _storage.write(key: _publicKey, value: config.publicKey),
      _storage.write(key: _privateKey, value: config.privateKey),
      _storage.write(key: _region, value: config.region),
      _storage.write(key: _zone, value: config.zone),
      _storage.write(key: _uhostId, value: config.uhostId),
    ]);
  }
}

class CompShareInstance {
  const CompShareInstance({
    required this.id,
    required this.name,
    required this.state,
    required this.region,
    required this.zone,
    required this.gpuType,
    required this.gpuCount,
    required this.pricePerHour,
    required this.supportWithoutGpuStart,
  });

  factory CompShareInstance.fromJson(Map<String, dynamic> json) {
    return CompShareInstance(
      id: json['UHostId']?.toString() ?? '',
      name: json['Name']?.toString() ?? '',
      state: json['State']?.toString() ?? 'Unknown',
      region: json['Region']?.toString() ?? '',
      zone: json['Zone']?.toString() ?? '',
      gpuType: json['GpuType']?.toString() ?? '',
      gpuCount: (json['GPU'] as num?)?.toInt() ?? 0,
      pricePerHour: (json['InstancePrice'] as num?)?.toDouble() ?? 0,
      supportWithoutGpuStart: json['SupportWithoutGpuStart'] as bool? ?? false,
    );
  }

  final String id;
  final String name;
  final String state;
  final String region;
  final String zone;
  final String gpuType;
  final int gpuCount;
  final double pricePerHour;
  final bool supportWithoutGpuStart;

  bool get isRunning => state == 'Running';
  bool get isStopped => state == 'Stopped';
  bool get isTransitioning => const {
        'Starting',
        'Stopping',
        'Rebooting',
        'Install',
      }.contains(state);
}

class CompShareApiException implements Exception {
  const CompShareApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

class CompShareApi {
  CompShareApi({
    required this.config,
    http.Client? client,
  }) : _client = client ?? http.Client();

  static final endpoint = Uri.parse('https://api.compshare.cn');
  final CompShareConfig config;
  final http.Client _client;

  static String signature(
    Map<String, String> parameters,
    String privateKey,
  ) {
    final keys = parameters.keys.toList()..sort();
    final source = StringBuffer();
    for (final key in keys) {
      source
        ..write(key)
        ..write(parameters[key]);
    }
    source.write(privateKey);
    return sha1.convert(utf8.encode(source.toString())).toString();
  }

  Future<Map<String, dynamic>> _invoke(
    String action, [
    Map<String, String> values = const {},
    bool accountOnly = false,
  ]) async {
    if (accountOnly
        ? config.publicKey.isEmpty || config.privateKey.isEmpty
        : !config.isConfigured) {
      throw const CompShareApiException('请先保存完整的优云智算 API 配置。');
    }
    final body = <String, String>{
      'Action': action,
      'PublicKey': config.publicKey,
      if (!accountOnly) 'Region': config.region,
      if (!accountOnly) 'Zone': config.zone,
      ...values,
    };
    body['Signature'] = signature(body, config.privateKey);
    http.Response response;
    try {
      response = await _client
          .post(endpoint, body: body)
          .timeout(const Duration(seconds: 25));
    } on Exception catch (error) {
      throw CompShareApiException('无法连接优云智算控制面：$error');
    }
    Map<String, dynamic> payload;
    try {
      payload = Map<String, dynamic>.from(jsonDecode(response.body) as Map);
    } on Exception {
      throw CompShareApiException(
        '优云智算返回了无法识别的响应（HTTP ${response.statusCode}）。',
      );
    }
    final retCode = (payload['RetCode'] as num?)?.toInt() ?? -1;
    if (response.statusCode >= 400 || retCode != 0) {
      throw CompShareApiException(
        payload['Message']?.toString() ??
            payload['Error']?.toString() ??
            '优云智算请求失败（RetCode=$retCode）。',
      );
    }
    return payload;
  }

  Future<CompShareInstance> describe() async {
    final payload = await _invoke('DescribeCompShareInstance', {
      'Limit': '100',
      'Offset': '0',
    });
    final raw = (payload['UHostSet'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .where((item) => item['UHostId']?.toString() == config.uhostId)
        .firstOrNull;
    if (raw == null) {
      throw CompShareApiException('没有找到实例 ${config.uhostId}。');
    }
    return CompShareInstance.fromJson(raw);
  }

  /// Account-level read only. No instance ID, region, or power action is sent.
  Future<Map<String, String>> balance() async {
    final payload = await _invoke('GetBalance', const {}, true);
    final info = payload['AccountInfo'];
    if (info is! Map) {
      throw const CompShareApiException('余额响应格式无法识别。');
    }
    final result = <String, String>{};
    for (final key in [
      'AmountAvailable',
      'Amount',
      'AmountFree',
      'AmountFreeze',
      'AmountCredit'
    ]) {
      final raw = info[key];
      final number = raw == null ? null : num.tryParse(raw.toString());
      if (number != null && number.isFinite) result[key] = raw.toString();
    }
    if (result.isEmpty) throw const CompShareApiException('接口未提供可识别的余额。');
    return result;
  }

  Future<void> start({String withoutGpuSpec = ''}) async {
    await _invoke('StartCompShareInstance', {
      'UHostId': config.uhostId,
      if (withoutGpuSpec.isNotEmpty) 'WithoutGpuSpec': withoutGpuSpec,
    });
  }

  Future<void> stop() async {
    await _invoke('StopCompShareInstance', {'UHostId': config.uhostId});
  }

  Future<void> reboot() async {
    await _invoke('RebootCompShareInstance', {'UHostId': config.uhostId});
  }
}
