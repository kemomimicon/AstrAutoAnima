"""Build the 0.5.2-1.44 image payload from the prepared application environment."""
from __future__ import annotations
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import shutil
import subprocess
import tarfile
import time

BASE = Path('/root/autodl-tmp')
ROOT = BASE / 'aaa-install'
STUDIO = BASE / 'apps/AnimaLoraStudio'
IMAGE = Path('/opt/aaa-image-052144')
PUBLIC = Path('/root/AstrAutoAnima')
SKIP = {'.git','__pycache__','.pytest_cache','.cache','node_modules','logs','temp'}


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def tree(paths, root, exclude=()):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Source directory: ' + str(root))
    for parent, dirs, files in os.walk(root, followlinks=False):
        current = Path(parent)
        dirs[:] = sorted(n for n in dirs if n not in SKIP and (current/n).relative_to(root).as_posix() not in exclude)
        paths.add(current)
        for name in dirs + sorted(files):
            p = current/name
            if p.is_dir() and not p.is_symlink():
                continue
            if name.endswith(('.log','.pyc','.pyo')) or name == '.env' or name.startswith('.env.') and name != '.env.example':
                continue
            paths.add(p)


def selected():
    paths = set()
    tree(paths, ROOT/'ComfyUI', {'models','user','input','output','web_custom_versions'})
    for name in ('diffusion_models','text_encoders','vae','booru_tagger'):
        tree(paths, ROOT/'ComfyUI/models'/name)
    tree(paths, ROOT/'ComfyUI/user/default/workflows')
    tree(paths, ROOT/'astrbot/.venv')
    for name in ('astrbot_plugin_comfy_bridge','astrbot_plugin_anima_master'):
        tree(paths, ROOT/'astrbot/data/plugins'/name)
    tree(paths, ROOT/'hub')
    for name in ('optional','tools'):
        tree(paths, ROOT/name)
    pd=ROOT/'astrbot/data/plugin_data/astrbot_plugin_comfy_bridge'
    for name in ('anima_random_prompt_pool.json','character_dictionary.json','workflow_registry.optional.json'):
        paths.add(pd/name)
    for name in ('character_dictionary_sources','hub_state/extensions/packages'):
        tree(paths,pd/name)
    paths.add(pd/'hub_state/extensions/active.json')
    for name in ('anima_random_prompt_pool.json','presets.json'):
        paths.add(ROOT/'data/local'/name)
    for name in ('.aaa-managed-install','deploy_project.py','deployment_support.py','download_network.py',
                 'install_progress.py','project_components.py','gufeng_resource.py','services.full.json','services.local.json','services.json'):
        paths.add(ROOT/name)
    tree(paths,STUDIO,{'studio_data','data_exports'})
    tree(paths,BASE/'apps/node-v22.20.0-linux-x64')
    paths.add(BASE/'apps/Start-Studio.sh')
    tree(paths,BASE/'aaa-bootstrap-py312')
    for p in paths:
        if not p.exists() and not p.is_symlink():
            raise ValueError('Missing image input: '+str(p))
    return sorted(paths,key=str)


def schema_defaults(schema):
    defaults={'string':'','text':'','bool':False,'int':0,'float':0.0,'list':[],'dict':{},'object':{}}
    return {k:schema_defaults(v['items']) if v.get('type')=='object' and 'items' in v else
            copy.deepcopy(v.get('default',defaults.get(v.get('type')))) for k,v in schema.items()}


def virtual():
    envs={}
    keys={'AAH_EXECUTION_MODE','AAH_HOST','AAH_PORT','AAH_PLUGIN_DIR','AAH_PLUGIN_DATA_DIR','AAH_COMFYUI_ROOT',
          'AAH_ASTRBOT_URL','AAH_COMFYUI_URL','AAH_WEB_ROOT','AAH_LOCAL_WORKFLOW_PATH','AAH_LOCAL_GUFENG_CATALOG_PATH'}
    for name in ('full','local'):
        source=json.loads((ROOT/f'runtime-env.{name}.json').read_text('utf-8-sig'))
        envs['env_'+name]={k:v for k,v in source.items() if k in keys}
        envs['env_'+name]['AAH_ADMIN_TOKEN']=''
    envs['env_full'].update(AAH_ASTRBOT_API_KEY='',AAH_ASTRBOT_BOT_ID='your-bot-id')
    run=subprocess.run([str(ROOT/'astrbot/.venv/bin/python'),'-B','-c',
        'import json; from astrbot.core.config.default import DEFAULT_CONFIG; print("AAA_DEFAULTS="+json.dumps(DEFAULT_CONFIG))'],
        cwd=IMAGE,capture_output=True,text=True,check=True)
    astro=json.loads(next(x[13:] for x in run.stdout.splitlines() if x.startswith('AAA_DEFAULTS=')))
    astro.update(platform=[],provider_sources=[],provider=[],admins_id=[])
    astro['dashboard'].update(username='astrbot',password='',pbkdf2_password='',jwt_secret='',host='127.0.0.1')
    envs['astrbot']=astro
    result={ROOT/'.image-defaults/templates.json':envs}
    for name in ('astrbot_plugin_comfy_bridge','astrbot_plugin_anima_master'):
        plugin=ROOT/'astrbot/data/plugins'/name
        config=schema_defaults(json.loads((plugin/'_conf_schema.json').read_text('utf-8-sig')))
        live=json.loads((ROOT/f'astrbot/data/config/{name}_config.json').read_text('utf-8-sig'))
        if name=='astrbot_plugin_comfy_bridge':
            for k in ('workflow_path','hq_workflow_path','refine_workflow_path','reverse_workflow_path','seedvr2_workflow_path',
                      'detail_repair_workflow_path','workflow_registry_path','positive_prompt_node_id','negative_prompt_node_id',
                      'latent_node_id','sampler_node_id','style_lora_mode','style_lora_node_ids','comfyui_output_root',
                      'input_dir','output_dir','prompt_pool_path','job_store_path','reverse_history_dir'):
                if k in live:config[k]=live[k]
            pd=ROOT/'astrbot/data/plugin_data/astrbot_plugin_comfy_bridge'
            config.update(comfyui_base_url='http://127.0.0.1:8188',hq_use_seedvr2=False,reverse_workflow_enabled=True,
                character_dictionary_enabled=True,character_dictionary_path=str(pd/'character_dictionary.json'))
        else:
            # All AM defaults except the selected public base-model wiring.
            for k in ('anima_master_comfyui_connection','anima_master_models'):
                if k in live:config[k]=live[k]
        result[ROOT/f'astrbot/data/config/{name}_config.json']=config
    comfy=ROOT/'ComfyUI/models'
    result[STUDIO/'studio_data/secrets.json']={'download_source':'modelscope',
        'download_sources':{'training':'modelscope','wd14':'modelscope','upscaler':'modelscope'},
        'wd14':{'model_id':str(comfy/'booru_tagger/wd-eva02-large-tagger-v3')}}
    return {p:(json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode() for p,v in result.items()}


def build():
    if IMAGE.exists():raise ValueError('Image directory already exists')
    if shutil.disk_usage('/').free < 20*2**30:raise ValueError('System disk space')
    IMAGE.mkdir(mode=0o755)
    paths=selected();files=virtual()
    archive=IMAGE/'runtime.tar.gz'
    command=['pigz','-1','-p','6'] if shutil.which('pigz') else ['gzip','-1']
    seen={};total=0;count=0;last=time.monotonic()
    with archive.open('xb') as output:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=output)
        try:
            with tarfile.open(fileobj=process.stdin,mode='w|',format=tarfile.PAX_FORMAT) as tar:
                for p in paths:
                    name=p.relative_to('/root').as_posix()
                    info=tar.gettarinfo(str(p),arcname=name)
                    info.uid=info.gid=0;info.uname=info.gname='root'
                    source=p
                    if info.issym():
                        resolved=p.resolve()
                        if resolved.is_relative_to(Path('/root/miniconda3/bin')) and resolved.is_file() and p.name.startswith('python'):
                            source=resolved;info.type=tarfile.REGTYPE;info.linkname='';info.size=resolved.stat().st_size
                        else:
                            if info.linkname.startswith('/'):
                                if not resolved.is_relative_to(BASE):raise ValueError('External link: '+name)
                                info.linkname=os.path.relpath(resolved,p.parent)
                            if not posixpath.normpath(posixpath.join(posixpath.dirname(name),info.linkname)).startswith('autodl-tmp/'):
                                raise ValueError('External link: '+name)
                    if info.isfile() and info.size>=16*2**20:
                        key=(p.name,info.size);sha=digest(source)
                        previous=seen.setdefault(key,{})
                        if sha in previous:
                            info.type=tarfile.LNKTYPE;info.linkname=previous[sha];info.size=0
                        else:previous[sha]=name
                    if info.isfile():
                        total+=info.size
                        with source.open('rb') as f:tar.addfile(info,f)
                    else:tar.addfile(info)
                    count+=1
                    if time.monotonic()-last>=15:
                        progress={'entries':count,'total':len(paths)+len(files),'compressed_bytes':archive.stat().st_size}
                        (IMAGE/'build-progress.json').write_text(json.dumps(progress))
                        print('BUILD_PROGRESS',json.dumps(progress),flush=True);last=time.monotonic()
                        if shutil.disk_usage('/').free<3*2**30:raise ValueError('System disk reserve')
                for p,data in files.items():
                    info=tarfile.TarInfo(p.relative_to('/root').as_posix());info.size=len(data);info.mode=0o600
                    tar.addfile(info,io.BytesIO(data));total+=len(data);count+=1
        finally:
            process.stdin.close()
            if process.wait()!=0:raise ValueError('Payload compression')
    manifest={'schema':1,'image':'0.5.2-1.44-image.1','sha256':digest(archive),'compressed_bytes':archive.stat().st_size,
        'unique_bytes':total,'entries':count,'top_roots':['aaa-install','apps/AnimaLoraStudio','apps/node-v22.20.0-linux-x64','apps/Start-Studio.sh','aaa-bootstrap-py312'],
        'optional_downloads':['SeedVR2 weights','JoyCaption','CL Tagger','NapCat/QQ'],
        'software_source_commit':'29882ba009719f1707ac0bb2690b04df1763dff7'}
    (IMAGE/'payload-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('PAYLOAD_BUILT',json.dumps(manifest),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--build',action='store_true');args=parser.parse_args()
    if args.build:build()
    else:print('Build prepared application runtime: --build')
