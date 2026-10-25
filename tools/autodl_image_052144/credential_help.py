"""Read-only, explicit credential display; no password reset, rotation or implicit export."""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import re
import sys

ROOT=Path('/root/autodl-tmp/aaa-install')
NAPCAT=Path('/root/autodl-tmp/aaa-install/napcat-config/webui.json')
PROFILES={'default':'runtime-env.json','full':'runtime-env.full.json','local':'runtime-env.local.json'}
LABELS={'hub':'Hub管理员令牌 → 管理端','astrbot-api':'AstrBot完整OpenAPI Key → Hub配置',
        'napcat':'NapCat WebUI Token → 6099登录','initial':'镜像初始账号密码（不是改密后的密码）',
        'astrbot-initial':'首次密码恢复查询（校验当前摘要，不是密码重置）','onebot':'OneBot连接Token（两端一致）'}


def no_links(path):
    for part in (path,*path.parents):
        if part.is_symlink():raise ValueError('符号链接路径被拒绝')


def read(path):
    no_links(path)
    if not path.is_file() or path.stat().st_size>1024**2:raise ValueError('文件缺失或大小异常')
    try:value=json.loads(path.read_text('utf-8-sig'))
    except (ValueError,UnicodeError):raise ValueError('JSON/编码不正确；未输出源内容') from None
    if not isinstance(value,dict):raise ValueError('配置必须为对象')
    return value


def value(config,key):
    found=config.get(key,'')
    if not isinstance(found,str) or len(found)>8192 or any(ord(c)<32 or ord(c)==127 for c in found):
        raise ValueError('字段格式异常；未输出值')
    return found


def matches_password(encoded,candidate):
    if not isinstance(encoded,str) or not isinstance(candidate,str):return False
    if re.fullmatch('[a-fA-F0-9]{32}',encoded):return hmac.compare_digest(encoded.lower(),hashlib.md5(candidate.encode()).hexdigest())
    try:
        name,iterations,salt,digest=encoded.split('$')
        if name!='pbkdf2_sha256' or not iterations.isdigit() or not 1<=int(iterations)<=1000000:return False
        if not re.fullmatch('[a-fA-F0-9]{32}',salt) or not re.fullmatch('[a-fA-F0-9]{64}',digest):return False
        actual=hashlib.pbkdf2_hmac('sha256',candidate.encode(),bytes.fromhex(salt),int(iterations)).hex()
        return hmac.compare_digest(actual,digest.lower())
    except (ValueError,OverflowError):return False


def initial_password(root,record_only=False):
    dashboard=read(root/'astrbot/data/cmd_config.json').get('dashboard',{})
    if not isinstance(dashboard,dict):raise ValueError('后台配置格式异常')
    if dashboard.get('password_change_required') is not True:
        raise ValueError('后台已经改密或没有首次改密标记，不能从摘要还原当前密码；请用本人保存的密码或匹配版本的重置流程')
    stored=dashboard.get('pbkdf2_password') or dashboard.get('password')
    candidates=[];record=root/'INITIAL_CREDENTIALS.json'
    if record.is_file():candidates.append(value(read(record),'astrbot_initial_password'))
    if not record_only:
        log=root/'AstrBot.log';no_links(log)
        if log.is_file():
            with log.open('rb') as stream:
                stream.seek(max(0,log.stat().st_size-2*1024**2));text=stream.read().decode('utf-8',errors='replace')
            for line in reversed(text.splitlines()):
                line=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',line)
                match=re.search(r'(?:Initial password|初始密码)\s*[:：]\s*([^\s]{1,256})',line,re.I)
                if match:candidates.append(match.group(1))
    for candidate in candidates[:30]:
        if candidate and matches_password(stored,candidate):
            return '用户名：'+value(dashboard,'username')+'\n初始密码：'+candidate
    raise ValueError('未找到与当前摘要匹配的初始密码；不会把旧日志密码冒充当前密码，也不会重置')


def onebot(root,bot_id):
    config=read(root/'astrbot/data/cmd_config.json');rows=config.get('platform',[])
    if not isinstance(rows,list):raise ValueError('平台配置格式异常')
    rows=[row for row in rows if isinstance(row,dict) and row.get('type')=='aiocqhttp' and (not bot_id or str(row.get('id',''))==bot_id)]
    if len(rows)>1:raise ValueError('有多个OneBot适配器，请用 --bot-id 精确选择；未显示任何Token')
    if len(rows)==1:
        token=value(rows[0],'ws_reverse_token')
        if not token:raise ValueError('所选OneBot未设置Token；请在两端设置一致的新Token，不要关闭鉴权排错')
        return '平台ID：'+value(rows[0],'id')+'\n保存的OneBot Token：'+token
    record=root/'INITIAL_CREDENTIALS.json'
    if not bot_id and record.is_file():
        pending=value(read(record),'onebot_token_pending_manual_setup')
        if pending:return '尚未配置实际OneBot适配器；下面只是待手动填入两端的初始值：\n'+pending
    raise ValueError('没有匹配的OneBot适配器，请先创建或核对 --bot-id；不猜账号/平台')


def selected(args):
    if args.show in ['initial','astrbot-initial']:
        return initial_password(args.root,record_only=args.show=='initial')
    if args.show=='onebot':return onebot(args.root,args.bot_id)
    path=args.napcat_config if args.show=='napcat' else args.root/PROFILES[args.profile]
    key={'hub':'AAH_ADMIN_TOKEN','astrbot-api':'AAH_ASTRBOT_API_KEY','napcat':'token'}[args.show]
    found=value(read(path),key)
    if not found:raise ValueError('该项未配置；未生成新凭据')
    return found


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--profile',choices=PROFILES,default='full');p.add_argument('--napcat-config',type=Path,default=NAPCAT);p.add_argument('--show',choices=LABELS);p.add_argument('--bot-id',default='');a=p.parse_args(argv)
    print('只读查询：不生成、不重置、不更新、不删除任何凭据。录屏/共享屏幕时不要显示。')
    if not a.show:
        for role,key in [('hub','AAH_ADMIN_TOKEN'),('astrbot-api','AAH_ASTRBOT_API_KEY'),('napcat','token')]:
            try:
                path=a.napcat_config if role=='napcat' else a.root/PROFILES[a.profile]
                status='已保存，隐藏' if value(read(path),key) else '未配置'
            except (OSError,ValueError):status='无法读取，请核对路径/权限/格式'
            print(role,LABELS[role],status)
        print('可选 --show initial / astrbot-initial / onebot；不同模式令牌以实际启动配置为准。')
        print('普通用户令牌若仅存哈希不能还原，需管理员换发。SSH密码请从自己的AutoDL控制台领取。')
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise ValueError('拒绝管道和重定向显示，需交互终端')
    # Read before confirmation so invalid/stale records never invite an unsafe reveal.
    found=selected(a)
    print('将显示：',LABELS[a.show])
    print('仅保存的配置，不保证未重启服务已生效；请停止录屏并准备私密保存。')
    if input('确认请输入 SHOW，其他输入取消：').strip()!='SHOW':print('已取消，未显示。');return 0
    print(found)
    print('删除文本不会撤销凭据；泄露需在对应服务换发/撤销。初始密码登录后及时修改。')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except ValueError as e:raise SystemExit('已停止：'+str(e))
    except (OSError,EOFError):raise SystemExit('已停止：检查路径、权限和交互终端；未输出完整配置。')
