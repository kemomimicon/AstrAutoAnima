"""Validate local publication materials, never approve or contact a cloud instance."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    "docs/AUTODL_IMAGE.md", "docs/AUTODL_IMAGE_PUBLISH.md",
    "docs/AUTODL_ART_DESCRIPTION.md", "docs/AUTODL_IMAGE_REDISTRIBUTION.md",
)
REQUIRED_GATES = {
    "exact_public_source_mapping", "third_party_redistribution", "host_and_payload_privacy",
    "new_instance_ssh_jupyter_identity", "independent_application_credentials", "payload_restore",
    "password_change_and_restart", "gpu_base_generation", "openapi_authentication",
    "qq_delivery_and_reply_link", "client_preview_download", "libraries_and_character_dictionary",
    "studio_without_training", "seedvr2_optional_inference", "clean_final_candidate_restore",
}


def check(root):
    errors = []
    for name in DOCS:
        path = root / name
        if path.is_symlink() or not path.is_file():
            errors.append("Missing or linked document: " + name)
            continue
        text = path.read_text("utf-8-sig")
        if text.count("```") % 2:
            errors.append("Unclosed code fence: " + name)
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            local = (path.parent / target.split("#", 1)[0]).resolve()
            if not local.is_relative_to(root.resolve()) or not local.is_file():
                errors.append("Invalid local link in " + name)
    source = root / "tools/autodl_public_image_20261025/public_probe.py"
    tree = ast.parse(source.read_text("utf-8-sig"))
    imports = {
        n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0]
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
    }
    if imports - {"__future__", "argparse", "hashlib", "json", "pathlib", "sys"}:
        errors.append("Probe acquired unexpected imports; review CPU-only/read-only boundary")
    pending = json.loads((root / "examples/autodl_image_acceptance.pending.json").read_text("utf-8-sig"))
    if pending.get("template_only") is not True or pending.get("public_release_approved") is not False:
        errors.append("Pending template must never approve a public release")
    if set(pending.get("gates", {})) != REQUIRED_GATES or any(v != "pending" for v in pending.get("gates", {}).values()):
        errors.append("Pending template must keep every acceptance gate pending")
    if pending.get("evidence") != {}:
        errors.append("Pending template must not contain personal acceptance evidence")
    if pending.get("baseline_software") != "0.5.2-beta.1/build44":
        errors.append("Image baseline identity changed unexpectedly")
    assignments = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                   if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "EXPECTED_SHA"}
    if pending.get("payload_sha256") != assignments.get("EXPECTED_SHA"):
        errors.append("Pending template and probe identify different payloads")
    for name in ("Open-AAA-Tunnel.ps1", "Open-AAA-Tunnel.cmd"):
        path = source.parent / name
        if not path.is_file() or path.is_symlink() or not path.read_bytes().isascii():
            errors.append("Missing, linked or non-ASCII Windows tunnel helper")
    return errors


if __name__ == "__main__":
    try:
        problems = check(ROOT)
    except (OSError, ValueError, SyntaxError, TypeError):
        raise SystemExit("FAIL: malformed or inaccessible publication materials; no cloud action performed")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit(1)
    print("PASS: local materials, document links, CPU-only imports and pending acceptance template")
    print("NOT APPROVED: cloud restore, GPU tests, redistribution review and source mapping remain pending")
