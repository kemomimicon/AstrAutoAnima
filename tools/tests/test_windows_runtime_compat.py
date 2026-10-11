"""Offline integration boundaries; no GPU, network, live services or user data."""
import ast
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
GUARDS = [
    "comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools/idle_guard.py",
    "hub/service/src/astr_auto_anima_hub/idle_guard.py",
    "plugin/astrbot_plugin_comfy_bridge/idle_guard_runtime.py",
]


def load(relative):
    spec = importlib.util.spec_from_file_location("compat_test_module", ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def extract(relative, names, namespace):
    path = ROOT / relative
    tree = ast.parse(path.read_text("utf-8-sig"))
    body = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class AdmissionTests(unittest.TestCase):
    def test_comfy_middleware_reaches_handler_on_windows(self):
        guard = load(GUARDS[0])
        instance = types.SimpleNamespace(app=types.SimpleNamespace(middlewares=[]),
                                         routes=types.SimpleNamespace(get=lambda _: lambda f: f))
        web = types.SimpleNamespace(middleware=lambda f: f,
                                    json_response=lambda payload, status=200: (payload, status))
        modules = {"server": types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=instance)),
                   "aiohttp": types.SimpleNamespace(web=web)}
        ns = extract("comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools/idle_admission.py",
                     {"install_idle_admission"},
                     {"time": time, "admission": guard.admission, "root_path": guard.root_path})
        async def handler(request):
            return "accepted"
        with patch.dict(sys.modules, modules), patch.object(sys, "platform", "win32"):
            self.assertTrue(ns["install_idle_admission"]())
            self.assertTrue(ns["install_idle_admission"]())
            self.assertEqual(len(instance.app.middlewares), 1)
            for url in ["/prompt", "/api/prompt"]:
                result = asyncio.run(instance.app.middlewares[0](types.SimpleNamespace(method="POST", path=url), handler))
                self.assertEqual(result, "accepted")

    def test_all_copies_windows_skip_before_paths_locks_or_fcntl(self):
        for filename in GUARDS:
            with self.subTest(filename=filename):
                guard = load(filename)
                with patch.object(guard.sys, "platform", "win32"), patch.object(guard, "root_path", side_effect=AssertionError("must not access Linux state")):
                    self.assertIsNone(guard.admission())
                    self.assertIsNone(guard.admission(Path("relative/copied-linux-data")))

    def test_relative_roots_normalized_and_linux_opt_out(self):
        for filename in GUARDS:
            guard = load(filename)
            with patch.object(guard.sys, "platform", "linux"):
                relative = Path("compat-no-shutdown-controller")
                root = Path.cwd() / relative
                self.assertEqual(guard.root_path(relative), root)
                self.assertIsNone(guard.admission(root))

    @unittest.skipUnless(sys.platform == "linux", "real Linux flock regression")
    def test_linux_exclusive_lock_and_gate_remain_fail_closed(self):
        import fcntl
        for filename in GUARDS:
            guard = load(filename)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                lock = root / "idle_shutdown.lock"
                lock.touch()
                with lock.open("a") as held:
                    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(RuntimeError):
                        guard.admission(root)
                gate = root / "idle_shutdown_gate.json"
                gate.write_text(json.dumps({"boot_id": guard.boot_id(), "blocked": True}), "utf-8")
                with self.assertRaises(RuntimeError):
                    guard.admission(root)
                gate.write_text("invalid json", "utf-8")
                with self.assertRaises(RuntimeError):
                    guard.admission(root)
                gate.write_text(json.dumps({"boot_id": "previous-boot", "blocked": True}), "utf-8")
                lease = guard.admission(root)
                self.assertIsNotNone(lease)
                lease.close()


class ReverseStorageTests(unittest.TestCase):
    def setUp(self):
        self.ns = extract("comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools/nodes.py",
                          {"_checked_reverse_path", "_reverse_storage_root", "AnimaReverseResultSaver"},
                          dict(Path=Path, os=os, json=json, hashlib=hashlib, uuid=uuid,
                               datetime=datetime, timezone=timezone, tempfile=tempfile))

    def test_actual_saver_roundtrip_in_local_unicode_directory(self):
        # Tiny stand-in for a pixel array: exercises the real saver, not inference.
        class Pixels:
            def __mul__(self, _): return self
            def astype(self, _): return self
            def tobytes(self): return b"rgb-pixel"
        self.ns["np"] = types.SimpleNamespace(asarray=lambda _: Pixels(), clip=lambda x, *_: x, uint8=int)
        with tempfile.TemporaryDirectory(prefix="AAA Windows (test) ") as tmp:
            root = Path(tmp).resolve() / "反推 历史"
            result = self.ns["AnimaReverseResultSaver"]().save([None], "{}", "rainy street", str(root), "", "private", "", "", "", False)
            saved = Path(result["result"][0])
            self.assertTrue(saved.is_relative_to(root))
            self.assertEqual(json.loads(saved.read_text("utf-8"))["actual_generation_prompt"], "rainy street")
            self.assertTrue((root / "index/reverse_history.jsonl").is_file())
            self.assertEqual(result["ui"]["anima_prompt"], ["rainy street"])

    def test_blank_uses_comfy_output_or_configured_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            folder = types.SimpleNamespace(get_output_directory=lambda: str(root / "output"))
            with patch.dict(sys.modules, {"folder_paths": folder}), patch.dict(os.environ, {"AAH_PLUGIN_DATA_DIR": ""}):
                self.assertEqual(self.ns["_reverse_storage_root"](""), root / "output/AstrAutoAnima/reverse_history")
            with patch.dict(os.environ, {"AAH_PLUGIN_DATA_DIR": str(root / "plugin_data")}):
                self.assertEqual(self.ns["_reverse_storage_root"](""), root / "plugin_data/reverse_history")

    def test_relative_and_broad_roots_rejected(self):
        for value in ["relative/history", Path.cwd().anchor, str(Path.home())]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.ns["_checked_reverse_path"](value)

    def test_reparse_ancestor_rejected_including_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            marker = root / "index"
            original = Path.lstat
            def fake(path, *args, **kwargs):
                if path == marker:
                    return types.SimpleNamespace(st_file_attributes=0x400, st_mode=stat.S_IFDIR)
                return original(path, *args, **kwargs)
            with patch.object(Path, "lstat", fake), self.assertRaises(ValueError):
                self.ns["_checked_reverse_path"](marker / "reverse_history.jsonl")


class DictionaryAndCleanupTests(unittest.TestCase):
    def test_dictionary_overlay_shares_actual_base_directory(self):
        ns = extract("plugin/astrbot_plugin_comfy_bridge/main.py",
                     {"_character_dictionary_edits_path"}, {"Path": Path})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            bridge = types.SimpleNamespace(config={}, _character_dictionary_path=lambda: root / "character_dictionary.json")
            self.assertEqual(ns["_character_dictionary_edits_path"](bridge), root / "hub_state/character_dictionary_edits.json")
            bridge.config["character_dictionary_edits_path"] = str(root / "custom.json")
            self.assertEqual(ns["_character_dictionary_edits_path"](bridge), root / "custom.json")

    def test_cleanup_prunes_reparse_subtree_and_rejects_root(self):
        cleanup = load("plugin/astrbot_plugin_comfy_bridge/cleanup_runtime.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            linked = root / "junction"
            linked.mkdir()
            keep = linked / "old.png"
            keep.write_bytes(b"test-image")
            os.utime(keep, (1, 1))
            original = Path.lstat
            def fake(path, *args, **kwargs):
                if path == linked:
                    return types.SimpleNamespace(st_file_attributes=0x400, st_mode=stat.S_IFDIR)
                return original(path, *args, **kwargs)
            with patch.object(Path, "lstat", fake):
                self.assertEqual(cleanup.cleanup_old_output_images(root, now=999999).deleted, 0)
                self.assertEqual(cleanup.cleanup_old_output_images(linked, now=999999).failed, 1)
                with self.assertRaises(ValueError):
                    cleanup.checked_output_path(linked / "nested")
            self.assertEqual(keep.read_bytes(), b"test-image")

    def test_output_path_checked_before_mkdir_and_resolve(self):
        ns = extract("plugin/astrbot_plugin_comfy_bridge/main.py", {"_output_dir"},
                     {"Path": Path, "checked_output_path": lambda _: (_ for _ in ()).throw(ValueError("blocked"))})
        with patch.object(Path, "mkdir") as mkdir, self.assertRaises(ValueError):
            ns["_output_dir"](types.SimpleNamespace(config={"output_dir": "fake-output"}))
        mkdir.assert_not_called()
