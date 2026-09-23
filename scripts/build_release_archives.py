#!/usr/bin/env python3
"""Build privacy-checked AstrAutoAnima release archives with stable ZIP metadata."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.5.0-beta.2"
WORKFLOW_VERSION = "0.8.0-beta.1-public"
ZIP_TIME = (2026, 9, 23, 0, 0, 0)
LF_SUFFIXES = {".sh", ".py", ".json", ".yaml", ".yml", ".toml", ".md"}
CRLF_SUFFIXES = {".bat", ".cmd", ".ps1"}


def public_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    paths = [ROOT / line for line in result.stdout.split('\0') if line]
    return sorted(path for path in paths if path.is_file())


def write_zip(destination: Path, entries: list[tuple[Path, str]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source, archive_name in sorted(entries, key=lambda item: item[1]):
            info = zipfile.ZipInfo(archive_name.replace("\\", "/"), ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if source.suffix in {".sh", ".py"} else 0o644) << 16
            payload = source.read_bytes()
            if source.suffix.lower() in LF_SUFFIXES:
                payload = payload.replace(b"\r\n", b"\n")
            elif source.suffix.lower() in CRLF_SUFFIXES:
                payload = payload.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            archive.writestr(info, payload)


def relative_entries(
    files: list[Path],
    base: Path,
    *,
    prefix: str = "",
    exclude_parts: set[str] | None = None,
) -> list[tuple[Path, str]]:
    excluded = exclude_parts or set()
    entries: list[tuple[Path, str]] = []
    for path in files:
        try:
            relative = path.relative_to(base)
        except ValueError:
            continue
        if any(part in excluded for part in relative.parts):
            continue
        name = (Path(prefix) / relative).as_posix() if prefix else relative.as_posix()
        entries.append((path, name))
    return entries


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--web-archive", type=Path, help="Optional separately built public Web ZIP to include in lazy bundle")
    args = parser.parse_args()
    output = args.output.resolve()

    for check in ("privacy_scan.py", "validate_release.py"):
        subprocess.run([sys.executable, str(ROOT / "scripts" / check)], check=True)

    files = public_files()
    plugin_root = ROOT / "plugin" / "astrbot_plugin_comfy_bridge"
    hub_root = ROOT / "hub" / "service"
    workflow_root = ROOT / "comfyui"

    archives: dict[str, list[tuple[Path, str]]] = {
        f"astrbot_plugin_comfy_bridge-{VERSION}.zip": relative_entries(
            files, plugin_root, exclude_parts={"tests"}
        ),
        f"astr_auto_anima_hub_service-{VERSION}.zip": relative_entries(
            files, hub_root, exclude_parts={"tests"}
        ),
        f"Anima_Workflow_Pack-{WORKFLOW_VERSION}.zip": relative_entries(
            files,
            workflow_root,
            prefix=f"Anima_Workflow_Pack-{WORKFLOW_VERSION}",
        ),
    }

    tool_paths = [
        path
        for path in files
        if path.is_relative_to(ROOT / "tools")
        or path.is_relative_to(ROOT / "examples")
        or path in {
            ROOT / "docs" / "TOOLS.md",
            ROOT / "docs" / "EASY_INSTALL.md",
            ROOT / "一键部署_AstrAutoAnima.bat",
            ROOT / "一键部署_AstrAutoAnima.sh",
            ROOT / "Deploy-Windows.cmd",
            ROOT / "Deploy-Linux.sh",
        }
    ]
    archives[f"AstrAutoAnima-tools-{VERSION}.zip"] = [
        (path, path.relative_to(ROOT).as_posix()) for path in tool_paths
    ]

    source_prefix = f"AstrAutoAnima-{VERSION}"
    source_entries = [
        (path, (Path(source_prefix) / path.relative_to(ROOT)).as_posix())
        for path in files
    ]
    archives[f"AstrAutoAnima-{VERSION}-source.zip"] = source_entries
    lazy_roots = {"plugin", "hub", "comfyui", "tools", "examples", "docs"}
    lazy_root_files = {
        ".astr_auto_anima_public_root",
        ".gitattributes",
        "LICENSE",
        "README.md",
        "RELEASE_NOTES.md",
        "THIRD_PARTY_NOTICES.md",
        "release-manifest.json",
        "一键部署_AstrAutoAnima.bat",
        "一键部署_AstrAutoAnima.sh",
        "Deploy-Windows.cmd",
        "Deploy-Linux.sh",
        "artwork-manifest.json",
    }
    lazy_files = []
    for path in files:
        relative = path.relative_to(ROOT)
        if relative.as_posix() in lazy_root_files or relative.parts[0] in lazy_roots:
            if "tests" not in relative.parts:
                lazy_files.append(path)
    for platform in ('windows', 'linux'):
        incompatible = {'.sh'} if platform == 'windows' else {'.cmd', '.bat', '.ps1'}
        other_plan = 'deployment-plan.linux.json' if platform == 'windows' else 'deployment-plan.windows.json'
        archives[f'AstrAutoAnima-lazy-bundle-{platform}-{VERSION}.zip'] = [
            (path, (Path(source_prefix) / path.relative_to(ROOT)).as_posix())
            for path in lazy_files if path.suffix.lower() not in incompatible and path.name != other_plan
        ]
    archives[f'AstrAutoAnima-artwork-{VERSION}.zip'] = [
        (path, path.relative_to(ROOT).as_posix()) for path in files
        if path.is_relative_to(ROOT / 'clients/flutter/assets')
        or path in {ROOT / 'artwork-manifest.json', ROOT / 'docs/ARTWORK.md'}
    ]

    output.mkdir(parents=True, exist_ok=True)
    built: list[Path] = []
    for filename, entries in archives.items():
        if not entries:
            raise RuntimeError(f"Archive would be empty: {filename}")
        destination = output / filename
        write_zip(destination, entries)
        if 'lazy-bundle' in filename and args.web_archive:
            with zipfile.ZipFile(args.web_archive) as web, zipfile.ZipFile(destination, 'a', compression=zipfile.ZIP_DEFLATED) as bundle:
                if 'index.html' not in web.namelist():
                    raise ValueError('Web archive must have index.html at root')
                for member in web.infolist():
                    name = member.filename.replace('\\', '/')
                    if member.is_dir():
                        continue
                    if name.startswith('/') or ':' in name or '..' in Path(name).parts or name.endswith(('.env', '.map')):
                        raise ValueError('Unsafe Web archive entry')
                    info = zipfile.ZipInfo(f'{source_prefix}/hub/service/web/{name}', ZIP_TIME)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    bundle.writestr(info, web.read(member))
        built.append(destination)
        print(f"BUILT {destination.name} ({destination.stat().st_size:,} bytes)")

    checksums = output / "SHA256SUMS.txt"
    checksum_files = sorted(path for path in output.iterdir() if path.is_file()
                            and (path.suffix in {".zip", ".apk"} or path.name == "README.md"))
    lines = [f"{sha256(path)}  {path.name}" for path in checksum_files]
    checksums.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"BUILT {checksums.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
