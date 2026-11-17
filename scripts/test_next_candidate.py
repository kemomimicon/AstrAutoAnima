"""Run one recorded regression round, with private runtime fixtures isolated."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    env['PYTHONPATH']=os.pathsep.join(str(ROOT/p) for p in ('.','plugin','hub/service/src','hub/service/tests','tools'))
    commands=[('plugin',[sys.executable,'-X','utf8','-m','unittest','discover','-s',str(ROOT/'plugin/astrbot_plugin_comfy_bridge/tests'),'-q']),
              ('hub',[sys.executable,'-X','utf8','-m','unittest','discover','-s',str(ROOT/'hub/service/tests'),'-t',str(ROOT/'hub/service'),'-q']),
              ('tools',[sys.executable,'-X','utf8','-m','unittest','discover','-s',str(ROOT/'tools/tests'),'-q'])]
    rows=[]
    for name,command in commands:
        scratch=output/('isolated-'+name);scratch.mkdir()
        log=output/(name+'.log');started=time.monotonic()
        with log.open('wb') as stream:
            process=subprocess.run(command,cwd=scratch,env=env,stdout=stream,stderr=subprocess.STDOUT)
        row={'suite':name,'exit_code':process.returncode,'seconds':round(time.monotonic()-started,2),'log':log.name}
        rows.append(row)
        print(json.dumps(row),flush=True)
        if process.returncode:print(log.read_text('utf-8',errors='replace')[-9000:],flush=True)
    result={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'suites':rows,'passed':all(r['exit_code']==0 for r in rows)}
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return 0 if result['passed'] else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    raise SystemExit(run(p.parse_args().output))
