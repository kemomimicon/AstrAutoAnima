import os
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_comfy_bridge.cleanup_runtime import cleanup_old_output_images


class CleanupRuntimeTests(unittest.TestCase):
    def test_deletes_only_expired_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_image = root / "old.png"
            fresh_image = root / "fresh.webp"
            old_json = root / "record.json"

            old_image.write_bytes(b"old-image")
            fresh_image.write_bytes(b"fresh-image")
            old_json.write_text("{}", encoding="utf-8")

            now = 2_000_000.0
            old_time = now - 49 * 3600
            os.utime(old_image, (old_time, old_time))
            os.utime(old_json, (old_time, old_time))
            os.utime(fresh_image, (now, now))

            report = cleanup_old_output_images(root, 48, now=now)

            self.assertEqual(report.scanned, 2)
            self.assertEqual(report.deleted, 1)
            self.assertEqual(report.deleted_bytes, len(b"old-image"))
            self.assertTrue(fresh_image.exists())
            self.assertTrue(old_json.exists())
            self.assertFalse(old_image.exists())

    def test_ignores_symlinks_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.png"
            link = root / "link.png"
            target.write_bytes(b"image")
            old_time = 9_999_999.0 - 49 * 3600
            os.utime(target, (old_time, old_time))
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available")

            report = cleanup_old_output_images(root, 1, now=9_999_999.0)

            self.assertEqual(report.deleted, 1)
            self.assertTrue(link.is_symlink())

    def test_missing_directory_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            report = cleanup_old_output_images(missing, 48)
            self.assertEqual(report.scanned, 0)
            self.assertEqual(report.deleted, 0)

    def test_old_one_hour_setting_still_protects_recent_two_days(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recent = root / '36-hours.png'
            expired = root / '49-hours.png'
            for path, hours in ((recent, 36), (expired, 49)):
                path.write_bytes(b'synthetic image')
                os.utime(path, (2_000_000-hours*3600, 2_000_000-hours*3600))
            report = cleanup_old_output_images(root, 1, now=2_000_000)
            self.assertEqual(report.deleted, 1)
            self.assertTrue(recent.exists())
            self.assertFalse(expired.exists())

    def test_job_records_fail_closed_for_active_or_unreadable_state(self):
        from astrbot_plugin_comfy_bridge.cleanup_runtime import require_idle_job_records
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = root / 'task.json'
            for contents in ('{"status":"queued"}', '{"status":"running"}',
                             '{"status":"unknown"}', '{}', 'not-json'):
                item.write_text(contents)
                with self.assertRaises(ValueError):
                    require_idle_job_records(root)
            item.write_text('{"status":"completed"}')
            require_idle_job_records(root)
            with self.assertRaises(ValueError):
                require_idle_job_records(item)

    def test_schema_defaults_off_and_runtime_clamps_legacy_value(self):
        import json
        from types import SimpleNamespace
        from test_remake_inheritance import bind
        root = Path(__file__).parents[1]
        config = json.loads((root / '_conf_schema.json').read_text('utf-8-sig'))
        self.assertIs(config['output_cleanup_enabled']['default'], False)
        owner = SimpleNamespace(config={'output_retention_hours': 1})
        self.assertEqual(bind('_output_retention_hours', owner)(), 48)

    def test_cleanup_checks_queue_before_deleting(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock
        from test_remake_inheritance import bind
        from astrbot_plugin_comfy_bridge.cleanup_runtime import CleanupReport, require_idle_job_records

        class Context:
            def __init__(self, value):
                self.value = value
            async def __aenter__(self):
                return self.value
            async def __aexit__(self, *args):
                pass

        async def check():
            with tempfile.TemporaryDirectory() as directory:
                queue = AsyncMock()
                response = SimpleNamespace(raise_for_status=Mock(), json=queue)
                session = SimpleNamespace(get=lambda url: Context(response))
                client = SimpleNamespace(ClientTimeout=lambda **kw: None,
                                         ClientSession=lambda **kw: Context(session))
                cleanup = Mock(return_value=CleanupReport(0, 0, 0, 0))
                owner = SimpleNamespace(_job_store=lambda: SimpleNamespace(jobs_dir=Path(directory)),
                                        _base_url=lambda: 'http://local-test',
                                        config={'output_dir': str(Path(directory) / 'not-created')},
                                        _output_dir=Mock(side_effect=AssertionError('must not resolve or mkdir')),
                                        _output_retention_hours=lambda: 48)
                method = bind('_cleanup_plugin_outputs', owner, aiohttp=client, asyncio=asyncio,
                              Path=Path,
                              CleanupReport=CleanupReport, require_idle_job_records=require_idle_job_records,
                              cleanup_old_output_images=cleanup)
                for result in ({}, {'queue_running': None, 'queue_pending': []},
                               {'queue_running': [1], 'queue_pending': []}):
                    queue.return_value = result
                    with self.assertRaises(ValueError):
                        await method()
                    cleanup.assert_not_called()
                queue.side_effect = TimeoutError('unreachable')
                with self.assertRaises(TimeoutError):
                    await method()
                cleanup.assert_not_called()
                queue.side_effect = None
                queue.return_value = {'queue_running': [], 'queue_pending': []}
                await method()
                cleanup.assert_called_once()
                self.assertEqual(cleanup.call_args.args[0], Path(directory) / 'not-created')
                self.assertFalse((Path(directory) / 'not-created').exists())
                owner._output_dir.assert_not_called()
        asyncio.run(check())

    def test_directory_link_is_not_followed_for_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / 'original'
            outside.mkdir()
            image = outside / 'old.png'
            image.write_bytes(b'image')
            os.utime(image, (1, 1))
            alias = root / 'alias'
            try:
                alias.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('directory symlinks are not available')
            report = cleanup_old_output_images(alias, 48, now=2_000_000)
            self.assertEqual(report.deleted, 0)
            self.assertTrue(image.exists())


if __name__ == "__main__":
    unittest.main()
