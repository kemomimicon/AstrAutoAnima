import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from astr_auto_anima_hub.prompt_favorites_migration import main


def test_cli_preview_never_creates_database():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        pool, db = root/'pool.json', root/'favorites.sqlite3'
        pool.write_text(json.dumps({'prompts': [{'id': 'p', 'source_code': 'P', 'liked_by': 'owner', 'prompt': 'test tags'}]}))
        before = pool.read_bytes()
        assert main(['--pool', str(pool), '--database', str(db)]) == 0
        assert pool.read_bytes() == before
        assert not db.exists()


def test_cli_requires_operator_stopped_acknowledgement():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        pool = root/'pool.json'
        pool.write_text('{"prompts": []}')
        with pytest.raises(SystemExit), patch('astr_auto_anima_hub.prompt_favorites_migration.migrate_legacy_favorites') as migrate:
            main(['--pool', str(pool), '--database', str(root/'favorites.sqlite3'), '--apply'])
        migrate.assert_not_called()


def test_cli_cannot_reuse_pool_as_database():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory).resolve()/'pool.json'
        path.write_text('{"prompts": []}')
        with pytest.raises(SystemExit):
            main(['--pool', str(path), '--database', str(path)])
