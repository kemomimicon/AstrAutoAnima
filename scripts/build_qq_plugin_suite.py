"""Build the standalone AstrBot QQ plugin and its documented workflow suite."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'plugin'), str(ROOT / 'scripts')]
from astrbot_plugin_comfy_bridge.workflow_registry import load_workflow_registry
from astrbot_plugin_comfy_bridge.workflow_runtime import validate_workflow_nodes
from verify_release_archives import check


def serialized(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def archive(path, entries):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 28, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        assert {n: z.read(n) for n in z.namelist()} == entries
    failures = check(path)
    if failures:
        raise ValueError(f'{path.name}: {failures}')


def build(out):
    if out.resolve().is_relative_to(ROOT):
        raise ValueError('Output must be outside the public source tree')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise ValueError('Commit and freeze source first')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    out.mkdir(parents=True, exist_ok=True)
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    plugin_prefix = 'plugin/astrbot_plugin_comfy_bridge/'
    entries = {}
    for name in names:
        if not name.startswith(plugin_prefix) or 'tests' in Path(name).parts:
            continue
        relative = name.removeprefix(plugin_prefix)
        if relative == 'README.md':
            continue
        data = (ROOT / name).read_bytes()
        if Path(name).suffix in {'.py', '.json', '.yaml', '.md'}:
            data = data.replace(b'\r\n', b'\n')
        entries[relative] = data
    schema = json.loads(entries['_conf_schema.json'])
    defaults = {
        'workflow_path': 'data/workflows/AAA_QQ_Quick_api.json',
        'hq_workflow_path': 'data/workflows/AAA_QQ_HQ_api.json',
        'refine_workflow_path': 'data/workflows/AAA_QQ_Refine_api.json',
        'reverse_workflow_path': 'data/workflows/Anima_WD_Only_Reverse_api.json',
        'style_lora_node_ids': '', 'style_lora_mode': 'dynamic',
        'hq_use_seedvr2': False, 'agent_tools_enabled': False,
    }
    for key, value in defaults.items():
        schema[key]['default'] = value
    entries['_conf_schema.json'] = serialized(schema)
    guide = (ROOT / 'docs/QQ_PLUGIN_ONLY_GUIDE.md').read_bytes().replace(b'\r\n', b'\n')
    entries['README.md'] = guide
    entries['QQ指令操作说明.txt'] = b'\xef\xbb\xbf' + guide
    entries['LICENSE'] = (ROOT / 'LICENSE').read_bytes()
    entries['THIRD_PARTY_NOTICES.md'] = (ROOT / 'THIRD_PARTY_NOTICES.md').read_bytes()
    metadata = entries['metadata.yaml'].decode().replace('version: 0.5.2-beta.1', 'version: 0.5.2-beta.1+qq.1')
    metadata = metadata.replace('repo: ""', 'repo: "https://github.com/kemomimicon/AstrAutoAnima"')
    entries['metadata.yaml'] = metadata.encode()
    tree = ast.parse((ROOT / 'tools/deploy_project.py').read_text('utf-8-sig'))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {'quick_workflow', 'configured_anima_workflow'}]
    assert len(functions) == 2
    scope = {'Path': Path, 'shutil': shutil, 'json': json, 'no_links': lambda p: None,
             'json_write': lambda p, data: p.write_bytes(serialized(data))}
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'existing-deployment-templates', 'exec'), scope)
    with tempfile.TemporaryDirectory(prefix='aaa-qq-workflows-') as temporary:
        tmp = Path(temporary)
        model_names = ['anima-base-v1.0.safetensors', 'qwen_3_06b_base.safetensors', 'qwen_image_vae.safetensors']
        # Empty test inputs only select public model names; no model bytes enter the package.
        from types import SimpleNamespace
        for folder, name in zip(['diffusion_models', 'text_encoders', 'vae'], model_names):
            p = tmp / 'models' / folder / name
            p.parent.mkdir(parents=True)
            p.touch()
        plan = SimpleNamespace(unet=tmp/'models/diffusion_models'/model_names[0],
                               clip=tmp/'models/text_encoders'/model_names[1], vae=tmp/'models/vae'/model_names[2])
        quick = scope['quick_workflow'](plan, tmp, lambda message: None)
        quick['11']['inputs']['text'] = 'mountain landscape, lake, daylight'
        quick['12']['inputs']['text'] = 'low quality, blurry, watermark'
        workflows = {'AAA_QQ_Quick_api.json': quick}
        for src, target in [('Anima_HQ_Txt2Img_Beta_api.json', 'AAA_QQ_HQ_api.json'),
                            ('Anima_Refine_Existing_Beta_api.json', 'AAA_QQ_Refine_api.json')]:
            shutil.copy2(ROOT/'comfyui/workflows'/src, tmp/src)
            scope['configured_anima_workflow'](tmp, quick, src, target)
            workflows[target] = json.loads((tmp/target).read_text('utf-8'))
        workflows['Anima_WD_Only_Reverse_api.json'] = json.loads((ROOT/'comfyui/workflows/Anima_WD_Only_Reverse_api.json').read_text('utf-8'))
    registry = load_workflow_registry(ROOT/'plugin/astrbot_plugin_comfy_bridge/data/workflow_registry.json')
    mapping = dict(zip(['quick_txt2img_v1', 'hq_txt2img_anima_v1', 'refine_existing_v1', 'reverse_anime_v1'], workflows))
    for ident, name in mapping.items():
        graph = workflows[name]
        validate_workflow_nodes(graph, registry.resolve(ident))
        for node in graph.values():
            for value in node.get('inputs', {}).values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    assert value[0] in graph, (name, value)
        if ident != 'reverse_anime_v1':
            assert 'YOUR_' not in json.dumps(graph)
            assert not any(n['class_type'] == 'LoraLoader' for n in graph.values())
        entries['data/workflows/'+name] = serialized(graph)
    for name, data in entries.items():
        if name.endswith('.py'):
            compile(data.decode('utf-8-sig'), name, 'exec')
    assert json.loads(entries['data/anima_random_prompt_pool.json'])['prompts'] == []
    assert b'"qq_official": True' in entries['platform_switchboard.py']
    manifest = {'display_version': '0.5.2-1.44 / qq.1', 'source_commit': commit,
                'standalone_qq_chain': True, 'requires_hub': False, 'defaults': defaults,
                'files': {n: hashlib.sha256(d).hexdigest() for n, d in entries.items()}}
    entries['qq-package-manifest.json'] = serialized(manifest)
    plugin = out/'astrbot_plugin_comfy_bridge-0.5.2-1.44-qq.1.zip'
    archive(plugin, entries)
    suite = {plugin.name: plugin.read_bytes(), '00_安装与QQ指令说明.txt': b'\xef\xbb\xbf'+guide,
             'LICENSE': entries['LICENSE'], 'THIRD_PARTY_NOTICES.md': entries['THIRD_PARTY_NOTICES.md'],
             '新装配置参考.json': serialized({k: v['default'] for k, v in schema.items()}),
             '模型下载清单.json': (ROOT/'tools/model_catalog.json').read_bytes(),
             '外部节点依赖清单.json': (ROOT/'comfyui/dependency_manifest.json').read_bytes(),
             '词库示例.json': serialized({'prompts': [{'id':'qq-example-landscape', 'prompt':'mountain landscape, lake, daylight',
                'source_code':'B', 'safety_code':'N', 'safety_level':'normal', 'enabled':True}]})}
    for name, graph in workflows.items():
        suite['工作流API/'+name] = serialized(graph)
    for name in ['Anima_SeedVR2_Refine_Beta_api.json', 'Anima_Base_Multi_Person_Beta_api.json']:
        suite['可选扩展工作流/'+name] = (ROOT/'comfyui/workflows'/name).read_bytes()
    prefix = 'comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools/'
    for name in names:
        if name.startswith(prefix):
            suite['ComfyUI自定义节点/ComfyUI-AstrAutoAnima-Workflow-Tools/'+name.removeprefix(prefix)] = (ROOT/name).read_bytes()
    suite['工作流与扩展说明.txt'] = ('基础Quick、HQ和Anima精修使用ComfyUI自带节点。\n'
       'WD反推：安装本包自定义节点及外部节点依赖清单中ComfyUI-Booru-Tagger，WD模型按该节点说明安装；不需要JoyCaption。\n'
       'SeedVR2、多人图按可选扩展模板所列节点配置；不参与首次基础出图。\n'
       '模型路径和节点依赖清单是公共模板，请按实际ComfyUI列表选择；不要覆盖正在使用的个人工作流。\n'
       '模型使用模型下载清单中的固定URL，下载后核对同一条目的大小与SHA256。\n').encode('utf-8-sig')
    suite['QQ插件包验收.json'] = serialized({'source_commit':commit, 'python_syntax':True, 'workflow_registry_and_links':True,
       'quick_nodes':len(quick), 'lora_placeholders_removed':True, 'persistent_user_data_included':False,
       'gpu_job_started':False, 'files':{n:hashlib.sha256(d).hexdigest() for n,d in suite.items()}})
    total = out/'AAA_QQ_Plugin_Suite_0.5.2-1.44-qq.1.zip'
    archive(total, suite)
    for p in [plugin, total]:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        p.with_suffix('.sha256.txt').write_text(digest+'  '+p.name+'\n', encoding='ascii')
        print(p, p.stat().st_size, digest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
