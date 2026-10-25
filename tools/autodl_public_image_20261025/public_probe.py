"""Read-only, CPU-only structural probe. This is NOT a GPU or privacy certification."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

EXPECTED_SHA = "416ca962fc1c78c024dce0396775f1991184dc630d60e783e7a4b5cefa61dbf9"
EXPECTED_BYTES = 11928121690
EXPECTED_ENTRIES = 129054
EXPECTED_UNIQUE_BYTES = 18850893037
EXPECTED_ROOTS = {
    "aaa-install", "apps/AnimaLoraStudio", "apps/node-v22.20.0-linux-x64",
    "apps/Start-Studio.sh", "aaa-bootstrap-py312",
}


def unlinked(path: Path) -> bool:
    return not any(part.is_symlink() for part in (path, *path.parents))


def add(report, name, state, message):
    report["checks"].append({"name": name, "state": state, "message": message})


def probe(image: Path, repo: Path, full_hash: bool = False) -> dict:
    report = {
        "schema": 1,
        "probe_revision": "20261025.2",
        "purpose": "read-only CPU structural inspection; not release approval",
        "services_started": False, "files_written": False, "network_used": False,
        "gpu_test": "not performed", "privacy_certification": "not performed",
        "cloud_clone_test": "not performed", "checks": [],
    }
    if not unlinked(image) or not image.is_dir():
        add(report, "image_directory", "fail", "Missing or symlinked image directory; no recovery attempted.")
        return finish(report)
    add(report, "image_directory", "pass", "Image directory exists without symlinked ancestors.")
    manifest_path = image / "payload-manifest.json"
    valid = False
    if not unlinked(manifest_path) or not manifest_path.is_file():
        add(report, "manifest", "fail", "Manifest missing or linked.")
    elif manifest_path.stat().st_size > 64 * 1024:
        add(report, "manifest", "fail", "Unexpected manifest size; contents not displayed.")
    else:
        try:
            data = json.loads(manifest_path.read_text("utf-8-sig"))
            valid = (
                isinstance(data, dict)
                and data.get("schema") == 1
                and data.get("sha256") == EXPECTED_SHA
                and data.get("compressed_bytes") == EXPECTED_BYTES
                and data.get("entries") == EXPECTED_ENTRIES
                and data.get("unique_bytes") == EXPECTED_UNIQUE_BYTES
                and isinstance(data.get("top_roots"), list)
                and len(data["top_roots"]) == len(EXPECTED_ROOTS)
                and all(isinstance(x, str) for x in data["top_roots"])
                and set(data["top_roots"]) == EXPECTED_ROOTS
            )
        except (ValueError, UnicodeError):
            valid = False
        add(report, "manifest", "pass" if valid else "fail",
            "Matches the exact sealed build44 payload." if valid else "Unexpected or malformed manifest; contents not displayed.")
    archive = image / "runtime.tar.gz"
    archive_ok = unlinked(archive) and archive.is_file() and archive.stat().st_size == EXPECTED_BYTES
    add(report, "archive_size", "pass" if archive_ok else "fail",
        "Archive size matches; size alone is NOT an integrity proof." if archive_ok else "Archive missing, linked or unexpected size.")
    if full_hash and archive_ok and valid:
        print("Reading sealed payload sequentially for SHA256; no extraction or service start.", file=sys.stderr, flush=True)
        value = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                value.update(chunk)
        matched = value.hexdigest() == EXPECTED_SHA
        add(report, "archive_sha256", "pass" if matched else "fail",
            "Sealed payload SHA256 matches." if matched else "SHA256 mismatch; no extraction attempted.")
    else:
        add(report, "archive_sha256", "pending", "Not hashed. --verify-payload reads about 11.1 GiB; nothing is extracted.")
    for filename in ("first_boot.py", "Start-Image.sh", "Show-Credentials.sh"):
        p = image / filename
        ok = unlinked(p) and p.is_file()
        add(report, "entry_" + filename, "pass" if ok else "fail", "Present; not executed." if ok else "Missing or linked entry.")
    if unlinked(repo) and repo.is_dir() and (repo / ".git").is_dir() and unlinked(repo / ".git"):
        add(report, "public_repository", "pass", "Git directory exists at the requested path; origin, revision and functionality NOT verified.")
    else:
        add(report, "public_repository", "pending", "Public repository not confirmed. This probe does not clone or change Git trust settings.")
    add(report, "fresh_instance", "pending", "Use a separate restored instance to verify independent SSH/Jupyter/app credentials; do not initialize the sealed master.")
    add(report, "gpu_and_delivery", "pending", "Real generation, QQ delivery and optional GPU pipelines still require acceptance testing.")
    return finish(report)


def finish(report):
    states = {c["state"] for c in report["checks"]}
    report["status"] = "failed" if "fail" in states else "structure_checked_acceptance_pending"
    report["public_release_approved"] = False
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("/opt/aaa-image-052144"))
    parser.add_argument("--repo", type=Path, default=Path("/root/AstrAutoAnima"))
    parser.add_argument("--verify-payload", action="store_true", help="Stream SHA256 of the existing 11.1 GiB archive; no extraction.")
    args = parser.parse_args(argv)
    try:
        result = probe(args.image_dir, args.repo, args.verify_payload)
    except OSError:
        # Never print arbitrary filesystem exception text, JSON fragments or config values.
        print(json.dumps({"status": "failed", "message": "Filesystem access failed; no recovery or changes attempted.", "public_release_approved": False}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
