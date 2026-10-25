import json
import ast
import sqlite3
import tempfile
import unittest
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace, MethodType

from astrbot_plugin_comfy_bridge.personal_prompt_runtime import personal_prompts
from astrbot_plugin_comfy_bridge.prompt_pool_runtime import load_prompt_pool, select_random_prompts
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


class PersonalPromptRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "hub_state"
        self.state.mkdir()
        self.registry = self.state / "lite_users.json"
        self.database = self.state / "prompt_favorites.sqlite3"
        self.registry.write_text('{"users":[]}', encoding="utf-8")
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TABLE favorites (id TEXT, owner TEXT, prompt TEXT, name TEXT, safety_code TEXT, created_at REAL)")
            db.executemany("INSERT INTO favorites VALUES (?,?,?,?,?,?)", [
                (f"liked-old-{i}", "legacy-owner", f"rain, street {i}", "old", "N", i) for i in range(6)
            ] + [("admin", "administrator", "not yours", "admin", "N", 9),
                 ("registered", "one", "registered only", "one", "N", 10)])

    def bridge(self, **changes):
        document = dict(schema="aaa-favorite-reader-v1", legacy_qq="123456",
                        users_path=str(self.registry), favorites_path=str(self.database))
        document.update(changes)
        (self.state / "favorite_reader.json").write_text(json.dumps(document), encoding="utf-8")

    def ticket_event(self, **changes):
        root, token = "a" * 32, "b" * 32
        ticket = dict(root=root, expires=time.time() + 60,
                      favorites_owner="legacy-owner", favorites_scope="prompt-favorites:read")
        ticket.update(changes)
        path = self.root / "safety/tickets" / (token + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ticket), encoding="utf-8")
        sender = "aaa_safe_" + token
        return SimpleNamespace(get_platform_name=lambda: "webchat",
            get_sender_id=lambda: sender,
            get_session_id=lambda: f"webchat!{sender}!hub_job_{root}")

    def test_webchat_owner_requires_exact_session_capability(self):
        self.bridge()
        before = self.database.read_bytes()
        event = self.ticket_event()
        self.assertEqual(len(personal_prompts(self.root, event.get_sender_id(), event=event)), 6)
        event = self.ticket_event(favorites_owner="administrator")
        self.assertEqual([r["id"] for r in personal_prompts(self.root, "123456", event=event)], ["admin"])
        for changes in ({"expires": 0}, {"expires": float("inf")},
                        {"favorites_scope": ""}, {"favorites_owner": ""}, {"root": "wrong"}):
            event = self.ticket_event(**changes)
            with self.assertRaises(WorkflowError):
                personal_prompts(self.root, "123456", event=event)
        event = self.ticket_event()
        event.get_session_id = lambda: "hub_job_" + "c" * 32
        with self.assertRaises(WorkflowError):
            personal_prompts(self.root, "123456", event=event)
        for forged in ("hub_user_legacy-owner", "api_hub_user_legacy-owner", "123456"):
            event.get_sender_id = lambda: forged
            with self.assertRaises(WorkflowError):
                personal_prompts(self.root, forged, event=event)
        self.assertEqual(before, self.database.read_bytes())

    def test_native_platform_cannot_use_a_webchat_capability(self):
        self.bridge()
        event = self.ticket_event()
        event.get_platform_name = lambda: "aiocqhttp"
        self.assertEqual(personal_prompts(self.root, event.get_sender_id(), event=event), [])

    def test_legacy_qq_reads_existing_collection_without_writes(self):
        before = self.database.read_bytes()
        self.assertEqual(personal_prompts(self.root, "123456"), [])
        self.bridge()
        rows = personal_prompts(self.root, "123456")
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["id"].startswith("liked-old-") for row in rows))
        for qq in ("777777", "", "legacy-owner", "administrator", "' OR 1=1", "0123456"):
            self.assertEqual(personal_prompts(self.root, qq), [])
        self.assertEqual(before, self.database.read_bytes())
        self.assertEqual({p.name for p in self.state.iterdir()},
                         {"favorite_reader.json", "lite_users.json", "prompt_favorites.sqlite3"})

    def test_missing_registry_can_still_resolve_explicit_legacy_binding(self):
        self.bridge()
        self.registry.unlink()
        self.assertEqual(len(personal_prompts(self.root, "123456")), 6)
        self.assertEqual(personal_prompts(self.root, "654321"), [])

    def test_registered_disabled_and_duplicate_binding_precedence(self):
        self.bridge()
        account = {"id": "one", "qq": "123456", "enabled": True}
        for users, expected in (([account], ["registered"]),
                ([dict(account, enabled=False)], []),
                ([account, dict(account, id="two")], []),
                ([dict(account, id="")], [])):
            self.registry.write_text(json.dumps({"users": users}), encoding="utf-8")
            self.assertEqual([r["id"] for r in personal_prompts(self.root, "123456")], expected)

    def test_rebinding_or_revoking_does_not_leave_old_access(self):
        self.bridge(legacy_qq="654321")
        self.assertEqual(personal_prompts(self.root, "123456"), [])
        self.assertEqual(len(personal_prompts(self.root, "654321")), 6)
        self.bridge(legacy_qq="")
        self.assertEqual(personal_prompts(self.root, "654321"), [])

    def test_invalid_bridge_or_registry_fails_closed(self):
        for changes in ({"schema": "other"}, {"legacy_qq": "bad"}, {"users_path": "relative"},
                        {"favorites_path": None}):
            self.bridge(**changes)
            with self.assertRaises(ValueError):
                personal_prompts(self.root, "123456")
        self.bridge()
        for payload in ("broken", "[]", '{"users":{}}'):
            self.registry.write_text(payload, encoding="utf-8")
            with self.assertRaises(ValueError):
                personal_prompts(self.root, "123456")

    def test_real_P_pool_single_and_five_draws_never_leak_other_owners(self):
        self.bridge()
        pool_path = self.root / "anima_random_prompt_pool.json"
        pool_path.write_text(json.dumps({"prompts": [
            {"id": "public", "prompt": "landscape", "source_code": "D", "safety_code": "N"},
            {"id": "old-other", "prompt": "private", "source_code": "P", "liked_by": "other"},
        ]}), encoding="utf-8")
        before = pool_path.read_bytes()
        tree = ast.parse((Path(__file__).parents[1] / "main.py").read_text("utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ComfyWorkflowBridge")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_random_prompt_pool")
        ns = dict(Any=object, __package__="astrbot_plugin_comfy_bridge", load_prompt_pool=load_prompt_pool)
        exec(compile(ast.Module(body=[method], type_ignores=[]), "real-p-pool", "exec"), ns)
        runtime = SimpleNamespace(_prompt_pool_path=lambda: pool_path)
        get_pool = MethodType(ns["_random_prompt_pool"], runtime)
        selection = {"source_codes": ["P"], "safety_codes": ["N"]}
        for count in (1, 5):
            picked, _, _ = select_random_prompts(get_pool(selection, "123456"), count, "",
                                                 source_codes=["P"], safety_codes=["N"])
            self.assertEqual(len(picked), count)
            self.assertEqual(len({r["id"] for r in picked}), count)
            self.assertTrue(all(r["id"].startswith("liked-old-") for r in picked))
        unknown = get_pool(selection, "777777")
        self.assertFalse(any(r["source_code"] == "P" for r in unknown["prompts"]))
        self.assertEqual(pool_path.read_bytes(), before)

    def test_only_matching_qq_sees_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "hub_state"
            state.mkdir()
            (state / "lite_users.json").write_text(json.dumps({"users": [
                {"id": "one", "qq": "123456", "enabled": True},
                {"id": "two", "qq": "654321", "enabled": True},
            ]}), encoding="utf-8")
            with closing(sqlite3.connect(state / "prompt_favorites.sqlite3")) as db, db:
                db.execute("CREATE TABLE favorites (id TEXT, owner TEXT, prompt TEXT, name TEXT, safety_code TEXT, created_at REAL)")
                db.executemany("INSERT INTO favorites VALUES (?,?,?,?,?,?)", [
                    ("liked-1", "one", "rain, flowers", "one", "N", 1),
                    ("liked-2", "two", "private", "two", "H", 2),
                ])
            rows = personal_prompts(root, "123456")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["prompt"], "rain, flowers")
            self.assertEqual(rows[0]["source_code"], "P")
            self.assertEqual(personal_prompts(root, "777777"), [])
            legacy = [
                {"id": "old-1", "prompt": "rain, flowers", "source_code": "P", "liked_by": "one"},
                {"id": "old-2", "prompt": "snow", "source_code": "P", "liked_by": "one"},
                {"id": "old-3", "prompt": "secret", "source_code": "P", "liked_by": "two"},
            ]
            merged = personal_prompts(root, "123456", legacy)
            self.assertEqual({row["prompt"] for row in merged}, {"rain, flowers", "snow"})


if __name__ == "__main__":
    unittest.main()
