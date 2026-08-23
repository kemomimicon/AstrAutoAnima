from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astr_auto_anima_hub.lite_users import (
    LiteUserRegistryError,
    authenticate_lite_user,
    hash_lite_token,
    load_lite_users,
)


class LiteUserTests(unittest.TestCase):
    def test_load_and_authenticate_hashed_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "users.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "users": [
                            {
                                "id": "qq-123456",
                                "label": "Tester",
                                "qq": "123456",
                                "token_sha256": hash_lite_token("secret-token"),
                                "allow_group": True,
                                "enabled": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_lite_users(path)[0].qq, "123456")
            self.assertEqual(
                authenticate_lite_user(path, "secret-token").id, "qq-123456"
            )
            self.assertIsNone(authenticate_lite_user(path, "wrong-token"))

    def test_rejects_duplicate_qq(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "users.json"
            path.write_text(
                json.dumps(
                    {
                        "users": [
                            {
                                "id": "one",
                                "label": "One",
                                "qq": "123456",
                                "token_sha256": "1" * 64,
                            },
                            {
                                "id": "two",
                                "label": "Two",
                                "qq": "123456",
                                "token_sha256": "2" * 64,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(LiteUserRegistryError):
                load_lite_users(path)


if __name__ == "__main__":
    unittest.main()
