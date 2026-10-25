"""Stream-check payload integrity, private-path exclusions, and known credential leakage."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
import time

from first_boot import allowed_member,sha256

IMAGE=Path('/opt/aaa-image-052144')
ROOT=Path('/root/autodl-tmp/aaa-install')
PD=ROOT/'astrbot/data/plugin_data/astrbot_plugin_comfy_bridge'


def known_secrets():
    values=[]
    for path in ROOT.glob('runtime-env*.json'):
        data=json.loads(path.read_text('utf-8-sig'))
        values.extend(v.encode() for k,v in data.items() if any(s in k.upper() for s in ['TOKEN','SECRET','KEY']) and isinstance(v,str) and len(v)>=12)
    config=Path('/root/autodl-tmp/aaa-install/napcat-config/webui.json')
    if config.exists():
        data=json.loads(config.read_text('utf-8-sig'))
        for key in ['token','totpSecret']:
            v=data.get(key,'')
            if isinstance(v,str) and len(v)>=12:values.append(v.encode())
    config=json.loads((ROOT/'astrbot/data/cmd_config.json').read_text('utf-8-sig')).get('dashboard',{})
    for key in ['password','pbkdf2_password','jwt_secret']:
        v=config.get(key,'')
        if isinstance(v,str) and len(v)>=12:values.append(v.encode())
    return list(set(values))


def main():
    manifest=json.loads((IMAGE/'payload-manifest.json').read_text())
    archive=IMAGE/'runtime.tar.gz'
    if sha256(archive)!=manifest['sha256']:raise ValueError('Archive SHA mismatch')
    secrets=known_secrets();count=0;scanned=0;last=time.monotonic();virtual={};names=set()
    with tarfile.open(archive,'r|gz') as tar:
        for member in tar:
            count+=1;name=member.name
            if name in names:raise ValueError('Duplicate archive member')
            names.add(name)
            if not allowed_member(member):raise ValueError('Unsafe member path/link')
            if any(x in name for x in ['/models/SEEDVR2/','/models/llava_gguf/','/job_store/','/prompt_pool_backups/','/studio_data/logs/','/ComfyUI/output/','/ComfyUI/input/']):raise ValueError('Excluded private/optional path found')
            if name.endswith(('/cmd_config.json','/runtime-env.json','/runtime-env.full.json','/runtime-env.local.json','/data_v4.db','/INITIAL_CREDENTIALS.json')):raise ValueError('Live credential/database member found')
            if member.isfile() and member.size<=4*1024**2:
                data=tar.extractfile(member).read();scanned+=1
                if any(secret in data for secret in secrets):raise ValueError('Known credential found; private content not printed')
                if name.endswith(('/.image-defaults/templates.json','/studio_data/secrets.json')):virtual[name]=json.loads(data)
            if time.monotonic()-last>=15:
                print('VERIFY_PROGRESS',count,'small_files_scanned',scanned,flush=True);last=time.monotonic()
    if count!=manifest['entries']:raise ValueError('Archive entry count mismatch')
    defaults=virtual['autodl-tmp/aaa-install/.image-defaults/templates.json']
    for kind in ['env_full','env_local']:
        if defaults[kind].get('AAH_ADMIN_TOKEN'):raise ValueError('Template has fixed token')
    if defaults['env_full'].get('AAH_ASTRBOT_API_KEY'):raise ValueError('Template has API credential')
    astro=defaults['astrbot']
    if any(astro.get(k) for k in ['platform','provider_sources','provider','admins_id']):raise ValueError('AstrBot template carries configured identity')
    if any(astro['dashboard'].get(k) for k in ['password','pbkdf2_password','jwt_secret']):raise ValueError('AstrBot template carries password')
    result={'schema':1,'archive_sha256':manifest['sha256'],'entries':count,'small_files_credential_scanned':scanned,'known_credentials_absent':True,'optional_weights_excluded':True,'private_runtime_paths_excluded':True,'crc_stream_read_ok':True,'status':'payload-integrity-and-privacy-verified'}
    (IMAGE/'payload-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PAYLOAD_VALIDATED',json.dumps(result),flush=True)


if __name__=='__main__':main()
