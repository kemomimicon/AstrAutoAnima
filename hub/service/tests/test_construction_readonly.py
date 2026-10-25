import tempfile
from pathlib import Path
from unittest.mock import patch

from astr_auto_anima_hub.app import create_app
from astr_auto_anima_hub.config import Settings


def test_constructing_hub_does_not_create_runtime_files():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / 'not-created'
        with patch.object(Path, 'mkdir', side_effect=AssertionError('eager write')):
            create_app(Settings(plugin_data_dir=root))
        assert not root.exists()
