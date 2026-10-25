"""Exercise an actual patch, preserved fixture data, real Hub startup and rollback."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import venv


def main(patch,work):
    patch=patch.resolve();work=work.resolve()
    if work.exists():raise ValueError('Use a fresh smoke directory')
    work.mkdir(parents=True);install=work/'legacy install with spaces';hub=install/'hub'
    data=install/'astro/data';plugin=data/'plugins/astrbot_plugin_comfy_bridge';comfy=install/'comfy'
    shutil.copytree(patch/'payload/hub',hub);shutil.copytree(patch/'payload/web',hub/'web')
    shutil.copytree(patch/'payload/plugin',plugin);comfy.mkdir()
    (comfy/'main.py').write_text('# fixture, never executed\n')
    (comfy/'models').mkdir();(comfy/'models/kept.safetensors').write_bytes(b'fixture-model-preserved')
    (plugin/'metadata.yaml').write_text('version: 0.5.0-beta.2\n')
    project=hub/'pyproject.toml';project.write_text(project.read_text().replace('0.5.2b1','0.5.0b2'))
    init=hub/'src/astr_auto_anima_hub/__init__.py';init.write_text('__version__="0.5.0-beta.2"\n')
    (hub/'web/index.html').write_text('<h1>old fixture</h1>')
    venv.create(hub/'.venv',with_pip=True)
    python=hub/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    subprocess.run([str(python),'-m','pip','install','-e',str(hub)],check=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    token=secrets.token_urlsafe(48);pd=data/'plugin_data/astrbot_plugin_comfy_bridge';pd.mkdir(parents=True)
    pool=pd/'anima_random_prompt_pool.json'
    pool.write_text(json.dumps({'schema_version':3,'prompts':[{'id':'kept','prompt':'safe landscape','enabled':True,'source_code':'G','safety_code':'N'}]}))
    env={'AAH_ADMIN_TOKEN':token,'AAH_PORT':str(port),'AAH_HOST':'127.0.0.1','AAH_EXECUTION_MODE':'remote',
         'AAH_PLUGIN_DIR':str(plugin),'AAH_PLUGIN_DATA_DIR':str(pd),'AAH_COMFYUI_ROOT':str(comfy),
         'AAH_ASTRBOT_BOT_ID':'fixture-bot','AAH_WEB_ROOT':str(hub/'web')}
    cfg=install/'runtime-env.json';cfg.write_text(json.dumps(env));(install/'.aaa-managed-install').write_text('')
    services=[{'name':'Hub','cwd':str(hub),'command':[str(python),'-m','astr_auto_anima_hub'],'port':port}]
    (install/'services.json').write_text(json.dumps(services))
    for name in ['deploy_project.py','deployment_support.py','download_network.py','install_progress.py','project_components.py','gufeng_resource.py']:
        shutil.copy2(patch/'payload/runtime'/name,install/name)
    protected={p:p.read_bytes() for p in [cfg,pool,comfy/'models/kept.safetensors']}
    spec=importlib.util.spec_from_file_location('aaa_patch_smoke_updater',patch/'update.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    plan=module.managed(install);backup=module.apply(plan,confirm_stopped=True)
    childenv={k:v for k,v in os.environ.items() if not k.startswith('AAH_') and k not in {'PYTHONPATH','PYTHONHOME'}}
    childenv.update(env,PYTHONDONTWRITEBYTECODE='1')
    with (work/'hub-smoke.log').open('wb') as log:
        process=subprocess.Popen([str(python),'-B','-m','astr_auto_anima_hub'],cwd=hub,env=childenv,stdout=log,stderr=log)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(60):
                if process.poll() is not None:raise RuntimeError('Updated fixture Hub exited; inspect the smoke log')
                try:
                    with opener.open(f'http://127.0.0.1:{port}/api/v1/health',timeout=1) as response:health=json.load(response)
                    assert health['status']=='ok' and health['version']=='0.5.2-beta.1';break
                except OSError:time.sleep(.5)
            else:raise RuntimeError('Updated Hub did not become healthy')
        finally:process.terminate();process.wait(timeout=20)
    for p,content in protected.items():assert p.read_bytes()==content
    module.rollback(backup)
    assert '0.5.0-beta.2' in init.read_text()
    for p,content in protected.items():assert p.read_bytes()==content
    report={'actual_patch_apply':True,'fixture_legacy_version':'0.5.0-beta.2','updated_Hub_health':'0.5.2-beta.1',
            'credentials_pool_model_bytes_preserved':True,'code_rollback':True,'production_services_modified':False,'gpu_job_started':False}
    (work/'upgrade-smoke-result.json').write_text(json.dumps(report,indent=2)+'\n')
    print('REAL_PATCH_HUB_STARTUP_AND_ROLLBACK_PASSED')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--patch',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();main(a.patch,a.work)
