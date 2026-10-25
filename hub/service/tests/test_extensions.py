import json
import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from astr_auto_anima_hub.config import Settings
from astr_auto_anima_hub.extensions import registry, contained, router


class ExtensionDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def package(self):
        package = self.root / 'packages/anima-lora-studio/0.1.0'
        (package / 'web').mkdir(parents=True)
        (package / 'web/index.html').write_text('Mock only')
        (package / 'LICENSE').write_text('Mock license, not Studio distribution')
        (package / 'SOURCE.json').write_text('{}')
        manifest = dict(schema_version=1, id='anima-lora-studio', name='炼丹炉',
            description='Mock', version='0.1.0', publisher='test', type='proxied_web',
            compatibility=dict(hub='>=0.5.0b3', client='>=0.5.0b3', studio='>=0.25.0'),
            navigation=dict(group='standalone', label='炼丹炉', icon='science'),
            web=dict(root='web', index='index.html', base_path='/extensions/anima-lora-studio/'),
            proxy=dict(upstream_setting='anima_studio_upstream', allowed_upstream_host='127.0.0.1',
                path_prefixes=['/api/', '/samples/'], sse_paths=['/api/events']),
            health=dict(path='/api/health'), licenses=[dict(name='Mock', path='LICENSE', source='SOURCE.json')])
        (package/'manifest.json').write_text(json.dumps(manifest))
        (self.root/'active.json').write_text(json.dumps(dict(schema_version=1,
            extensions={'anima-lora-studio': dict(version='0.1.0', enabled=True)})))
        return package, manifest

    def test_empty_registry_no_creation(self):
        self.assertEqual(registry(self.root)['extensions'], [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_valid_connector_is_not_claimed_runnable(self):
        self.package()
        row = registry(self.root)['extensions'][0]
        self.assertTrue(row['enabled'])
        self.assertEqual(row['navigation']['group'], 'standalone')
        self.assertEqual(row['state'], 'host_pending')
        self.assertFalse(row['ui']['launch_available'])
        self.assertNotIn(str(self.root), str(row))

    def test_manifest_external_host_and_unknown_fields_rejected(self):
        package, manifest = self.package()
        for field, value in [('command', 'run something'), ('url', 'https://example.org')]:
            bad = dict(manifest, **{field: value})
            (package/'manifest.json').write_text(json.dumps(bad))
            self.assertEqual(registry(self.root)['extensions'][0]['state'], 'broken_package')
        manifest['proxy']['allowed_upstream_host'] = '169.254.169.254'
        (package/'manifest.json').write_text(json.dumps(manifest))
        self.assertFalse(registry(self.root)['extensions'][0]['enabled'])

    def test_traversal_rejected(self):
        for value in ['../secret', '/etc/passwd', 'C:/secret', r'web\..\secret']:
            with self.assertRaises(ValueError):
                contained(self.root, value)

    def test_malformed_registry_does_not_break_discovery(self):
        (self.root/'active.json').write_text('{broken')
        self.assertEqual(registry(self.root)['discovery_state'], 'broken_registry')

    def test_admin_only_and_status(self):
        self.package()
        app = FastAPI()
        app.state.settings = Settings(admin_token='a'*32, lite_token='b'*32, extensions_override=self.root)
        app.include_router(router)
        with TestClient(app) as client:
            for headers in [{}, {'Authorization': 'Bearer ' + 'b'*32}]:
                self.assertEqual(client.get('/api/v1/admin/extensions', headers=headers).status_code, 401)
            headers = {'Authorization': 'Bearer ' + 'a'*32}
            self.assertEqual(client.get('/api/v1/admin/extensions', headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/v1/admin/extensions/anima-lora-studio/status', headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/v1/admin/extensions/unknown/status', headers=headers).status_code, 404)
