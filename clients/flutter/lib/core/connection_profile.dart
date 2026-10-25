import 'session_store.dart';

/// A bookmark, not a remote/cloud instance. Credentials never enter JSON prefs.
class ConnectionProfile {
  const ConnectionProfile(
      {required this.id,
      required this.label,
      required this.baseUrl,
      required this.mode,
      required this.deployment});
  final String id;
  final String label;
  final String baseUrl;
  final HubAccessMode mode;
  final HubDeploymentMode deployment;

  Map<String, dynamic> toJson() => {
        'id': id,
        'label': label,
        'base_url': baseUrl,
        'mode': mode.name,
        'deployment': deployment.name
      };

  factory ConnectionProfile.fromJson(Map<String, dynamic> value) {
    final id = value['id'] as String;
    if (!RegExp(r'^[a-zA-Z0-9_-]{1,80}$').hasMatch(id)) {
      throw const FormatException('Invalid connection id');
    }
    return ConnectionProfile(
        id: id,
        label: value['label'] as String,
        baseUrl: value['base_url'] as String,
        mode: HubAccessMode.values.byName(value['mode'] as String),
        deployment:
            HubDeploymentMode.values.byName(value['deployment'] as String));
  }
}

String validateProfileEndpoint(String raw, HubDeploymentMode deployment) {
  final uri = Uri.tryParse(raw.trim());
  if (uri == null ||
      !{'http', 'https'}.contains(uri.scheme) ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment) {
    throw const FormatException('请填写 HTTP/HTTPS Hub 地址，不要包含令牌、查询参数或账号密码。');
  }
  if (deployment == HubDeploymentMode.local &&
      !{'localhost', '127.0.0.1', '::1'}.contains(uri.host)) {
    throw const FormatException('本机模式只接受此电脑的 localhost / 127.0.0.1 / ::1。');
  }
  return uri.toString().replaceAll(RegExp(r'/+$'), '');
}
