import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';
import '../../core/hub_api.dart';

class NapcatLoginDialog extends StatefulWidget {
  const NapcatLoginDialog({required this.api, super.key});
  final HubApi api;
  @override
  State<NapcatLoginDialog> createState() => _NapcatLoginDialogState();
}

class _NapcatLoginDialogState extends State<NapcatLoginDialog> {
  final _code = TextEditingController();
  List<String> _accounts = [];
  String? _uin;
  String _status = 'Token 自动从服务端读取，不会显示或传给客户端。';
  bool _busy = false;
  bool _logged = false;
  String _qr = '';
  @override
  void initState() {
    super.initState();
    _request(false);
  }

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _request(bool login, {bool refreshQr = false}) async {
    if (login) {
      final yes = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
                  title: Text('登录QQ $_uin？'),
                  content: const Text('仅使用已有快捷登录凭据；验证码或设备验证仍需本人完成。'),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(context, false),
                        child: const Text('取消')),
                    FilledButton(
                        onPressed: () => Navigator.pop(context, true),
                        child: const Text('登录'))
                  ]));
      if (yes != true) return;
    }
    setState(() => _busy = true);
    try {
      final result = login
          ? await widget.api.napcatLogin(_uin!, _code.text.trim())
          : refreshQr
              ? await widget.api.napcatQr(_code.text.trim())
              : await widget.api.napcatAccounts(_code.text.trim());
      if (mounted) {
        setState(() {
          if (result['accounts'] is List) {
            _accounts = (result['accounts'] as List).map((e) => '$e').toList();
            if (!_accounts.contains(_uin)) {
              _uin = _accounts.length == 1 ? _accounts.first : null;
            }
          }
          _logged = result['is_login'] == true;
          _qr = result['qr_code']?.toString() ?? '';
          _status = result['message']?.toString() ??
              (_logged ? 'QQ 已登录' : 'QQ 未登录，请选择已有QQ账号。');
        });
      }
    } catch (error) {
      if (mounted) setState(() => _status = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
          title: const Text('NapCat 登录助手'),
          content: SizedBox(
              width: 460,
              child: SingleChildScrollView(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                Text(_status),
                if (_qr.isNotEmpty && !_logged) ...[
                  QrImageView(
                      data: _qr, size: 210, backgroundColor: Colors.white),
                  const Text('用手机 QQ 扫码并确认，随后点击刷新状态。勿分享此登录二维码。'),
                ],
                TextField(
                    controller: _code,
                    obscureText: true,
                    decoration:
                        const InputDecoration(labelText: '2FA动态码（未开启则留空）')),
                DropdownButtonFormField<String>(
                    key: ValueKey(_uin),
                    initialValue: _uin,
                    items: _accounts
                        .map((e) => DropdownMenuItem(value: e, child: Text(e)))
                        .toList(),
                    onChanged: (v) => setState(() => _uin = v),
                    decoration: const InputDecoration(labelText: '已有QQ账号')),
              ]))),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('关闭')),
            TextButton(
                onPressed: _busy || _logged
                    ? null
                    : () => _request(false, refreshQr: true),
                child: const Text('刷新登录二维码')),
            TextButton(
                onPressed: _busy ? null : () => _request(false),
                child: const Text('读取账号 / 刷新状态')),
            FilledButton(
                onPressed: _busy || _logged || _uin == null
                    ? null
                    : () => _request(true),
                child: const Text('快捷登录'))
          ]);
}
