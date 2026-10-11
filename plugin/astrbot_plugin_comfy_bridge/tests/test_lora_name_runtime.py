import ast
import asyncio
import copy
import json
from pathlib import Path
import types
import unittest
import uuid
from unittest.mock import patch

from astrbot_plugin_comfy_bridge.lora_name_runtime import (
    match_lora_name, prepare_lora_workflow,
)
from astrbot_plugin_comfy_bridge.workflow_runtime import WorkflowError


def graph(name="loras/@example_style.safetensors", kind="LoraLoader", node_id="900100"):
    return {node_id: {"class_type": kind, "inputs": {
        "lora_name": name, "strength_model": 0.7, "strength_clip": 0.6,
        "model": ["1", 0], "clip": ["2", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}}}


def metadata(choices, kind="LoraLoader"):
    return {kind: {"input": {"required": {"lora_name": [choices]}}}}


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
    async def text(self): return json.dumps(self.payload)


class Session:
    def __init__(self, catalogs):
        self.catalogs, self.gets, self.posts = catalogs, [], []
    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        kind = url.rsplit("/", 1)[-1]
        result = self.catalogs[kind]
        if isinstance(result, Exception): raise result
        return Response(result)
    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return Response({"prompt_id": "test-prompt"})


async def read(response):
    return response.payload


class MatchTests(unittest.TestCase):
    def test_reported_nested_windows_name_preserves_loras_and_at(self):
        self.assertEqual(match_lora_name("loras/@example_style.safetensors",
            [r"loras\@example_style.safetensors"], node_id="900100"),
            r"loras\@example_style.safetensors")

    def test_linux_target_accepts_windows_preset(self):
        self.assertEqual(match_lora_name(r"a\b\style.safetensors",
            ["a/b/style.safetensors"], node_id="x"), "a/b/style.safetensors")

    def test_unicode_spaces_and_mixed_separators(self):
        self.assertEqual(match_lora_name("画风/子目录\\名字 (v1).safetensors",
            [r"画风\子目录\名字 (v1).safetensors"], node_id="x"),
            r"画风\子目录\名字 (v1).safetensors")

    def test_exact_name_wins_even_if_normalization_is_ambiguous(self):
        choices = ["a/b/c.safetensors", r"a\b/c.safetensors"]
        self.assertEqual(match_lora_name(choices[1], choices, node_id="x"), choices[1])

    def test_ambiguous_separator_match_is_rejected(self):
        with self.assertRaisesRegex(WorkflowError, "歧义"):
            match_lora_name(r"a/b\c.safetensors",
                ["a/b/c.safetensors", r"a\b/c.safetensors"], node_id="x")

    def test_no_basename_casefold_prefix_trim_or_url_decode_guessing(self):
        cases = [
            ("x.safetensors", ["a/x.safetensors", "b/x.safetensors"]),
            ("loras/x.safetensors", ["x.safetensors"]),
            ("A/X.safetensors", ["a/x.safetensors"]),
            ("a%20b/x.safetensors", ["a b/x.safetensors"]),
            ("a/x.safetensors ", ["a/x.safetensors"]),
            ("../x.safetensors", ["x.safetensors"]),
        ]
        for value, choices in cases:
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                match_lora_name(value, choices, node_id="x")

    def test_duplicate_identical_server_names_not_ambiguous(self):
        self.assertEqual(match_lora_name("a/x.safetensors",
            [r"a\x.safetensors", r"a\x.safetensors"], node_id="x"), r"a\x.safetensors")


class PrepareTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_roles_styles_legacy_slots_and_model_only_use_exact_target(self):
        workflow = graph()
        for node_id in ("900001", "46", "47", "48", "49", "900101"):
            workflow.update({node_id: graph("loras/@example_style.safetensors")[ "900100"]})
        workflow["88"] = graph("role/hero.safetensors", "LoraLoaderModelOnly")["900100"]
        before = copy.deepcopy(workflow)
        session = Session({
            "LoraLoader": metadata([r"loras\@example_style.safetensors"]),
            "LoraLoaderModelOnly": metadata([r"role\hero.safetensors"], "LoraLoaderModelOnly"),
        })
        result = await prepare_lora_workflow(session, workflow, "http://remote:8188/", read)
        self.assertEqual(len(session.gets), 2)
        self.assertEqual(workflow, before)
        self.assertEqual(result["88"]["inputs"]["lora_name"], r"role\hero.safetensors")
        for node_id in ("900100", "900001", "46", "47", "48", "49", "900101"):
            self.assertEqual(result[node_id]["inputs"]["lora_name"], r"loras\@example_style.safetensors")
            self.assertEqual(result[node_id]["inputs"]["strength_model"], 0.7)
            self.assertEqual(result[node_id]["inputs"]["model"], ["1", 0])
        self.assertEqual(result["9"], workflow["9"])
        self.assertTrue(all(call[0].startswith("http://remote:8188/object_info/") for call in session.gets))

    async def test_no_lora_and_linked_string_and_custom_nodes_unchanged(self):
        for workflow in [
            graph(kind="ThirdPartyLoraStack"), graph(name=["text-node", 0]),
            {"9": {"class_type": "SaveImage", "inputs": {}}},
        ]:
            session = Session({})
            self.assertEqual(await prepare_lora_workflow(session, workflow, "http://target", read), workflow)
            self.assertEqual(session.gets, [])

    async def test_partial_match_does_not_change_original(self):
        workflow = graph("a/x.safetensors")
        workflow["900001"] = graph("missing.safetensors")["900100"]
        before = copy.deepcopy(workflow)
        with self.assertRaises(WorkflowError):
            await prepare_lora_workflow(Session({"LoraLoader": metadata([r"a\x.safetensors"])}),
                                        workflow, "http://target", read)
        self.assertEqual(before, workflow)

    async def test_malformed_or_empty_catalogs_fail_clearly(self):
        for payload in [None, {}, {"LoraLoader": None}, metadata("not-an-enum"),
                        metadata([None]), metadata([])]:
            with self.subTest(payload=payload), self.assertRaises(WorkflowError):
                await prepare_lora_workflow(Session({"LoraLoader": payload}), graph(), "http://target", read)

    async def test_network_failure_and_timeout_fail_before_submission(self):
        with self.assertRaisesRegex(WorkflowError, "尚未提交"):
            await prepare_lora_workflow(Session({"LoraLoader": OSError("offline")}), graph(), "http://target", read)
        async def timeout(awaitable, **_):
            awaitable.close()
            raise asyncio.TimeoutError
        with patch("astrbot_plugin_comfy_bridge.lora_name_runtime.asyncio.wait_for", timeout):
            with self.assertRaisesRegex(WorkflowError, "15 秒"):
                await prepare_lora_workflow(Session({}), graph(), "http://target", read)

    async def test_no_stale_or_cross_server_cache(self):
        workflow = graph("a/x.safetensors")
        win = Session({"LoraLoader": metadata([r"a\x.safetensors"])})
        linux = Session({"LoraLoader": metadata(["a/x.safetensors"])})
        first = await prepare_lora_workflow(win, workflow, "http://windows", read)
        second = await prepare_lora_workflow(linux, workflow, "http://linux", read)
        self.assertEqual(first["900100"]["inputs"]["lora_name"], r"a\x.safetensors")
        self.assertEqual(second["900100"]["inputs"]["lora_name"], "a/x.safetensors")
        linux.catalogs["LoraLoader"] = metadata([])
        with self.assertRaises(WorkflowError):
            await prepare_lora_workflow(linux, workflow, "http://linux", read)


class SubmitIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Exercise actual shared submission + HTTP parsing without importing AstrBot.
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text("utf-8-sig"))
        names = {"_submit_workflow", "_response_json"}
        body = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
        namespace = dict(aiohttp=types.SimpleNamespace(ClientSession=object, ClientResponse=object),
                         Any=object, json=json, uuid=uuid, WorkflowError=WorkflowError,
                         prepare_lora_workflow=prepare_lora_workflow)
        exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), namespace)
        self.bridge = types.SimpleNamespace(_base_url=lambda: "http://actual-target:8188")
        self.bridge._response_json = types.MethodType(namespace["_response_json"], self.bridge)
        self.submit = types.MethodType(namespace["_submit_workflow"], self.bridge)

    async def test_actual_post_payload_is_canonical_without_modifying_source(self):
        session = Session({"LoraLoader": metadata([r"loras\@example_style.safetensors"])})
        workflow = graph()
        self.assertEqual(await self.submit(session, workflow), "test-prompt")
        self.assertEqual(len(session.posts), 1)
        url, kwargs = session.posts[0]
        self.assertEqual(url, "http://actual-target:8188/prompt")
        self.assertEqual(kwargs["json"]["prompt"]["900100"]["inputs"]["lora_name"], r"loras\@example_style.safetensors")
        self.assertEqual(workflow["900100"]["inputs"]["lora_name"], "loras/@example_style.safetensors")

    async def test_unknown_or_ambiguous_names_never_post(self):
        for name, choices in [
            ("missing", ["present"]),
            (r"a/b\c", ["a/b/c", r"a\b/c"]),
        ]:
            session = Session({"LoraLoader": metadata(choices)})
            with self.assertRaises(WorkflowError):
                await self.submit(session, graph(name))
            self.assertEqual(session.posts, [])

    async def test_http_catalog_error_never_post(self):
        session = Session({})
        session.get = lambda *args, **kwargs: Response({"error": "unavailable"}, 503)
        with self.assertRaisesRegex(WorkflowError, "HTTP 503"):
            await self.submit(session, graph())
        self.assertEqual(session.posts, [])

    async def test_plain_workflow_posts_without_catalog_request(self):
        session = Session({})
        workflow = {"9": {"class_type": "SaveImage", "inputs": {}}}
        self.assertEqual(await self.submit(session, workflow), "test-prompt")
        self.assertEqual(session.gets, [])
