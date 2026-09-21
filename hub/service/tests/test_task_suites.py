import json
import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from astr_auto_anima_hub.auth import AuthPrincipal
from astr_auto_anima_hub.task_suites import SuiteWrite, list_suites, write_suite, delete_suite, suite_snapshot
from astr_auto_anima_hub.repositories import RepositoryError
from astr_auto_anima_hub.storage import RevisionConflict


@pytest.fixture
def settings(tmp_path):
    path = tmp_path / 'presets.json'
    path.write_text(json.dumps({'characters': {'角色': {'prompt': 'alice'}}, 'styles': {'画风': {'prompt': 'watercolor', 'loras': []}}}), encoding='utf-8')
    return SimpleNamespace(hub_state_dir=tmp_path / 'hub_state', preset_path=path,
                           personal_styles_path=tmp_path / 'personal_styles.json')


def payload(**values):
    return SuiteWrite.model_validate({'name': '套组', 'rows': [{'character': '角色', 'style': '画风'}], **values})


def test_owner_scope_revision_and_delete(settings):
    a, b = AuthPrincipal('user', 'a'), AuthPrincipal('user', 'b')
    saved = write_suite(settings, a, payload(), 'missing')
    identifier = saved['items'][0]['id']
    assert len(list_suites(settings, a)['items']) == 1
    assert not list_suites(settings, b)['items']
    with pytest.raises(RepositoryError):
        suite_snapshot(settings, b, identifier)
    with pytest.raises(RepositoryError):
        delete_suite(settings, b, identifier, saved['revision'])
    with pytest.raises(RevisionConflict):
        write_suite(settings, a, payload(name='修改'), 'missing', identifier)
    assert not delete_suite(settings, a, identifier, saved['revision'])['items']


def test_global_admin_and_frozen_snapshots(settings):
    a = AuthPrincipal('admin', 'administrator')
    u = AuthPrincipal('user', 'u')
    with pytest.raises(RepositoryError):
        write_suite(settings, u, payload(scope='global'), 'missing')
    saved = write_suite(settings, a, payload(scope='global'), 'missing')
    identifier = saved['items'][0]['id']
    assert list_suites(settings, u)['items'][0]['editable'] is False
    snap = suite_snapshot(settings, u, identifier)
    settings.preset_path.write_text('{}')
    assert snap['rows'][0]['style_snapshot']['prompt'] == 'watercolor'
    with pytest.raises(RepositoryError):
        suite_snapshot(settings, u, identifier)


@pytest.mark.parametrize('rows', [[], [{'character': '角色', 'style': '随机模式'}],
    [{'character': '角色', 'style': '__hub_personal_other_1'}],
    [{'character': '不存在', 'style': '画风'}],
    [{'character': '角色', 'style': '不存在'}]])
def test_invalid_reference_rejected(settings, rows):
    with pytest.raises((RepositoryError, ValueError)):
        write_suite(settings, AuthPrincipal('user', 'a'), payload(rows=rows), 'missing')


def test_legacy_cannot_save(settings):
    with pytest.raises(RepositoryError):
        write_suite(settings, AuthPrincipal('legacy_lite', 'shared'), payload(), 'missing')


def test_text_character_and_order(settings):
    rows = [{'character_kind': 'text', 'character': '初音未来', 'style': '画风'},
            {'character': '角色', 'style': '画风'}]
    a = AuthPrincipal('user', 'a')
    saved = write_suite(settings, a, payload(rows=rows), 'missing')
    snap = suite_snapshot(settings, a, saved['items'][0]['id'])
    assert [r['character'] for r in snap['rows']] == ['初音未来', '角色']


def test_http_crud_and_authorization(tmp_path):
    from fastapi.testclient import TestClient
    from astr_auto_anima_hub.config import Settings
    from astr_auto_anima_hub.app import create_app
    config = Settings(plugin_data_dir=tmp_path, admin_token='a'*32, lite_token='b'*32)
    config.preset_path.write_text(json.dumps({'characters': {'角色': {'prompt': 'alice'}}, 'styles': {'画风': {'prompt': 'watercolor'}}}), encoding='utf-8')
    client = TestClient(create_app(config))
    url = '/api/v1/lite/task-suites'
    admin = {'Authorization': 'Bearer ' + 'a'*32, 'If-Match': 'missing'}
    assert client.get(url).status_code == 401
    result = client.post(url, headers=admin, json=payload(scope='global').model_dump())
    assert result.status_code == 200, result.text
    data = result.json()
    identifier = data['items'][0]['id']
    public = client.get(url, headers={'Authorization': 'Bearer ' + 'b'*32}).json()
    assert public['items'][0]['id'] == identifier
    assert not public['items'][0]['editable']
    assert client.put(url+'/'+identifier, headers=admin, json=payload().model_dump()).status_code == 409
    assert client.delete(url+'/'+identifier, headers={**admin, 'If-Match': data['revision']}).status_code == 200
    client.close()


def test_submission_freezes_overrides_and_owner_cancel(tmp_path):
    from astr_auto_anima_hub.config import Settings
    from astr_auto_anima_hub.remote_jobs import RemoteJobManager, RemoteJobError
    from astr_auto_anima_hub.schemas import RemoteJobCreateRequest
    config = Settings(plugin_data_dir=tmp_path, astrbot_api_key='test')
    config.preset_path.write_text(json.dumps({'characters': {'角色': {'prompt': 'alice'}}, 'styles': {'画风': {'prompt': 'watercolor'}}}), encoding='utf-8')
    config.delivery_targets_path.parent.mkdir(parents=True, exist_ok=True)
    config.delivery_targets_path.write_text(json.dumps({'targets': [{'id': 'test', 'label': 'test', 'kind': 'group', 'umo': 'bot:GroupMessage:12345', 'allow_safety': ['N']}]}))
    user = AuthPrincipal('user', 'alice', qq='123456')
    suite = write_suite(config, user, payload(), 'missing')['items'][0]
    async def check():
        manager = RemoteJobManager(config)
        manager._run = AsyncMock()
        job = manager.create(RemoteJobCreateRequest(target_id='test', kind='direct', prompt='rain', task_suite_id=suite['id'], character='ignored', style='随机模式', personal_style_slot=3), user)
        assert job.task_suite_id and job.task_suite_name == '套组'
        current = manager.get(job.id, user)
        assert current.task_suite_rows[0]['character'] == '角色'
        with pytest.raises(RemoteJobError):
            manager.cancel_suite(job.id, AuthPrincipal('user', 'bob'))
        manager.cancel_suite(job.id, user)
        await asyncio.sleep(0)
        command = manager._run.call_args.args[1]
        assert '__hub_suite_' in command and 'ignored' not in command and '随机模式' not in command
        await manager.shutdown()
    asyncio.run(check())


def test_suite_image_remake_uses_row_job_and_blank_ratio(tmp_path):
    from astr_auto_anima_hub.config import Settings
    from astr_auto_anima_hub.remote_jobs import RemoteJobManager
    from astr_auto_anima_hub.schemas import RemakeOptions
    settings = Settings(plugin_data_dir=tmp_path)
    manager = RemoteJobManager(settings)
    digest = 'a'*64
    original = SimpleNamespace(bridge_job_ids=['job_1', 'job_2'], task_suite_rows=[{'index': 2, 'job_id': 'job_2'}], target_id='test', safety_code='N', deliver_to_im=False)
    image = SimpleNamespace(sha256=digest, task_suite_index=2)
    manager.get = lambda *args: original
    manager.get_image = lambda *args: (image, None)
    manager.create = lambda payload, principal: payload
    assets = tmp_path / 'job_store/assets'
    assets.mkdir(parents=True)
    for number in (1, 2):
        (assets / f'img_{number}.json').write_text(json.dumps({'sha256': digest, 'job_id': f'job_{number}', 'type': 'result', 'asset_id': f'img_{number}'}))
    payload = manager.remake_image('run', 'image', AuthPrincipal('user', 'a'), RemakeOptions(task_suite_id='c'*32))
    assert payload.ratio == '' and payload.task_suite_id == 'c'*32
    ticket = next((settings.hub_state_dir / 'image_actions').glob('*.json'))
    assert json.loads(ticket.read_text())['asset_id'] == 'img_2'


def test_identical_images_are_distinct_suite_rows(tmp_path):
    from astr_auto_anima_hub.config import Settings
    from astr_auto_anima_hub.remote_jobs import RemoteJobManager
    from PIL import Image
    import io
    manager = RemoteJobManager(Settings(plugin_data_dir=tmp_path))
    raw = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(raw, format='PNG')
    manager._suite_image_index['test'] = 1
    a = manager._store_media_bytes('test', raw.getvalue(), 'test.png', 'image/png')
    manager._suite_image_index['test'] = 2
    b = manager._store_media_bytes('test', raw.getvalue(), 'test.png', 'image/png')
    assert a.sha256 == b.sha256 and a.id != b.id
    assert a.task_suite_index == 1 and b.task_suite_index == 2
