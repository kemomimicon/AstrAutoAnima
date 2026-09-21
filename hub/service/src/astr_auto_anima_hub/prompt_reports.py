"""Private moderation inbox: user-owned image evidence, admin-only decisions."""
import json
import sqlite3
import time
import uuid
import re
from pathlib import Path
from contextlib import contextmanager
from .repositories import RepositoryError, file_revision
from .prompt_likes import ensure_kp_pool, _kp_entry
from .storage import mutate_json


class PromptReports:
    def __init__(self, settings, jobs):
        self.settings, self.jobs = settings, jobs
        self.root = settings.hub_state_dir / 'prompt_reports'

    @contextmanager
    def connect(self):
        # Importing the ASGI app must not create files or require write access.
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.root / 'reports.sqlite3', timeout=15)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, owner TEXT, job TEXT, image TEXT, prompt_id TEXT, snapshot TEXT, status TEXT, created REAL, UNIQUE(owner,job,image))')
                yield db
        finally:
            db.close()

    def submit(self, job_id, image_id, principal):
        job = self.jobs.get(job_id, principal)
        located = self.jobs.get_image(job_id, image_id, principal)
        if job is None or located is None:
            raise RepositoryError('图片不存在或无权访问')
        prompt_id = getattr(located[0], 'prompt_id', '')
        if not prompt_id and len(job.prompt_ids) == 1:
            prompt_id = job.prompt_ids[0]
        source = {'id': prompt_id, 'prompt': '未能取得可靠的词库条目，仅供图片与任务审核'}
        if prompt_id:
            try:
                source = _kp_entry(ensure_kp_pool(self.settings) if prompt_id.startswith('kp-') else self.settings.prompt_pool_path, prompt_id)
            except RepositoryError:
                pass  # Removed entries must not prevent image evidence submission.
        # Prefer exact asset->bridge job->source entry snapshot, not a mutable pool.
        store = self.settings.plugin_data_dir / 'job_store'
        matches=[]
        for asset_path in (store/'assets').glob('img_*.json'):
            try:
                asset=json.loads(asset_path.read_text(encoding='utf-8'))
                bridge_id=str(asset.get('job_id',''))
                if asset.get('sha256') != located[0].sha256 or bridge_id not in getattr(job,'bridge_job_ids',[]): continue
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',bridge_id): continue
                record=json.loads((store/'jobs'/(bridge_id+'.json')).read_text(encoding='utf-8'))
                outputs=record.get('result',{}).get('assets',[])
                entries=record.get('input',{}).get('source_entries',[])
                if asset.get('asset_id') not in outputs: continue
                position=outputs.index(asset['asset_id'])
                if position < len(entries) and entries[position].get('id') == prompt_id:
                    matches.append(entries[position])
            except (OSError,ValueError,TypeError): continue
        if len(matches)==1:
            prompt_id=str(matches[0].get('id',''))
            source={**source,**matches[0]}
        snapshot={'prompt':source, 'command':job.command_preview,
                  'content_type':located[0].content_type, 'image_sha256':located[0].sha256}
        return self.submit_evidence(job_id, image_id, principal, prompt_id, snapshot, located[1].read_bytes())

    def submit_evidence(self, job_id, image_id, principal, prompt_id, snapshot, content):
        """Internal entry point after caller has authorized the exact image."""
        owner = f'{principal.role}:{principal.subject}'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute('SELECT id FROM reports WHERE owner=? AND job=? AND image=?',(owner,job_id,image_id)).fetchone()
            if found: return {'id':found[0], 'status':'already_reported'}
            report_id=uuid.uuid4().hex
            # Copy immutable evidence bytes; filenames are never client-provided.
            (self.root / (report_id+'.image')).write_bytes(content)
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',
                (report_id,owner,job_id,image_id,prompt_id,json.dumps(snapshot,ensure_ascii=False),'pending',time.time()))
        return {'id':report_id,'status':'pending'}

    def list(self):
        with self.connect() as db:
            rows=db.execute('SELECT id,owner,prompt_id,snapshot,status,created FROM reports ORDER BY created DESC LIMIT 500').fetchall()
        return {'items':[dict(id=r[0],owner=r[1],prompt_id=r[2],snapshot=json.loads(r[3]),status=r[4],created=r[5]) for r in rows]}

    def image(self, report_id):
        with self.connect() as db:
            row=db.execute('SELECT snapshot FROM reports WHERE id=?',(report_id,)).fetchone()
        if not row: raise RepositoryError('举报不存在')
        path=self.root/(report_id+'.image')
        if not path.is_file(): raise RepositoryError('举报图片不可用')
        self.jobs._require_approved(path.read_bytes())
        return path,json.loads(row[0])['content_type']

    def resolve(self, report_id, action, principal):
        if not principal.is_admin: raise RepositoryError('只有管理员可以处理举报')
        if action not in {'trash','dismiss'}: raise RepositoryError('无效操作')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT prompt_id,status FROM reports WHERE id=?',(report_id,)).fetchone()
            if not row: raise RepositoryError('举报不存在')
            if row[1]!='pending': return {'status':row[1]}
            if action=='trash':
                if not row[0]: raise RepositoryError('此举报没有可靠的词库编号，只能审核图片或忽略，不能停用词条')
                path=ensure_kp_pool(self.settings) if row[0].startswith('kp-') else self.settings.prompt_pool_path
                resource='kp_prompts' if row[0].startswith('kp-') else 'prompts'
                def apply(data):
                    target=next((r for r in data.get('prompts',[]) if r.get('id')==row[0]),None)
                    if target is None: raise RepositoryError('原条目已不存在')
                    data.setdefault('trash', []).append(dict(target))
                    target.update(enabled=False,trashed=True,trash_report_id=report_id)
                mutate_json(path=path,resource=resource,expected_revision=file_revision(path,resource).revision,
                    backup_root=self.settings.backup_dir,audit_path=self.settings.audit_log_path,
                    actor=f'{principal.role}:{principal.subject}',action='report_trash',target=row[0],mutate=apply)
            db.execute('UPDATE reports SET status=? WHERE id=?',(action,report_id))
        return {'status':action}
