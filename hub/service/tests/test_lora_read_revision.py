import unittest
from unittest.mock import patch

from . import test_kp_lora_personal as fixtures
from astr_auto_anima_hub.lora_catalog import scan_loras, update_lora
from astr_auto_anima_hub.schemas import LoraCatalogUpdateRequest
from astr_auto_anima_hub.storage import RevisionConflict


class LoraReadRevisionTests(unittest.TestCase):
    setUp = fixtures.KpLoraPersonalTests.setUp
    tearDown = fixtures.KpLoraPersonalTests.tearDown

    def test_unchanged_reads_preserve_bytes_revision_and_no_extra_backup(self):
        first = scan_loras(self.settings, 'test')
        path = self.settings.lora_catalog_path
        before = path.read_bytes(), path.stat().st_mtime_ns
        backups = sorted(self.settings.backup_dir.rglob('*'))
        audit = self.settings.audit_log_path.read_bytes()
        for _ in range(3):
            again = scan_loras(self.settings, 'another-reader')
            self.assertEqual(again.revision, first.revision)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(sorted(self.settings.backup_dir.rglob('*')), backups)
        self.assertEqual(self.settings.audit_log_path.read_bytes(), audit)

    def test_metadata_save_then_category_save_survives_other_catalog_reads(self):
        first = scan_loras(self.settings, 'test')
        saved = update_lora(self.settings, first.items[0].path,
            LoraCatalogUpdateRequest(display_name='Edited', recommended_prompt='ink lines'),
            first.revision, 'test')
        editor = scan_loras(self.settings, 'test')
        scan_loras(self.settings, 'another-reader')
        self.assertEqual(editor.revision, saved.revision)
        update_lora(self.settings, first.items[0].path,
            LoraCatalogUpdateRequest(category='style'), editor.revision, 'test')
        item = scan_loras(self.settings, 'test').items[0]
        self.assertEqual((item.display_name, item.recommended_prompt, item.category), ('Edited', 'ink lines', 'style'))

    def test_real_concurrent_metadata_update_is_still_rejected(self):
        first = scan_loras(self.settings, 'test')
        update_lora(self.settings, first.items[0].path,
            LoraCatalogUpdateRequest(display_name='Other writer'), first.revision, 'other')
        with self.assertRaises(RevisionConflict):
            update_lora(self.settings, first.items[0].path,
                LoraCatalogUpdateRequest(category='style'), first.revision, 'stale-editor')
        item = scan_loras(self.settings, 'test').items[0]
        self.assertEqual((item.display_name, item.category), ('Other writer', 'unclassified'))

    def test_real_file_change_updates_revision_without_resetting_metadata(self):
        first = scan_loras(self.settings, 'test')
        saved = update_lora(self.settings, first.items[0].path,
            LoraCatalogUpdateRequest(display_name='Keep my name', category='style'), first.revision, 'test')
        (self.settings.lora_root / 'artist/ink.safetensors').write_bytes(b'changed fixture')
        changed = scan_loras(self.settings, 'test')
        self.assertNotEqual(changed.revision, saved.revision)
        self.assertEqual((changed.items[0].display_name, changed.items[0].category), ('Keep my name', 'style'))

    def test_unchanged_scan_checks_external_write_before_returning(self):
        first = scan_loras(self.settings, 'test')
        from astr_auto_anima_hub import storage
        original = storage.file_revision
        calls = 0

        def changed(path, name):
            nonlocal calls
            calls += 1
            value = original(path, name)
            if calls >= 2:
                value.revision = 'external-write'
            return value

        with patch.object(storage, 'file_revision', side_effect=changed):
            with self.assertRaises(RevisionConflict):
                scan_loras(self.settings, 'test')
        self.assertEqual(scan_loras(self.settings, 'test').revision, first.revision)
