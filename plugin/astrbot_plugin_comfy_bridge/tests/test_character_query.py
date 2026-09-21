import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from character_query_runtime import character_query_text


def test_strong_default_and_explicit_weak():
    path = ROOT / 'data/character_dictionary.example.json'
    strong = character_query_text(path, '初音未来')
    assert '强模式' in strong and 'twintails' in strong.split('可复制提示词：')[1]
    weak = character_query_text(path, 'Hatsune Miku 弱')
    assert '弱模式' in weak and 'twintails' not in weak.split('可复制提示词：')[1]


def test_help_missing_and_admin_disabled():
    path = ROOT / 'data/character_dictionary.example.json'
    assert '用法' in character_query_text(path, '')
    assert '未找到' in character_query_text(path, '不存在的角色')
    with tempfile.TemporaryDirectory() as tmp:
        edit = Path(tmp) / 'edits.json'
        edit.write_text(json.dumps({'entries': {'hatsune_miku': {'disabled': True}}}))
        assert '未找到' in character_query_text(path, '初音未来', edit)


def test_qq_handler_preserves_space_and_disables_llm():
    tree = ast.parse((ROOT / 'main.py').read_text('utf-8-sig'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'achar')
    node.decorator_list = []
    namespace = {'re': re, 'AstrMessageEvent': object, '__package__': 'astrbot_plugin_comfy_bridge',
                 'logger': SimpleNamespace(warning=lambda *a: None)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<query-test>', 'exec'), namespace)
    sent, flags = [], []
    async def send(value): sent.append(value)
    event = SimpleNamespace(message_str='/achar Hatsune Miku 弱', send=send,
                            plain_result=lambda x: x, should_call_llm=lambda x: flags.append(x),
                            stop_event=lambda: flags.append('stop'))
    plugin = SimpleNamespace(_character_dictionary_path=lambda: ROOT / 'data/character_dictionary.example.json',
                             _character_dictionary_edits_path=lambda: None)
    asyncio.run(namespace['achar'](plugin, event, 'Hatsune'))
    assert '弱模式' in sent[0] and 'hatsune_miku' in sent[0]
    assert flags == [False, 'stop']
