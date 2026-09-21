"""Local moderation primitives. No AstrBot, model or network dependencies."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from pathlib import Path

RANDOM_REVIEW = ContextVar("aaa_random_review", default=False)

class SafetyError(RuntimeError):
    pass


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text)).casefold()
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return re.sub(r"\s+", " ", re.sub(r"[_‐‑–—-]", " ", text)).strip()


def match_rules(text, rules, exemptions=""):
    allowed = {normalize(x) for x in str(exemptions).splitlines() if x.strip()}
    text = normalize(text)
    occurrences = []
    for rule in rules:
        for match in re.finditer(rule["pattern"], text, re.I):
            # Only the exact occurrence is exempt: never disable the whole regex.
            term = normalize(match.group())
            occurrences.append((match.start(), match.end(), rule["id"], term))
    allowed_spans = [(start, end) for start, end, _, term in occurrences if term in allowed]
    return [{"rule": rule, "term": term} for start, end, rule, term in occurrences
            if not any(left <= start and end <= right for left, right in allowed_spans)]


class Policy:
    def __init__(self, config):
        self.enabled = bool(config.get("safety_mode_enabled", False))
        self.scope = str(config.get("safety_review_scope", "both"))
        if self.enabled and self.scope not in {"input", "output", "both"}:
            raise SafetyError("安全审核配置无效，生成失败")
        self.input = self.enabled and self.scope in {"input", "both"}
        self.output = self.enabled and self.scope in {"output", "both"}
        self.exemptions = str(config.get("safety_exempt_terms", ""))
        self.fingerprint = hashlib.sha256(json.dumps({
            "enabled": self.enabled, "scope": self.scope, "exemptions": self.exemptions,
            "threshold": float(config.get("safety_audit_threshold", 0.35)), "rules": "20260910.2",
        }, sort_keys=True).encode()).hexdigest()


class CreditStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "credit.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users(qq TEXT PRIMARY KEY, credit INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS penalties(root TEXT PRIMARY KEY, qq TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, root TEXT, qq TEXT,
                    stage TEXT, rules TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS notices(id TEXT PRIMARY KEY, qq TEXT, credit INTEGER,
                    root TEXT, sent INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS resets(id TEXT PRIMARY KEY, qq TEXT, actor TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS approvals(sha TEXT, policy TEXT, PRIMARY KEY(sha, policy));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA busy_timeout=15000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def score(self, qq):
        with self.connect() as db:
            row = db.execute("SELECT credit FROM users WHERE qq=?", (qq,)).fetchone()
        return row[0] if row else 10

    def block(self, root, qq, stage, hits, *, deduct=True):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO users VALUES (?,10)", (qq,))
            before = db.execute("SELECT credit FROM users WHERE qq=?", (qq,)).fetchone()[0]
            inserted = db.execute("INSERT OR IGNORE INTO penalties VALUES (?,?)", (root, qq)).rowcount if deduct else 0
            after = max(0, before - 1) if inserted else before
            db.execute("UPDATE users SET credit=? WHERE qq=?", (after, qq))
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (
                uuid.uuid4().hex, root, qq, stage if deduct else stage + ":no_penalty",
                json.dumps(hits, ensure_ascii=False), time.time()))
            if inserted and (before >= 5 > after or before > 0 == after):
                db.execute("INSERT INTO notices(id,qq,credit,root) VALUES (?,?,?,?)",
                           (uuid.uuid4().hex, qq, after, root))
        return after

    def reset(self, qq, actor):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO users VALUES (?,10)", (qq,))
            db.execute("INSERT INTO resets VALUES (?,?,?,?)", (uuid.uuid4().hex, qq, actor, time.time()))
        # Do NOT remove penalties: retries after a reset remain idempotent.

    def approve(self, content, policy):
        sha = hashlib.sha256(content).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO approvals VALUES (?,?)", (sha, policy))

    def approved(self, content, policy):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM approvals WHERE sha=? AND policy=?",
                              (hashlib.sha256(content).hexdigest(), policy)).fetchone() is not None


class PriorityGate:
    """Dynamic two-level queue, FIFO within each level; never preempt a running job."""
    def __init__(self, capacity=1):
        self.capacity = capacity
        self.active = 0
        self.waiters = []
        self.changed = asyncio.Condition()
        self.sequence = 0

    @asynccontextmanager
    async def slot(self, priority):
        async with self.changed:
            self.sequence += 1
            ticket = (self.sequence, priority)
            self.waiters.append(ticket)
            try:
                while self.active >= self.capacity or min(
                    self.waiters, key=lambda item: (item[1](), item[0])
                ) is not ticket:
                    await self.changed.wait()
                self.waiters.remove(ticket)
                self.active += 1
            except BaseException:
                self.waiters.remove(ticket)
                self.changed.notify_all()
                raise
        try:
            yield
        finally:
            async with self.changed:
                self.active -= 1
                self.changed.notify_all()


def load_policy(root):
    path = Path(root) / "policy.json"
    if not path.exists():
        return Policy({})
    return Policy(json.loads(path.read_text(encoding="utf-8")))


def validate_audit(record, nonce):
    outputs = record.get("outputs", {})
    reports = outputs.get("4", {}).get("aaa_safety", [])
    if not isinstance(reports, list) or len(reports) != 1:
        raise SafetyError("安全审核结果缺失，生成失败（未扣分）")
    report = reports[0]
    if not isinstance(report, dict) or report.get("nonce") != nonce or report.get("status") != "ok":
        raise SafetyError("安全审核结果无效，生成失败（未扣分）")
    tags = report.get("tags")
    if not isinstance(tags, str) or not tags.strip():
        raise SafetyError("安全审核标签为空，生成失败（未扣分）")
    return tags


def positive_texts(workflow):
    """Walk positive conditioning only, including concatenation/weighted encoders."""
    roots = []
    for node in workflow.values():
        for key, value in node.get("inputs", {}).items():
            if key in {"positive", "positive_prompt"}:
                roots.append(value)
    seen, texts = set(), []
    def walk(value):
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list) and len(value) == 2 and str(value[0]) in workflow and isinstance(value[1], int):
            key = str(value[0])
            if key in seen:
                return
            seen.add(key)
            node = workflow[key]
            for field, item in node.get("inputs", {}).items():
                if field not in {"model", "clip", "vae", "negative", "negative_prompt"}:
                    walk(item)
    for root in roots:
        walk(root)
    return texts
