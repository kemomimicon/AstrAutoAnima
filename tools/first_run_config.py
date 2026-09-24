"""Local post-install configuration staging. No writes before explicit commit."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import stat
import tempfile
from urllib.parse import urlsplit
import urllib.request

import prompt_pool_manager as pool_tools


class SetupError(ValueError):
    pass


def safe_path(value: str | Path) -> Path:
    raw = str(value).strip()
    if not raw or '"' in raw or '\x00' in raw:
        raise SetupError('路径为空或含多余引号，请用“浏览”选择。')
    if os.name == 'nt' and raw.startswith('/'):
        raise SetupError('这是 Linux 路径。请在实际安装机器运行向导；不能用 Windows 写远程服务器目录。')
    if os.name != 'nt' and PureWindowsPath(raw).drive:
        raise SetupError('这是 Windows 路径，请在实际安装机器运行向导。')
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise SetupError('配置路径必须为绝对路径，请先在部署器中确认真实数据目录。')
    for part in [path, *path.parents]:
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
            raise SetupError('为防误写，暂不支持符号链接、目录联接或重解析路径。')
    return path.resolve()


def read_object(path: Path, default: dict | None = None) -> dict:
    if not path.exists() and default is not None:
        return copy.deepcopy(default)
    try:
        data = json.loads(path.read_text('utf-8-sig'))
    except (OSError, ValueError):
        raise SetupError(f'无法读取有效 JSON：{path.name}。请保留原文件并检查配置。') from None
    if not isinstance(data, dict):
        raise SetupError(f'{path.name} 必须是 JSON 对象。')
    return data


def fingerprint(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def validate_url(value: str) -> str:
    value = value.strip().rstrip('/')
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise SetupError('地址的端口格式不正确。') from None
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise SetupError('请填完整 HTTP(S) 根地址，不要把密钥写在地址中。')
    if parsed.path not in {'', '/'} or parsed.query or parsed.fragment or port == 0:
        raise SetupError('此向导请填服务根地址，不加 /api 路径、参数或片段。')
    return value


def validate_api_key(value: str, required: bool = False) -> str:
    key = value.strip()
    if not key and not required:
        return key
    if key.startswith('abk_') and len(key) == 12:
        raise SetupError('这是列表中的 12 位 Key 前缀，不是密钥。请复制 AstrBot 创建成功弹窗中的完整 API Key（v4.28.0 为 47 位）。')
    if not re.fullmatch(r'abk_[A-Za-z0-9_-]{43}', key):
        raise SetupError('请填写 AstrBot 创建时显示的完整 API Key：abk_ 开头、47 位，不含 Bearer、引号或省略号。此向导按已验证的 Key 格式检查。')
    return key


def validate_dictionary(payload: dict) -> int:
    rows = payload.get('characters')
    if not isinstance(rows, list) or not rows:
        raise SetupError('角色词典需要非空 characters 数组；随机提示词库不能作为角色词典导入。')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('tag'), str) or not row['tag'].strip() or row['tag'] in seen:
            raise SetupError('词典包含无效或重复的角色 tag。')
        seen.add(row['tag'])
        for key in ('aliases', 'appearance', 'copyright', 'gender'):
            if key in row and (not isinstance(row[key], list) or not all(isinstance(x, str) for x in row[key])):
                raise SetupError('词典的 aliases / appearance / copyright / gender 必须是字符串列表。')
    return len(rows)


def validate_targets(payload: dict) -> None:
    rows = payload.get('targets')
    if not isinstance(rows, list):
        raise SetupError('投递配置缺少 targets 列表。')
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SetupError('投递配置包含非对象条目。')
        ident = str(row.get('id', ''))
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', ident) or ident == 'self-private' or ident in seen:
            raise SetupError('投递目标 ID 无效、重复或使用了保留名。')
        seen.add(ident)
        if not str(row.get('label', '')).strip() or len(str(row['label'])) > 120:
            raise SetupError('投递目标显示名称必须为 1～120 个字符。')
        match = re.fullmatch(r'[A-Za-z0-9_.-]+:(GroupMessage|FriendMessage):[A-Za-z0-9_.-]+', str(row.get('umo', '')))
        if not match:
            raise SetupError('投递地址格式不正确，请核对 /sid 返回的 UMO。')
        kind = 'group' if match[1] == 'GroupMessage' else 'private'
        if row.get('kind', kind) != kind:
            raise SetupError('群聊／私聊类型与 UMO 不一致。')
        levels = row.get('allow_safety', ['N', 'H'] if kind == 'group' else ['N', 'H', 'S'])
        if not isinstance(levels, list) or not levels or not set(levels) <= {'N', 'H', 'S'}:
            raise SetupError('目标的安全等级配置无效。')


def target_record(ident: str, label: str, bot: str, number: str, kind: str) -> dict:
    if not re.fullmatch(r'[1-9][0-9]{4,14}', number.strip()):
        raise SetupError('请填写 5～15 位有效群号／QQ 号。')
    if kind not in {'group', 'private'}:
        raise SetupError('请选择群聊或私聊。')
    row = dict(id=ident.strip(), label=label.strip(), kind=kind,
               umo=f'{bot.strip()}:{"GroupMessage" if kind == "group" else "FriendMessage"}:{number.strip()}',
               allow_safety=['N'], enabled=True)
    validate_targets({'targets': [row]})
    return row


def probe_health(url: str) -> str:
    # No credentials, no redirects and no raw response/error body exposed in the UI.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
        with opener.open(validate_url(url) + '/api/v1/health', timeout=5) as response:
            data = json.loads(response.read(65536))
        if data.get('service') == 'astr-auto-anima-hub' and data.get('status') == 'ok':
            return 'Hub 健康接口正常。注意：这不验证令牌、QQ 投递或 GPU 生图。'
        return '地址有响应，但不是预期的 Hub 健康接口。'
    except Exception:
        return '未连通：请确认 Hub 已启动、地址正确；手机／远程访问还需检查网络。'


class SetupSession:
    def __init__(self, runtime_file: str | Path):
        self.runtime_path = safe_path(runtime_file)
        if self.runtime_path.name != 'runtime-env.json' or not self.runtime_path.is_file():
            raise SetupError('请选择安装目录中已有的 runtime-env.json，不要新建空文件。')
        self.env = read_object(self.runtime_path)
        if not all(isinstance(value, str) for value in self.env.values()):
            raise SetupError('runtime-env.json 的环境变量值必须是字符串。')
        self.data_path = safe_path(self.env.get('AAH_PLUGIN_DATA_DIR', ''))
        if not self.data_path.is_dir():
            raise SetupError('插件数据目录不存在。请先启动插件完成初始化，或在部署器纠正路径。')
        if self.data_path == Path(self.data_path.anchor):
            raise SetupError('插件数据目录不能是磁盘根目录。')
        self.paths = {
            '服务连接': self.runtime_path,
            '投递目标': safe_path(self.env.get('AAH_DELIVERY_TARGETS_PATH') or self.data_path / 'hub_state/delivery_targets.json'),
            '用户注册表': safe_path(self.env.get('AAH_LITE_USERS_PATH') or self.data_path / 'hub_state/lite_users.json'),
            '提示词库': safe_path(self.env.get('AAH_PROMPT_POOL_PATH') or self.data_path / 'anima_random_prompt_pool.json'),
            '角色词典': safe_path(self.env.get('AAH_CHARACTER_DICTIONARY_PATH') or self.data_path / 'character_dictionary.json'),
        }
        if len(set(self.paths.values())) != len(self.paths):
            raise SetupError('配置文件路径互相重叠，请纠正后重试。')
        self.targets = read_object(self.paths['投递目标'], {'targets': []})
        validate_targets(self.targets)
        self.users = read_object(self.paths['用户注册表'], {'version': 1, 'users': []})
        self._validate_users()
        self.pool = pool_tools.load_pool(self.paths['提示词库'])
        self.dictionary = read_object(self.paths['角色词典'], {'schema_version': '1.1', 'characters': []})
        self.original = copy.deepcopy(self.payloads())
        self.revisions = {key: fingerprint(path) for key, path in self.paths.items()}
        self.pending_tokens: dict[str, str] = {}

    def payloads(self) -> dict[str, dict]:
        return {'服务连接': self.env, '投递目标': self.targets, '用户注册表': self.users, '提示词库': self.pool, '角色词典': self.dictionary}

    def _validate_users(self):
        if not isinstance(self.users.get('users'), list):
            raise SetupError('用户注册表缺少 users 列表。')
        seen = set()
        ids = set()
        hashes = set()
        for row in self.users['users']:
            if not isinstance(row, dict):
                raise SetupError('用户注册表包含无效条目。')
            qq = str(row.get('qq', ''))
            ident = str(row.get('id', ''))
            hashed = str(row.get('token_sha256', ''))
            if not re.fullmatch(r'[1-9][0-9]{4,14}', qq) or qq in seen:
                raise SetupError('用户 QQ 无效或重复。')
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', ident) or ident in ids:
                raise SetupError('用户 ID 无效或重复。')
            if not re.fullmatch(r'[a-f0-9]{64}', hashed) or hashed in hashes:
                raise SetupError('用户令牌哈希无效或重复。')
            if not str(row.get('label', '')).strip():
                raise SetupError('用户显示名称不能为空。')
            seen.add(qq); ids.add(ident); hashes.add(hashed)

    def set_connections(self, values: dict[str, str]):
        allowed = {'AAH_ASTRBOT_URL', 'AAH_COMFYUI_URL', 'AAH_ASTRBOT_API_KEY', 'AAH_ASTRBOT_BOT_ID', 'AAH_ADMIN_TOKEN'}
        if not set(values) <= allowed:
            raise SetupError('不支持修改该环境变量。')
        env = {**self.env, **{key: value.strip() for key, value in values.items()}}
        validate_api_key(env.get('AAH_ASTRBOT_API_KEY', ''))
        for key in ('AAH_ASTRBOT_URL', 'AAH_COMFYUI_URL'):
            env[key] = validate_url(env.get(key, ''))
        bot = env.get('AAH_ASTRBOT_BOT_ID', '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', bot) or bot == 'your-bot-id':
            raise SetupError('请填 /sid 中的真实 Bot ID，不要保留 your-bot-id。')
        if len(env.get('AAH_ADMIN_TOKEN', '')) < 32:
            raise SetupError('管理员令牌至少 32 字符，请使用随机生成按钮。')
        if env.get('AAH_ADMIN_TOKEN') == env.get('AAH_LITE_TOKEN'):
            raise SetupError('管理员令牌不能与共享普通令牌相同。')
        self.env = env

    def stage_dictionary(self, payload: dict) -> int:
        count = validate_dictionary(payload)
        self.dictionary = copy.deepcopy(payload)
        return count

    def add_target(self, row: dict):
        payload = copy.deepcopy(self.targets)
        payload['targets'].append(row)
        validate_targets(payload)
        self.targets = payload

    def add_user(self, qq: str, label: str, allow_group: bool = False):
        qq = qq.strip()
        if not re.fullmatch(r'[1-9][0-9]{4,14}', qq):
            raise SetupError('请填用户自己的 5～15 位 QQ 号。')
        if len(label.strip()) > 120:
            raise SetupError('备注不能超过 120 个字符。')
        if any(str(row.get('qq')) == qq for row in self.users['users']):
            raise SetupError('此 QQ 已存在。向导不会重置其令牌；请到 Admin“用户”页换发或编辑。')
        ident = 'qq-' + qq
        if any(row['id'] == ident for row in self.users['users']):
            raise SetupError('用户 ID 已被其他账号使用，请到 Admin 用户页处理。')
        token = 'aah_u_' + secrets.token_urlsafe(32)
        self.users['users'].append(dict(id=ident, label=label.strip() or 'QQ ' + qq, qq=qq,
            token_sha256=hashlib.sha256(token.encode()).hexdigest(), allow_group=bool(allow_group), enabled=True))
        self.pending_tokens[qq] = token

    def import_pool(self, source: Path, overwrite: bool = False) -> tuple[int, int]:
        try:
            incoming = pool_tools.load_pool(source)
        except pool_tools.PoolError:
            raise SetupError('导入词库格式无效，请用配套编辑器检查；原库未改动。') from None
        payload = copy.deepcopy(self.pool)
        added, updated = pool_tools.merge_records(payload, incoming['prompts'], overwrite=overwrite)
        definitions = pool_tools.group_definitions(payload)
        known = {item['id'] for item in definitions}
        for group in pool_tools.group_definitions(incoming):
            if group['id'] not in known:
                definitions.append(group); known.add(group['id'])
        payload['custom_group_definitions'] = definitions
        self.pool = payload
        return added, updated

    def changes(self) -> list[str]:
        return [key for key, value in self.payloads().items() if value != self.original[key]]

    def summary(self) -> str:
        lines = ['待保存变更（令牌和 API Key 不在这里显示）：']
        for key in self.changes():
            lines.append(f'• {key} → {self.paths[key]}')
        lines.append(f'目标 {len(self.targets["targets"])} 项；用户 {len(self.users["users"])} 位；词库 {len(self.pool["prompts"])} 条。')
        if self.env.get('AAH_ASTRBOT_API_KEY', '') == '':
            lines.append('注意：尚未填写 AstrBot API Key，App 生成任务仍不可用。')
        if not self.changes():
            lines.append('没有变更，不会写任何文件。')
        lines.append('保存不会重启服务或试发群消息。连接字段变更后请正常重启 Hub。')
        return '\n'.join(lines)

    def commit(self) -> list[Path]:
        changed = self.changes()
        for key, path in self.paths.items():
            safe_path(path)
            if fingerprint(path) != self.revisions[key]:
                raise SetupError(f'{key} 在向导打开后被其他程序修改，请重新载入，避免覆盖新数据。')
        # Multi-file operation is not a database transaction; each file is backed up and atomically replaced.
        backups = []
        completed = []
        for key in changed:
            path = self.paths[key]
            temporary = None
            try:
                data = (json.dumps(self.payloads()[key], ensure_ascii=False, indent=2) + '\n').encode('utf-8')
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    backup = path.with_name(path.name + '.backup_first_run_' + secrets.token_hex(6))
                    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(path.read_bytes()); stream.flush(); os.fsync(stream.fileno())
                    backups.append(backup)
                fd, temporary = tempfile.mkstemp(prefix='.aaa-first-run-', dir=path.parent)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
                if fingerprint(path) != self.revisions[key]:
                    raise SetupError('目标在保存期间发生变化，已停止。')
                os.replace(temporary, path)
                temporary = None
                self.revisions[key] = fingerprint(path)
                self.original[key] = copy.deepcopy(self.payloads()[key])
                completed.append(key)
            except Exception:
                raise SetupError('保存中断。已保存：' + ('、'.join(completed) or '无') +
                    '。未继续写入后续文件；请检查同目录 .backup_first_run_ 备份，确认状态后重新载入。') from None
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)
        return backups
