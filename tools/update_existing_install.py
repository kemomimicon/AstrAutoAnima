"""Offline-first, preserving-data updater for existing AAA source installations."""
from __future__ import annotations
import argparse
import ast
from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import queue
from datetime import datetime
from urllib.parse import urlsplit

VERSION='0.5.2-1.44'
PAYLOAD=Path(__file__).resolve().parent/'payload'
HUB_REQUIREMENTS=[('fastapi','fastapi',(0,115),(1,)),('uvicorn','uvicorn',(0,30),(1,)),
 ('pydantic','pydantic',(2,8),(3,)),('httpx','httpx',(0,27),(1,)),
 ('PIL','Pillow',(10,4),(13,)),('cryptography','cryptography',(44,),(52,))]


@dataclass
class Plan:
    install_root: str=''
    plugin_dir: str=''
    hub_home: str=''
    hub_python: str=''
    web_dir: str=''
    comfyui_root: str=''
    astrbot_python: str=''
    comfy_python: str=''
    backup_root: str=''
    ports: tuple=(6185,6278,8188)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def safe(raw):
    if not str(raw).strip() or any(c in str(raw) for c in '\x00\r\n'):
        raise ValueError('路径为空或含换行')
    p=Path(raw).expanduser().absolute()
    if '..' in p.parts:raise ValueError('请选择规范的绝对路径，不要包含上级目录跳转')
    if p==Path(p.anchor) or p==Path.home():raise ValueError('不能把磁盘根或整个用户目录作为更新目标')
    for q in (p,*p.parents):
        try:s=q.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
            raise ValueError('更新目标含符号链接或目录联接：'+str(q))
    return p


def tree(root):
    root=safe(root)
    if not root.is_dir():raise ValueError('目录不存在：'+str(root))
    stack=[root]
    while stack:
        for p in sorted(stack.pop().iterdir()):
            safe(p)
            if p.is_dir():stack.append(p)
            elif p.is_file():yield p
            else:raise ValueError('范围内有特殊文件')


def read_json(p):
    p=safe(p)
    if not p.is_file() or p.stat().st_size>16*1024*1024:raise ValueError('配置文件缺失或过大：'+p.name)
    d=json.loads(p.read_text('utf-8-sig'))
    if not isinstance(d,dict):raise ValueError('配置不是 JSON 对象')
    return d


def write_atomic(path,data,mode=0o644):
    path=safe(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.aaa-update-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(name,mode);safe(path);os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()


def save(path,value):write_atomic(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode(),0o600)


def check_preserved_auth(env):
    admin=env.get('AAH_ADMIN_TOKEN','');lite=env.get('AAH_LITE_TOKEN','')
    if not isinstance(admin,str) or len(admin)<32:
        raise ValueError('旧 Hub 管理员令牌不符合新版至少 32 字符的要求，请本人先调整；更新器不会改密钥')
    if lite and (not isinstance(lite,str) or len(lite)<32 or lite==admin):
        raise ValueError('旧个人令牌不符合新版长度或独立性要求，请本人先处理；更新器不会改密钥')


def managed(root):
    root=safe(root);env=read_json(root/'runtime-env.json')
    if not (root/'.aaa-managed-install').is_file():raise ValueError('缺少懒人包安装标记，请使用手动路径计划')
    services=json.loads(safe(root/'services.json').read_text('utf-8-sig'))
    if not isinstance(services,list):raise ValueError('services.json 格式错误')
    hub=next((s for s in services if s.get('name')=='Hub'),None)
    if not hub or not hub.get('command'):raise ValueError('找不到 Hub 启动记录，请使用手动计划')
    home=safe(hub['cwd']);ports={6278}
    for s in services:
        if isinstance(s.get('port'),int):ports.add(s['port'])
    for path in root.glob('services.*.json'):
        extra=json.loads(safe(path).read_text('utf-8-sig'))
        if not isinstance(extra,list):raise ValueError('服务档位记录格式错误')
        for s in extra:
            if isinstance(s.get('port'),int):ports.add(s['port'])
    for key in ('AAH_ASTRBOT_URL','AAH_COMFYUI_URL'):
        u=urlsplit(str(env.get(key,'')))
        if u.hostname in ('localhost','127.0.0.1','::1') and u.port:ports.add(u.port)
    plugin='' if env.get('AAH_EXECUTION_MODE')=='local' else str(env.get('AAH_PLUGIN_DIR',''))
    def interpreter(name):
        s=next((s for s in services if s.get('name')==name),{})
        if s.get('mode')=='desktop':return ''
        command=s.get('command',[])
        if not command:return ''
        p=Path(command[0])
        if name=='AstrBot':
            p=p.parent/('python.exe' if os.name=='nt' else 'python')
        return str(p) if p.is_file() else ''
    return Plan(str(root),plugin,str(home),str(hub['command'][0]),
        str(env.get('AAH_WEB_ROOT') or home/'web'),str(env.get('AAH_COMFYUI_ROOT','')),
        interpreter('AstrBot'),interpreter('ComfyUI'),str(root/'aaa_update_backups'),tuple(sorted(ports)))


def version(path):
    text=safe(path).read_text('utf-8-sig')
    m=re.search(r'^version\s*[:=]\s*[\"\']?([0-9][0-9A-Za-z.+_-]*)',text,re.M)
    if not m:raise ValueError('无法识别现有版本：'+path.name)
    raw=m[1];core=re.match(r'(\d+)\.(\d+)\.(\d+)(.*)',raw)
    if not core:raise ValueError('版本格式不支持')
    base=tuple(int(x) for x in core.groups()[:3]);suffix=core[4].lower().split('+')[0]
    if base<(0,3,0) or base>(0,5,2):raise ValueError('版本超出本补丁升级范围：'+raw)
    if base==(0,5,2):
        beta=re.search(r'(?:beta[.-]?|b)(\d+)',suffix)
        if not beta or int(beta[1])>1:raise ValueError('现有版本更新，停止降级：'+raw)
    return raw


def idle(plan):
    for port in plan.ports:
        if type(port) is not int or not 1<=port<=65535:raise ValueError('服务端口无效')
        for address in ('127.0.0.1','::1'):
            try:c=socket.create_connection((address,port),timeout=.25)
            except OSError:continue
            c.close();raise ValueError('端口仍占用，请先正常退出相关服务：'+str(port))


def probe(python,source,requirements):
    python=Path(python).expanduser().absolute()
    if not python.is_file() or not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?(?:\.exe)?',python.name,re.I):
        raise ValueError('请选择该服务实际使用的 Python')
    code="""import importlib.util,importlib.metadata,json,re,sys
missing=[]
for module,dist,minimum,maximum in json.loads(sys.argv[2]):
 try:
  v=tuple(int(x) for x in re.match(r'(\\d+(?:\\.\\d+)*)',importlib.metadata.version(dist))[1].split('.'))
  if not importlib.util.find_spec(module) or v<tuple(minimum) or (maximum and v>=tuple(maximum)):missing.append(dist)
 except (ImportError,TypeError,KeyError):missing.append(dist)
spec=importlib.util.find_spec('astr_auto_anima_hub') if sys.argv[1] else None
print(json.dumps({'python_ok':sys.version_info>=(3,10),'origin':spec.origin if spec else '', 'missing':missing}))
"""
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME'}}
    env['PYTHONDONTWRITEBYTECODE']='1'
    p=subprocess.run([str(python),'-B','-c',code,str(source),json.dumps(requirements)],capture_output=True,text=True,
        encoding='utf-8',errors='replace',timeout=30,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode:raise ValueError('服务 Python 检查失败，请查看其环境和安装目录')
    try:d=json.loads(p.stdout)
    except ValueError:raise ValueError('服务 Python 返回了无法识别的检查结果') from None
    if not d['python_ok']:raise ValueError('当前运行环境需 Python 3.10 或以上；请先独立迁移环境')
    if source and (not d['origin'] or not Path(d['origin']).resolve().is_relative_to(Path(source).resolve())):
        raise ValueError('Hub 不是指向所选源码目录的可编辑安装，请按升级说明先核对 pip -e 路径')
    return d['missing']


def payload_files(payload):
    manifest=read_json(payload.parent/'payload-manifest.json');rows=manifest['files']
    expected={r['path']:r for r in rows}
    actual={p.relative_to(payload).as_posix():p for p in tree(payload)}
    if set(expected)!=set(actual):raise ValueError('补丁文件清单不完整')
    for name,p in actual.items():
        r=expected[name]
        if p.stat().st_size!=r['size'] or digest(p)!=r['sha256']:raise ValueError('补丁校验失败：'+name)
        if p.suffix=='.py':ast.parse(p.read_text('utf-8-sig'),filename=name)
    return actual


def prepare(plan,payload=PAYLOAD):
    files=payload_files(payload);ops=[];guards={};dependencies=[];old={};roots=[]
    def add(src,target,preserve=False):
        target=safe(target)
        if preserve and target.exists():return
        if target.exists() and not target.is_file():raise ValueError('文件目标被目录占用')
        new=digest(src)
        if target.is_file() and digest(target)==new:return
        ops.append({'source':str(src),'payload_path':src.relative_to(payload).as_posix(),'target':str(target),'new_sha256':new,'old_sha256':digest(target) if target.is_file() else None,
                    'old_mode':stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644})
    def copy_section(section,target,preserve_parts=()):
        target=safe(target);roots.append(str(target))
        source_root=safe(payload)
        if target==source_root or target.is_relative_to(source_root) or source_root.is_relative_to(target):
            raise ValueError('补丁解压目录与更新目标重叠，请把补丁放到独立目录')
        for name,p in files.items():
            if name.startswith(section+'/'):
                rel=Path(name.removeprefix(section+'/'))
                add(p,target/rel,bool(set(rel.parts)&set(preserve_parts)))
    if plan.plugin_dir:
        p=safe(plan.plugin_dir)
        if p.name!='astrbot_plugin_comfy_bridge' or not (p/'main.py').is_file():raise ValueError('不是现有 AAA 插件目录')
        old['plugin']=version(p/'metadata.yaml');copy_section('plugin',p,{'data'})
        # Existing plugin data is never overwritten; fresh defaults remain available for review.
        for name,f in files.items():
            if name.startswith('plugin/data/') and (p/Path(name.removeprefix('plugin/'))).exists():
                add(f,p/'.aaa-update-defaults'/Path(name.removeprefix('plugin/data/')),True)
        config=p.parent.parent/'config/astrbot_plugin_comfy_bridge_config.json'
        if config.is_file():guards[str(config)]=digest(config)
        if plan.astrbot_python:
            if probe(plan.astrbot_python,'',[('astrbot','astrbot',(4,17),(5,))]):
                raise ValueError('需要 AstrBot 4.17 至 4.x，请先单独核对核心版本；本补丁不替换 AstrBot')
            dependencies.append((plan.astrbot_python,'', [('aiohttp','aiohttp',(3,9),(4,)),('PIL','Pillow',(10,),(14,))],payload/'plugin/requirements.txt'))
    if plan.hub_home:
        h=safe(plan.hub_home)
        if not (h/'src/astr_auto_anima_hub').is_dir():raise ValueError('Hub 源码目录不完整')
        old['hub']=version(h/'pyproject.toml');copy_section('hub',h,{'resources','data'})
        copy_section('web',h/'web')
        if not plan.hub_python:raise ValueError('缺少 Hub Python 路径')
        dependencies.append((plan.hub_python,str(h/'src'),HUB_REQUIREMENTS,payload/'hub-requirements.txt'))
        if plan.web_dir and safe(plan.web_dir)!=h/'web':copy_section('web',safe(plan.web_dir))
        if (h/'.env').is_file():guards[str(h/'.env')]=digest(h/'.env')
    if plan.comfyui_root:
        c=safe(plan.comfyui_root)
        if not (c/'main.py').is_file():raise ValueError('ComfyUI 目录缺少 main.py')
        copy_section('node',c/'custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools')
        copy_section('workflows',c/'user/default/workflows/AAA_Update_0.5.2-1.44',{'*'})
        # Templates are add-only, including already customized templates in the update folder.
        for op in list(ops):
            if '/AAA_Update_0.5.2-1.44/' in op['target'].replace('\\','/') and op['old_sha256'] is not None:ops.remove(op)
        if plan.comfy_python:dependencies.append((plan.comfy_python,'',[('numpy','numpy',(1,),()),('PIL','Pillow',(1,),())],payload/'node/requirements.txt'))
    if not old:raise ValueError('没有选择已有插件或 Hub')
    if plan.install_root:
        root=safe(plan.install_root)
        if safe(payload).is_relative_to(root):raise ValueError('补丁请解压到原安装目录之外')
        if not (root/'runtime-env.json').is_file() or not (root/'services.json').is_file():raise ValueError('不是现有懒人包安装目录')
        roots.append(str(root))
        for p in root.glob('runtime-env*.json'):
            guards[str(safe(p))]=digest(p)
            if p.name in {'runtime-env.json','runtime-env.full.json','runtime-env.local.json'}:check_preserved_auth(read_json(p))
        for p in root.glob('services*.json'):guards[str(safe(p))]=digest(p)
        for name,p in files.items():
            if name.startswith('runtime/') and (p.suffix=='.py' or (root/Path(name).name).is_file()):
                if p.suffix=='.py' or safe(plan.hub_home)==root/'hub':add(p,root/Path(name).name)
    if len({o['target'].casefold() for o in ops})!=len(ops):raise ValueError('更新目标发生重叠')
    return {'plan':asdict(plan),'old_versions':old,'operations':ops,'guards':guards,'allowed_roots':roots},dependencies


def unchanged(state):
    for name,h in state['guards'].items():
        if digest(safe(name))!=h:raise ValueError('原配置发生变化，停止；未显示配置内容')
    for op in state['operations']:
        p=safe(op['target'])
        if (digest(p) if p.is_file() else None)!=op['old_sha256']:raise ValueError('预检后目标文件发生变化，停止')


def rollback(backup,log=print,payload=PAYLOAD):
    backup=safe(backup);state=read_json(backup/'update-state.json');plan=Plan(**state['plan']);idle(plan)
    sources=payload_files(payload)
    def allowed(op):
        name=op.get('payload_path','');p=Path(op['target']);src=sources.get(name)
        if src is None or digest(src)!=op['new_sha256']:return False
        section,rel=name.split('/',1);r=Path(rel);candidates=[]
        if section=='plugin' and plan.plugin_dir:
            base=safe(plan.plugin_dir);candidates=[base/r]
            if rel.startswith('data/'):candidates.append(base/'.aaa-update-defaults'/rel.removeprefix('data/'))
        elif section=='hub' and plan.hub_home:candidates=[safe(plan.hub_home)/r]
        elif section=='web' and plan.hub_home:
            candidates=[safe(plan.hub_home)/'web'/r]
            if plan.web_dir:candidates.append(safe(plan.web_dir)/r)
        elif section=='node' and plan.comfyui_root:candidates=[safe(plan.comfyui_root)/'custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools'/r]
        elif section=='workflows' and plan.comfyui_root:candidates=[safe(plan.comfyui_root)/'user/default/workflows/AAA_Update_0.5.2-1.44'/r]
        elif section=='runtime' and plan.install_root:candidates=[safe(plan.install_root)/r]
        return any(p==safe(c) for c in candidates)
    # All conflicts are checked before the first restore.
    for op in state['operations']:
        p=safe(op['target'])
        if not allowed(op):raise ValueError('回退目标越界或补丁来源不一致')
        current=digest(p) if p.is_file() else None
        if current not in (op['old_sha256'],op['new_sha256']):raise ValueError('升级后文件被改动，请保留备份并人工合并：'+p.name)
        if op['old_sha256']:
            old=safe(backup/op['backup_file'])
            if not old.is_relative_to(backup) or digest(old)!=op['old_sha256']:raise ValueError('回退备份校验失败')
    for op in reversed(state['operations']):
        p=safe(op['target'])
        if op['old_sha256']:write_atomic(p,(backup/op['backup_file']).read_bytes(),op['old_mode'])
        elif p.is_file():p.unlink()
    state['status']='rolled_back';save(backup/'update-state.json',state);log('代码已回退；个人配置和数据保持原值。')


def apply(plan,*,payload=PAYLOAD,confirm_stopped=False,install_dependencies=False,log=print):
    if not confirm_stopped:raise ValueError('请先正常退出 Hub、AstrBot 和 ComfyUI，再勾选已停止服务')
    state,deps=prepare(plan,payload);idle(plan);unchanged(state)
    missing=[]
    for python,source,req,reqfile in deps:
        absent=probe(python,source,req)
        if absent:missing.append((python,source,req,reqfile,absent))
    if missing and not install_dependencies:raise ValueError('需补齐服务依赖：'+', '.join(sorted({n for *_,names in missing for n in names}))+'。可勾选允许补齐依赖后再更新。')
    if not state['operations']:log('程序文件已是本次版本，无需重复覆盖。');return None
    backup_root=safe(plan.backup_root or str(Path(plan.hub_home or plan.plugin_dir).parent/'aaa_update_backups'))
    backup=backup_root/('to_0.5.2-1.44_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+secrets.token_hex(4))
    for r in state['allowed_roots']:
        if backup_root==safe(r):raise ValueError('备份目录不能等于程序目标目录')
    backup.mkdir(parents=True,exist_ok=False)
    if os.name!='nt':backup.chmod(0o700)
    for i,op in enumerate(state['operations']):
        op['backup_file']='files/'+str(i)
        if op['old_sha256']:
            old=Path(op['target']);write_atomic(backup/op['backup_file'],old.read_bytes(),0o600)
            if digest(backup/op['backup_file'])!=op['old_sha256']:raise ValueError('备份校验失败，未写程序文件')
    for i,name in enumerate(state['guards']):write_atomic(backup/'private-config-snapshots'/str(i),Path(name).read_bytes(),0o600)
    state['status']='backed_up';save(backup/'update-state.json',state);log('备份完成：'+str(backup))
    # Network access is opt-in and restricted to this project's declared dependencies.
    for python,source,req,reqfile,names in missing:
        log('正在补齐所选服务依赖：'+', '.join(names))
        result=subprocess.run([str(python),'-m','pip','install','-r',str(reqfile)],stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or probe(python,source,req):raise ValueError('依赖安装未完成，程序文件尚未覆盖；备份已保留')
    idle(plan);unchanged(state)
    try:
        state['status']='applying';save(backup/'update-state.json',state)
        for i,op in enumerate(state['operations'],1):
            source=safe(op['source'])
            if digest(source)!=op['new_sha256']:raise ValueError('补丁内容在预检后变化')
            write_atomic(op['target'],source.read_bytes(),op['old_mode'])
            if digest(op['target'])!=op['new_sha256']:raise ValueError('更新文件回读校验失败')
            if i%25==0:log(f'程序文件已更新并校验：{i}/{len(state["operations"])}')
        for name,h in state['guards'].items():
            if digest(name)!=h:raise ValueError('个人配置在更新期间被其他程序修改')
        state['status']='completed';save(backup/'update-state.json',state)
    except Exception:
        rollback(backup,log,payload);raise
    log('更新完成：0.5.2-1.44。按原方式启动服务，再更新客户端并验证首图。')
    return backup


def gui():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    app=tk.Tk();app.title('AstrAutoAnima · 旧版本升级到 0.5.2-1.44');app.geometry('900x620')
    path=tk.StringVar();stopped=tk.BooleanVar();deps=tk.BooleanVar();messages=queue.Queue();busy=False
    ttk.Label(app,text='选择已有安装目录（含 Start 与 runtime-env.json），先预检，再更新。').pack(anchor='w',padx=16,pady=12)
    row=ttk.Frame(app);row.pack(fill='x',padx=16);ttk.Entry(row,textvariable=path).pack(side='left',fill='x',expand=True)
    ttk.Button(row,text='选择目录',command=lambda:path.set(filedialog.askdirectory() or path.get())).pack(side='right')
    ttk.Checkbutton(app,text='我已正常退出 Hub、AstrBot 和 ComfyUI',variable=stopped).pack(anchor='w',padx=16,pady=8)
    ttk.Checkbutton(app,text='允许补齐此补丁所需 Python 依赖（联网；不安装 Torch 或模型）',variable=deps).pack(anchor='w',padx=16)
    output=tk.Text(app,wrap='word');output.pack(fill='both',expand=True,padx=16,pady=12)
    def log(s):messages.put(str(s))
    def start(execute):
        nonlocal busy
        if busy:return
        raw=path.get();confirmed=stopped.get();network=deps.get()
        if execute and not messagebox.askyesno('执行升级','按当前目录升级程序，并在修改前创建备份？'):return
        busy=True
        def work():
            nonlocal busy
            try:
                plan=managed(raw);state,requirements=prepare(plan);idle(plan)
                log('旧版本：'+json.dumps(state['old_versions'],ensure_ascii=False));log('待更新程序文件：'+str(len(state['operations'])))
                if execute:apply(plan,confirm_stopped=confirmed,install_dependencies=network,log=log)
                else:
                    for py,src,req,_ in requirements:
                        missing=probe(py,src,req)
                        if missing:log('需要补齐依赖：'+', '.join(missing))
                    log('预检完成；尚未修改文件或下载。')
            except Exception as e:log('停止：'+str(e))
            finally:busy=False
        threading.Thread(target=work,daemon=True).start()
    buttons=ttk.Frame(app);buttons.pack(fill='x',padx=16,pady=8)
    ttk.Button(buttons,text='只做预检',command=lambda:start(False)).pack(side='left',padx=8)
    ttk.Button(buttons,text='备份并升级',command=lambda:start(True)).pack(side='left',padx=8)
    def poll():
        while not messages.empty():output.insert('end',messages.get()+'\n');output.see('end')
        app.after(150,poll)
    def close():
        if busy:messagebox.showinfo('正在处理','请等待当前备份或更新完成。');return
        app.destroy()
    app.protocol('WM_DELETE_WINDOW',close)
    poll();app.mainloop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group();group.add_argument('--install-root',type=Path);group.add_argument('--plan',type=Path);group.add_argument('--rollback',type=Path)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--confirm-stopped',action='store_true');parser.add_argument('--install-dependencies',action='store_true');parser.add_argument('--gui',action='store_true')
    args=parser.parse_args()
    if args.gui or not any((args.install_root,args.plan,args.rollback)):
        if os.name!='nt' and not (os.getenv('DISPLAY') or os.getenv('WAYLAND_DISPLAY')):parser.print_help();return
        gui();return
    if args.rollback:
        if not args.confirm_stopped:raise ValueError('请先退出服务并加 --confirm-stopped')
        rollback(args.rollback);return
    plan=managed(args.install_root) if args.install_root else Plan(**read_json(args.plan))
    if args.apply:apply(plan,confirm_stopped=args.confirm_stopped,install_dependencies=args.install_dependencies)
    else:
        state,deps=prepare(plan);idle(plan)
        print('旧版本：',json.dumps(state['old_versions'],ensure_ascii=False));print('待更新程序文件：',len(state['operations']))
        for python,source,req,_ in deps:
            missing=probe(python,source,req)
            if missing:print('需补齐依赖：',', '.join(missing))
        print('预检完成；未修改、未下载、未启动服务。')


if __name__=='__main__':
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    try:main()
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError) as e:raise SystemExit('升级停止：'+str(e))
