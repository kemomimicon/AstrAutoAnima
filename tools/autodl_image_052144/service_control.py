"""Scoped Linux status/TERM only. Does not need ss, fuser, pkill or root-wide process killing."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time
import urllib.request

ROOT=Path('/root/autodl-tmp/aaa-install')
SERVICES={'hub':('hub',6278),'comfy':('ComfyUI',8188)}


def is_open(port):
    with socket.socket() as conn:
        conn.settimeout(.5)
        return conn.connect_ex(('127.0.0.1',port))==0


def identify(root,service,proc=Path('/proc')):
    folder,port=SERVICES[service];expected=root/folder;matches=[]
    if expected.is_symlink() or expected.resolve()!=expected:
        raise ValueError('Unexpected app directory/link')
    for p in proc.iterdir():
        if not p.name.isdigit() or int(p.name)<=1:continue
        try:
            if (p/'cwd').resolve(strict=True)!=expected:continue
            args=[x for x in (p/'cmdline').read_bytes().split(b'\0') if x]
            python=os.fsencode(expected/'.venv/bin/python')
            if not args or args[0]!=python:continue
            good=(args[1:3]==[b'-m',b'astr_auto_anima_hub']) if service=='hub' else (args[1:2] in ([b'main.py'],[os.fsencode(expected/'main.py')]))
            if good:matches.append((int(p.name),(p/'stat').read_text().split()[21]))
        except (FileNotFoundError,ProcessLookupError):continue
    return matches


def listener_owned(pid,port,proc=Path('/proc')):
    inodes=set()
    for name in ['tcp','tcp6']:
        table=proc/'net'/name
        if not table.exists():continue
        for line in table.read_text().splitlines()[1:]:
            fields=line.split()
            if fields[3]=='0A' and int(fields[1].split(':')[1],16)==port:inodes.add(fields[9])
    if not inodes:return False
    fd=proc/str(pid)/'fd'
    for path in fd.iterdir():
        try:
            target=os.readlink(path)
            if target.startswith('socket:[') and target[8:-1] in inodes:return True
        except FileNotFoundError:continue
    return False


def queue_empty():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:8188/queue',timeout=10) as r:
        value=json.load(r)
    if not isinstance(value,dict) or not all(k in value for k in ['queue_running','queue_pending']):
        raise ValueError('Unrecognized ComfyUI queue')
    if value['queue_running'] or value['queue_pending']:raise ValueError('ComfyUI has tasks; no signal sent')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('service',choices=SERVICES);p.add_argument('action',choices=['status','stop']);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--apply',action='store_true');p.add_argument('--confirm-idle',action='store_true');a=p.parse_args(argv)
    root=a.root.absolute();_,port=SERVICES[a.service]
    if sys.platform!='linux':raise ValueError('Linux /proc only; do not run this script in Windows PowerShell')
    if not is_open(port):print('PORT_CLOSED: already stopped; no signal sent.');return 0
    matches=identify(root,a.service)
    if len(matches)!=1 or not listener_owned(matches[0][0],port):
        raise ValueError('Cannot uniquely prove listener ownership; no signal sent')
    pid,start=matches[0];print('VERIFIED_SERVICE',a.service,'PID',pid,'port',port)
    if a.action=='status' or not a.apply:
        print('READ_ONLY. Stopping requires: stop --apply --confirm-idle');return 0
    if not a.confirm_idle:raise ValueError('Stop new requests and confirm no tasks before --confirm-idle')
    if is_open(8188):queue_empty()
    elif a.service=='comfy':raise ValueError('ComfyUI port disappeared; inspect before retrying')
    stat=(Path('/proc')/str(pid)/'stat').read_text().split()
    if stat[21]!=start:raise ValueError('PID identity changed; no signal sent')
    os.kill(pid,signal.SIGTERM)
    end=time.monotonic()+30
    while time.monotonic()<end:
        if not is_open(port):print('STOPPED_GRACEFULLY; no force kill.');return 0
        time.sleep(.5)
    raise ValueError('Not stopped after 30s; no stronger signal sent; inspect private service log')


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,IndexError,json.JSONDecodeError):
        raise SystemExit('STOPPED: no further action. Check private app path, process identity, permissions and queue; no force kill.')
