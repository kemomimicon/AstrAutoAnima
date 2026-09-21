import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../core/courtyard_theme.dart';

final appThemeMode = ValueNotifier<ThemeMode>(ThemeMode.system);
final appSkin = ValueNotifier<String>('courtyard');
final showRemakeOptions = ValueNotifier<bool>(true);

Future<void> loadAppTheme() async {
  final prefs = await SharedPreferences.getInstance();
  final value = prefs.getString('aaa_theme_mode');
  showRemakeOptions.value = prefs.getBool('aaa_remake_options') ?? true;
  appSkin.value =
      prefs.getString('aaa_skin') == 'classic' ? 'classic' : 'courtyard';
  appThemeMode.value = ThemeMode.values
      .firstWhere((mode) => mode.name == value, orElse: () => ThemeMode.system);
}

class SettingsDrawer extends StatelessWidget {
  const SettingsDrawer({required this.onDisconnect, this.onGallery, super.key});
  final Future<void> Function() onDisconnect;
  final VoidCallback? onGallery;

  @override
  Widget build(BuildContext context) => Drawer(
        width: (MediaQuery.sizeOf(context).width - 48).clamp(240, 320),
        child: SafeArea(
            child: ListView(children: [
          const ListTile(title: Text('设置', style: TextStyle(fontSize: 24))),
          ValueListenableBuilder<bool>(
            valueListenable: showRemakeOptions,
            builder: (context, value, _) => SwitchListTile(
              title: const Text('重跑前显示调整菜单'),
              subtitle: const Text('关闭后沿用原配置并更换种子；修改内容仅当次有效'),
              value: value,
              onChanged: (next) async {
                showRemakeOptions.value = next;
                final prefs = await SharedPreferences.getInstance();
                await prefs.setBool('aaa_remake_options', next);
              },
            ),
          ),
          if (onGallery != null)
            ListTile(
                leading: const Icon(Icons.photo_library_outlined),
                title: const Text('画风画廊'),
                onTap: onGallery),
          Padding(
              padding: const EdgeInsets.all(16),
              child: ValueListenableBuilder<String>(
                  valueListenable: appSkin,
                  builder: (context, skin, _) =>
                      DropdownButtonFormField<String>(
                          initialValue: skin,
                          isExpanded: true,
                          decoration: const InputDecoration(labelText: '皮肤'),
                          items: const [
                            DropdownMenuItem(
                                value: 'courtyard', child: Text('蓝铃云庭')),
                            DropdownMenuItem(
                                value: 'classic', child: Text('原有主题'))
                          ],
                          onChanged: (value) async {
                            if (value == null) return;
                            appSkin.value = value;
                            await (await SharedPreferences.getInstance())
                                .setString('aaa_skin', value);
                          }))),
          ValueListenableBuilder<ThemeMode>(
              valueListenable: appThemeMode,
              builder: (context, mode, _) => Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  child: DropdownButton<ThemeMode>(
                      isExpanded: true,
                      value: mode,
                      items: const [
                        DropdownMenuItem(
                            value: ThemeMode.system, child: Text('跟随系统')),
                        DropdownMenuItem(
                            value: ThemeMode.light, child: Text('浅色')),
                        DropdownMenuItem(
                            value: ThemeMode.dark, child: Text('深色'))
                      ],
                      onChanged: (value) async {
                        if (value == null) return;
                        appThemeMode.value = value;
                        final prefs = await SharedPreferences.getInstance();
                        await prefs.setString('aaa_theme_mode', value.name);
                      }))),
          ListTile(
              leading: const CourtyardIcon(Icons.dns_outlined),
              title: const Text('切换服务器 / 令牌'),
              subtitle: const Text('退出当前连接后重新填写；不会显示当前令牌'),
              onTap: () async {
                final yes = await showDialog<bool>(
                    context: context,
                    builder: (context) => AlertDialog(
                            title: const Text('切换连接？'),
                            content: const Text('将清除本机当前连接凭据，服务器已排队任务不会因此取消。'),
                            actions: [
                              TextButton(
                                  onPressed: () =>
                                      Navigator.pop(context, false),
                                  child: const Text('取消')),
                              FilledButton(
                                  onPressed: () => Navigator.pop(context, true),
                                  child: const Text('切换'))
                            ]));
                if (yes == true) await onDisconnect();
              }),
          ListTile(
              leading: const CourtyardIcon(Icons.help_outline),
              title: const Text('帮助与使用手册'),
              onTap: () => showDialog<void>(
                  context: context,
                  builder: (context) => const AlertDialog(
                      title: Text('使用说明'),
                      content: SingleChildScrollView(
                          child: Text(
                              '连接：填写服务器6278端口映射地址与Hub令牌，手机不能填写127.0.0.1。云实例密钥与Hub令牌、Civitai密钥不是同一套。\n\n'
                              '跑图：选择角色、画风与提示词后提交。高级设置保存采样参数、主光/效果光、主材质/细节/表面效果；均可选无，冲突组合会拒绝。SeedVR2本身不使用这些提示词。\n\n'
                              '角色预设：资源→预设→角色→新增→从LoRA库选择，自动填写真实相对路径；可填写推荐触发词。先在LoRA库扫描并分类。角色词典开关开启时使用词典输入，不使用预设下拉。\n\n'
                              '中文生图需要文本LLM；反推需要WD/CLTagger及JoyCaption。仅反推可复选分类，不提交生图。\n\n'
                              '下载LoRA：管理员先在Hub配置Civitai密钥并重启Hub。资源→LoRA→下载，选择版本和触发词，默认存入loras/anima_lora；新目录是LoRA根目录内的子目录。旧下载和模型不会自动搬迁。\n\n'
                              '记录：查看任务与图片，循环箭头用于新种子重跑，大拇指用于收藏提示词，警告图标用于举报。\n\n'
                              '收藏：提示词浏览中的个人收藏可取消；角色词典中的星号可编辑或取消收藏。\n\n'
                              '安全模式由管理员控制。审核未通过不会返回图片。\n\n'
                              '五连抽：每张新图绑定词库编号；部分失败仍保留成功图片。旧记录没有可靠对应时不按位置猜测编号。\n\n'
                              '储存：先盘点、打包，再确认清理；真正删除不可撤销。定期清理仅插件缓存，随机画风在output/AAA-RandomStyle独立清理。去元数据仅支持PNG，仍保留任务记录。\n\n'
                              '水印：管理端上传透明PNG签名，自动仅管理员；QQ引用本人任务图回复“打上水印”。原图保留，副本默认在Author Pictures。\n\n'
                              '服务器地址、令牌：通过设置切换连接；不要把令牌截图发给他人。'))))),
          ListTile(
              leading: const CourtyardIcon(Icons.info_outline),
              title: const Text('制作组'),
              onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => Scaffold(
                      appBar: AppBar(title: const Text('制作组')),
                      body: const SizedBox.expand())))),
          ListTile(
              leading: const CourtyardIcon(Icons.info_outline),
              title: const Text('版本信息'),
              onTap: () => showAboutDialog(
                  context: context,
                  applicationName: 'AstrAutoAnima',
                  applicationVersion: '0.5.0 Beta（具体构建号请查看连接页版本）')),
        ])),
      );
}
