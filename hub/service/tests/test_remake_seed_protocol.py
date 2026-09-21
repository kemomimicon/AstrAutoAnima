from types import SimpleNamespace

from astr_auto_anima_hub.remote_jobs import build_remote_command
from astr_auto_anima_hub.schemas import RemoteJobCreateRequest
from astrbot_plugin_comfy_bridge.preset_runtime import parse_generation_directives


def test_remake_wire_order_and_parser():
    target = SimpleNamespace(allow_safety=frozenset({'N', 'H'}), public=SimpleNamespace(kind='group'))
    command, _ = build_remote_command(RemoteJobCreateRequest(
        kind='remake', target_id='group', prompt='引用令牌=' + 'a' * 32,
        character='梅娅', style='蓝铃 云亭', ratio='2:3', remake_fixed_seed=True,
        remake_adjustment='把背景改成雨夜'), target)
    assert command.index('比例=') < command.index('固定种子') < command.index('把背景')
    body = command.split(' ', 2)[2]
    text, options = parse_generation_directives(body)
    assert text == '把背景改成雨夜'
    assert options == {'character': '梅娅', 'style': '蓝铃 云亭', 'ratio': '2:3', 'fixed_seed': True}


def test_empty_options_keep_legacy_wire_format():
    target = SimpleNamespace(allow_safety=frozenset({'N'}), public=SimpleNamespace(kind='group'))
    command, _ = build_remote_command(RemoteJobCreateRequest(
        kind='remake', target_id='group', prompt='引用令牌=' + 'a' * 32), target)
    assert command == '/aremake 引用令牌=' + 'a' * 32
