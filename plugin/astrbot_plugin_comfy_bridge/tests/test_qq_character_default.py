import ast
from pathlib import Path
from types import SimpleNamespace


def test_qq_strong_explicit_overrides_and_other_platform_unchanged():
    source = Path(__file__).resolve().parents[1] / 'main.py'
    tree = ast.parse(source.read_text('utf-8-sig'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_character_lookup_mode')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<mode-test>', 'exec'), namespace)
    select = namespace['_character_lookup_mode']
    plugin = SimpleNamespace(config={'character_dictionary_default_mode': 'weak'})
    qq = SimpleNamespace(get_platform_name=lambda: 'aiocqhttp')
    web = SimpleNamespace(get_platform_name=lambda: 'webchat')
    assert select(plugin, {}, qq) == 'strong'
    for explicit in ('weak', 'off', 'strong', '弱', '关闭'):
        assert select(plugin, {'character_tag_mode': explicit}, qq) == explicit
    assert select(plugin, {}, web) == 'weak'
    assert select(plugin, {'character_tag_mode': 'strong'}, web) == 'strong'
    assert select(plugin, {}) == 'weak'
    # All generation variants use the shared resolution path.
    generate = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_generate')
    assert 'mode=self._character_lookup_mode(options, event)' in ast.unparse(generate)
