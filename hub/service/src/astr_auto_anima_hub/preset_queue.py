"""Durable, idempotent preset submissions; compare only the edited item."""
import json
import sqlite3
import threading
import time
from contextlib import closing
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .management import write_preset, delete_preset, _preset_value
from .preset_lock import preset_file_lock
from .repositories import RepositoryError, list_presets, read_json_object
from .schemas import PresetSummary, PresetWriteRequest
from .storage import _write_lock


class PresetSubmission(BaseModel):
    request_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    action: Literal['create', 'update', 'delete']
    kind: Literal['character', 'style']
    original_name: str = Field(default='', max_length=200)
    expected: PresetSummary | None = None
    value: PresetWriteRequest | None = None

    @model_validator(mode='after')
    def check(self):
        if self.action != 'delete' and self.value is None:
            raise ValueError('缺少预设内容')
        if self.action != 'create' and (not self.expected or self.expected.name != self.original_name or self.expected.kind != self.kind):
            raise ValueError('缺少原条目快照，不能覆盖未读取的预设')
        return self


class PresetQueue:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.hub_state_dir / 'preset_submissions.sqlite3'
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.guard = threading.Lock()
        self.thread = None

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, actor TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL DEFAULT "", created REAL NOT NULL, result TEXT)')
        return db

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                return
            self.stopping.clear()
            self.thread = threading.Thread(target=self.loop, name='preset-submissions', daemon=True)
            self.thread.start()

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=20)

    def submit(self, request, actor):
        payload = request.model_dump_json()
        with closing(self.connect()) as db, db:
            row = db.execute('SELECT payload,actor FROM submissions WHERE id=?', (request.request_id,)).fetchone()
            if row and (row['payload'] != payload or row['actor'] != actor):
                raise RepositoryError('提交编号已用于另一份内容，不能重复覆盖')
            if not row:
                if db.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued','running')").fetchone()[0] >= 200:
                    raise RepositoryError('预设提交队列已满，请稍后再试')
                db.execute('INSERT INTO submissions(id,payload,actor,status,created) VALUES(?,?,?,?,?)',
                           (request.request_id, payload, actor, 'queued', time.time()))
        self.start()
        self.wake.set()
        return self.get(request.request_id)

    def get(self, identifier):
        with closing(self.connect()) as db:
            row = db.execute('SELECT id,status,message,result FROM submissions WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise RepositoryError('找不到预设提交记录')
            return {**dict(row), 'result': json.loads(row['result']) if row['result'] else None}

    def perform(self, request, actor):
        # Same order as legacy mutate_json: process mutex, then OS file lock.
        with _write_lock, preset_file_lock(self.settings.preset_path):
            current = list_presets(self.settings.preset_path)
            rows = current.styles if request.kind == 'style' else current.characters
            name = request.value.name.strip() if request.value else request.original_name
            target_name = request.original_name if request.action != 'create' else name
            target = next((row for row in rows if row.name == target_name), None)
            raw = read_json_object(self.settings.preset_path) if self.settings.preset_path.is_file() else {}
            collection = raw.get('styles' if request.kind == 'style' else 'characters', {})
            if request.value:
                desired = _preset_value(request.kind, request.value)
                if collection.get(name) == desired and (name == target_name or target is None):
                    return {'action': 'updated', 'resource': f'{request.kind}:{name}', 'revision': current.revision, 'backup': None}
            elif target is None and target_name not in collection:
                return {'action': 'deleted', 'resource': f'{request.kind}:{target_name}', 'revision': current.revision, 'backup': None}
            if request.action == 'create':
                if target_name in collection:
                    raise RepositoryError('同名预设已存在；未覆盖，提交内容仍保留')
            elif target != request.expected:
                raise RepositoryError('这条预设本身已变化；未覆盖，提交内容仍保留，请核对差异')
            try:
                if request.action == 'delete':
                    return delete_preset(self.settings, request.kind, target_name, current.revision, actor).model_dump()
                return write_preset(self.settings, request.kind, request.value, current.revision, actor,
                                    previous_name=None if request.action == 'create' else target_name).model_dump()
            except RepositoryError as exc:
                # mutate_json may fail at the secondary audit write AFTER the
                # preset replacement. Confirm committed data under the lock;
                # do not misreport failure or write a second backup.
                latest = read_json_object(self.settings.preset_path)
                items = latest.get('styles' if request.kind == 'style' else 'characters', {})
                applied = target_name not in items if request.action == 'delete' else (
                    items.get(name) == desired and (name == target_name or target_name not in items))
                if not applied:
                    raise
                import logging
                logging.getLogger(__name__).warning('Preset committed; secondary write failed: %s', exc)
                return {'action': 'deleted' if request.action == 'delete' else 'updated',
                        'resource': f'{request.kind}:{name}',
                        'revision': list_presets(self.settings.preset_path).revision,
                        'backup': None, 'audit_warning': str(exc)[:300]}

    def drain_once(self):
        # One writer even if a second Hub accidentally shares this data directory.
        with preset_file_lock(self.path):
            with closing(self.connect()) as db, db:
                row = db.execute("SELECT * FROM submissions WHERE status IN ('queued','running') ORDER BY created,id LIMIT 1").fetchone()
                if row is None:
                    return False
                db.execute("UPDATE submissions SET status='running' WHERE id=?", (row['id'],))
            try:
                result = self.perform(PresetSubmission.model_validate_json(row['payload']), row['actor'])
                state, message = 'succeeded', ('已保存并确认（审计写入异常，请检查日志）' if result.get('audit_warning') else '已保存并确认')
            except Exception as exc:
                result = None
                state = 'conflict' if isinstance(exc, RepositoryError) else 'failed'
                message = str(exc)[:600]
            with closing(self.connect()) as db, db:
                db.execute('UPDATE submissions SET status=?,message=?,result=? WHERE id=?',
                           (state, message, json.dumps(result, ensure_ascii=False) if result else None, row['id']))
            return True

    def loop(self):
        while not self.stopping.is_set():
            try:
                if self.drain_once():
                    continue
            except (OSError, sqlite3.Error):
                # Keep queued content durable if disk/lock is temporarily unavailable.
                pass
            self.wake.wait(30)
            self.wake.clear()
