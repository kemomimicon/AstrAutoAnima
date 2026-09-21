import asyncio
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety_runtime import CreditStore, Policy, PriorityGate, SafetyError, match_rules, positive_texts, validate_audit


class SafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = json.loads((Path(__file__).resolve().parents[1] / "data/safety_rules.json").read_text(encoding="utf-8"))["rules"]

    def test_terms_and_normalization(self):
        for text in ["nude", "NSFW", "(naked:1.2)", "nudity", "pussy", "ＰＵＳＳＹ", "pussy_juice", "(nipples:1.3)", "anal sex", "condom", "精液", "乳頭", "p\u200bussy"]:
            self.assertTrue(match_rules(text, self.rules), text)

    def test_ambiguous_and_nonsexual(self):
        for text in ["cock", "dick", "climax", "fingering", "vibrator", "lubricant", "analysis", "cocktail", "succumb", "sexy", "bikini", "denuded", "breasts", "underwear", "露点", "交配"]:
            self.assertFalse(match_rules(text, self.rules), text)

    def test_exact_exemption_not_regex(self):
        self.assertFalse(match_rules("condom", self.rules, "CONDOM"))
        self.assertTrue(match_rules("condoms", self.rules, "condom"))
        self.assertTrue(match_rules("condom", self.rules, ".*"))
        self.assertTrue(match_rules("condom, penis", self.rules, "condom"))
        self.assertTrue(match_rules("pussy juice", self.rules, "pussy"))
        self.assertFalse(match_rules("pussy juice", self.rules, "pussy_juice"))
        self.assertTrue(match_rules("pussy juice, pussy", self.rules, "pussy_juice"))

    def test_scopes(self):
        self.assertFalse(Policy({}).enabled)
        for scope, flags in [("input", (True,False)), ("output", (False,True)), ("both", (True,True))]:
            p = Policy({"safety_mode_enabled": True, "safety_review_scope": scope})
            self.assertEqual((p.input,p.output), flags)
        with self.assertRaises(SafetyError):
            Policy({"safety_mode_enabled": True, "safety_review_scope": "bad"})

    def test_credit_idempotency_threshold_reset(self):
        with tempfile.TemporaryDirectory() as root:
            store = CreditStore(root)
            for index in range(5):
                self.assertEqual(store.block("five", "123456", "output", []), 9)
            store = CreditStore(root)
            for index in range(5):
                store.block(str(index), "123456", "input", [])
            self.assertEqual(store.score("123456"), 4)
            with store.connect() as db:
                self.assertEqual(db.execute("SELECT credit FROM notices").fetchall(), [(4,)])
            for index in range(5, 9):
                store.block(str(index), "123456", "input", [])
            self.assertEqual(store.score("123456"), 0)
            store.reset("123456", "admin")
            self.assertEqual(store.block("five", "123456", "output", []), 10)

    def test_concurrent_same_root_one_penalty(self):
        with tempfile.TemporaryDirectory() as root:
            store = CreditStore(root)
            with ThreadPoolExecutor(5) as executor:
                list(executor.map(lambda _: store.block("batch", "123456", "output", []), range(10)))
            self.assertEqual(store.score("123456"), 9)

    def test_approval_policy_bound(self):
        with tempfile.TemporaryDirectory() as root:
            store = CreditStore(root)
            self.assertFalse(store.approved(b"image", "p1"))
            store.approve(b"image", "p1")
            self.assertTrue(store.approved(b"image", "p1"))
            self.assertFalse(store.approved(b"image", "p2"))
            self.assertFalse(store.approved(b"other", "p1"))

    def test_fail_closed_audit(self):
        for report in [{}, {"outputs": {"4": {"aaa_safety": []}}}, {"outputs": {"4": {"aaa_safety": [{"status":"ok","nonce":"wrong","tags":"solo"}]}}}]:
            with self.assertRaises(SafetyError):
                validate_audit(report, "nonce")
        report = {"outputs": {"4": {"aaa_safety": [{"status":"ok","nonce":"nonce","tags":"solo"}]}}}
        self.assertEqual(validate_audit(report,"nonce"), "solo")

    def test_positive_only_graph(self):
        graph = {"1":{"inputs":{"positive":["2",0],"negative":["3",0]}},
                 "2":{"inputs":{"text":"solo"}}, "3":{"inputs":{"text":"penis"}}}
        self.assertEqual(positive_texts(graph), ["solo"])


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_priority_fifo_cancel(self):
        gate = PriorityGate()
        order = []
        async def run(name, priority):
            async with gate.slot(lambda: priority):
                order.append(name)
                await asyncio.sleep(0)
        async with gate.slot(lambda: 0):
            low = asyncio.create_task(run("low", 1))
            first = asyncio.create_task(run("first", 0))
            second = asyncio.create_task(run("second", 0))
            cancelled = asyncio.create_task(run("cancelled", 0))
            await asyncio.sleep(0)
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)
        await asyncio.gather(low, first, second)
        self.assertEqual(order, ["first","second","low"])
        self.assertEqual(gate.active, 0)


if __name__ == "__main__":
    unittest.main()
