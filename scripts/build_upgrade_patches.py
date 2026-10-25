"""Build 0.5.2-1.44 preserving-data upgrade patches from published component bytes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from build_platform_full_suites import load_baseline,read_zip,BASE_COMMIT,BASE_SHA,TIME

ROOT=Path(__file__).resolve().parents[1]


def create_entries(base,platform,commit):
    lazy=read_zip(base[f'deployment/AstrAutoAnima-lazy-bundle-{platform}-0.5.2-beta.1.zip'],True)
    plugin=read_zip(base['components/astrbot_plugin_comfy_bridge-0.5.2-beta.1.zip'])
    hub=read_zip(base['components/astr_auto_anima_hub_service-0.5.2-beta.1.zip'])
    workflow=read_zip(base['components/Anima_Workflow_Pack-0.8.0-beta.1-public.zip'],True)
    payload={'plugin/'+n:d for n,d in plugin.items()}
    payload.update({'hub/'+n:d for n,d in hub.items() if not n.startswith('web/')})
    payload.update({'web/'+n.removeprefix('web/'):d for n,d in hub.items() if n.startswith('web/')})
    node='custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools/'
    payload.update({'node/'+n.removeprefix(node):d for n,d in workflow.items() if n.startswith(node)})
    payload.update({'workflows/'+n.removeprefix('workflows/'):d for n,d in workflow.items() if n.startswith('workflows/') and n.endswith('.json')})
    for name in ['deploy_project.py','deployment_support.py','download_network.py','install_progress.py','project_components.py','gufeng_resource.py']:
        payload['runtime/'+name]=lazy['tools/'+name]
    if platform=='windows':
        # The proven generic launcher preserves the active profile when no --profile is supplied.
        marker="def windows_start_script(profile=None):"
        scope={};source=lazy['tools/deployment_support.py'].decode('utf-8-sig')
        import ast
        function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='windows_start_script')
        exec(compile(ast.Module(body=[function],type_ignores=[]),'launcher-template','exec'),scope)
        for name,profile in [('Start.cmd',None),('Start-Full.cmd','full'),('Start-Local.cmd','local')]:
            payload['runtime/'+name]=scope['windows_start_script'](profile).encode('ascii')
        launcher=b'@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\nset "PYTHONUTF8=1"\r\ncd /d "%~dp0."\r\nwhere py >nul 2>nul\r\nif errorlevel 1 (\r\n python update.py --gui\r\n) else (\r\n py -3 update.py --gui\r\n)\r\nif errorlevel 1 pause\r\n'
    else:
        for name,profile in [('Start.sh',''),('Start-Full.sh',' --profile full'),('Start-Local.sh',' --profile local')]:
            payload['runtime/'+name]=('#!/bin/sh\nset -eu\nD=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$D/hub/.venv/bin/python" -B "$D/deploy_project.py" --start "$D"'+profile+'\n').encode()
        launcher=b'#!/bin/sh\nset -eu\nD=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "${AAA_PYTHON:-python3}" -B "$D/update.py" "$@"\n'
    payload['hub-requirements.txt']=b'fastapi>=0.115,<1\nuvicorn[standard]>=0.30,<1\npydantic>=2.8,<3\nhttpx>=0.27,<1\nPillow>=10.4,<13\ncryptography>=44,<52\n'
    manifest={'version':'0.5.2-1.44','build':44,'component_commit':BASE_COMMIT,'updater_commit':commit,
       'source_complete_sha256':BASE_SHA,'files':[{'path':n,'size':len(d),'sha256':hashlib.sha256(d).hexdigest()} for n,d in sorted(payload.items())]}
    entries={'payload/'+n:d for n,d in payload.items()}
    entries['payload-manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    entries['update.py']=(ROOT/'tools/update_existing_install.py').read_bytes()
    entries['Update-Windows.cmd' if platform=='windows' else 'Update-Linux.sh']=launcher
    entries['00_升级说明.txt']=b'\xef\xbb\xbf'+(ROOT/'docs/UPGRADE_0.5.2-1.44.md').read_bytes()
    for name in ['TROUBLESHOOTING.md','SETUP_QA.md','TOOLS.md','WORKFLOWS.md','REMAKE_HOTFIX.md','PUBLICATION_0.5.2-1.44.md']:
        entries['docs/'+name]=(ROOT/'docs'/name).read_bytes()
    for name in ['LICENSE','THIRD_PARTY_NOTICES.md']:entries[name]=(ROOT/name).read_bytes()
    manual={'install_root':'','plugin_dir':'','hub_home':'','hub_python':'','web_dir':'','comfyui_root':'','astrbot_python':'','comfy_python':'','backup_root':'','ports':[6185,6278,8188]}
    entries['update-plan.example.json']=(json.dumps(manual,ensure_ascii=False,indent=2)+'\n').encode()
    if platform=='windows':
        entries.update({n:d for n,d in base.items() if n.startswith('clients/windows/')})
    entries['客户端更新下载.txt']=('Windows Admin/Service 与 Android 管理端/个人端使用 build44。\n'+
       'https://github.com/kemomimicon/AstrAutoAnima/releases/tag/v0.5.2-1.44\n'+
       '关闭旧客户端后，将新版 Windows ZIP 解压到新目录运行；Android APK 按原包名和签名覆盖安装。\n').encode('utf-8-sig')
    return entries


def build(baseline,output):
    if output.resolve().is_relative_to(ROOT):raise ValueError('请在源码目录之外制包')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise ValueError('先提交并冻结源码')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    base=load_baseline(baseline);output.mkdir(parents=True,exist_ok=True);built=[]
    for platform in ['windows','linux']:
        prefix=f'AstrAutoAnima-{platform.title()}-Update-to-0.5.2-1.44'
        path=output/(prefix+'.zip')
        if path.exists():raise FileExistsError('不覆盖已有补丁包')
        entries=create_entries(base,platform,commit)
        with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name,data in sorted(entries.items()):
                info=zipfile.ZipInfo(prefix+'/'+name,TIME);info.external_attr=(0o755 if name.endswith('.sh') else 0o644)<<16
                info.compress_type=zipfile.ZIP_STORED if name.endswith('.zip') else zipfile.ZIP_DEFLATED
                archive.writestr(info,data)
        if read_zip(path.read_bytes(),True)!=entries:raise ValueError('补丁回读校验失败')
        h=hashlib.sha256(path.read_bytes()).hexdigest()
        (output/(prefix+'.sha256.txt')).write_text(h+'  '+path.name+'\n',encoding='ascii')
        built.append({'name':path.name,'size':path.stat().st_size,'sha256':h,'platform':platform,'updater_commit':commit})
        print('BUILT',path.name,path.stat().st_size,h,flush=True)
    (output/'UPDATE_SHA256SUMS.txt').write_text(''.join(r['sha256']+'  '+r['name']+'\n' for r in built),encoding='ascii')
    (output/'update-assets.json').write_text(json.dumps(built,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.baseline,a.output)
