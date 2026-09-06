from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_DATA_ROOT = Path(
    "/workspace/astrbot-runtime/data/plugin_data/astrbot_plugin_comfy_bridge"
)
DEFAULT_CHARACTERS_URL = (
    "https://raw.githubusercontent.com/tcpassos/"
    "mcp-danbooru-characters/master/data/characters.jsonl"
)
DEFAULT_TRANSLATIONS_URL = (
    "https://raw.githubusercontent.com/ffdkj/"
    "ffdkj-Danbooru_Tag-Chinese-English-Translation-Table/main/tag.sqlite"
)


def _human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def _download(url: str, destination: Path, *, force: bool = False) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 0 and not force:
        print(f"复用已下载文件：{destination} ({_human_size(destination.stat().st_size)})")
        return destination

    partial = destination.with_name(destination.name + ".part")
    if force and partial.exists():
        partial.unlink()
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "AstrAutoAnima-character-dictionary-installer/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
        print(f"继续下载：{destination.name}，已有 {_human_size(offset)}")
    else:
        print(f"开始下载：{destination.name}")

    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"下载失败：{url}\n{exc}") from exc

    with response:
        status = getattr(response, "status", 200)
        append = bool(offset and status == 206)
        if offset and not append:
            offset = 0
        total_header = response.headers.get("Content-Length")
        total = int(total_header) + offset if total_header else 0
        mode = "ab" if append else "wb"
        received = offset
        next_report = received + 4 * 1024 * 1024
        with partial.open(mode) as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                received += len(chunk)
                if received >= next_report:
                    suffix = f" / {_human_size(total)}" if total else ""
                    print(f"  已下载 {_human_size(received)}{suffix}")
                    next_report = received + 4 * 1024 * 1024

    if not partial.is_file() or partial.stat().st_size == 0:
        raise RuntimeError(f"下载结果为空：{url}")
    partial.replace(destination)
    print(f"下载完成：{destination} ({_human_size(destination.stat().st_size)})")
    return destination


def _validate_characters(path: Path, *, minimum_records: int = 1000) -> int:
    count = 0
    with path.open("r", encoding="utf-8-sig") as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"角色数据第 {number} 行不是有效 JSON：{exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"角色数据第 {number} 行不是对象")
            if not str(value.get("name", value.get("tag", ""))).strip():
                raise RuntimeError(f"角色数据第 {number} 行缺少 name/tag")
            count += 1
    if count < minimum_records:
        raise RuntimeError(f"角色数据只有 {count} 条，低于最低要求 {minimum_records} 条")
    return count


def _validate_translations(path: Path, *, minimum_records: int = 1000) -> int:
    with path.open("rb") as source:
        header = source.read(16)
    if header != b"SQLite format 3\x00":
        raise RuntimeError("中文翻译文件不是有效的 SQLite 数据库")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(tags)")
        }
        required = {"name", "category", "cn_name"}
        if not required.issubset(columns):
            raise RuntimeError(
                "中文翻译数据库 tags 表缺少字段："
                + ", ".join(sorted(required - columns))
            )
        count = int(
            connection.execute(
                "SELECT count(*) FROM tags "
                "WHERE category = 4 AND cn_name IS NOT NULL AND trim(cn_name) <> ''"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    if count < minimum_records:
        raise RuntimeError(f"中文角色译名只有 {count} 条，低于最低要求 {minimum_records} 条")
    return count


def _backup_output(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.stem}.backup_{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and build AstrAutoAnima's local Chinese character dictionary."
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--characters-url", default=DEFAULT_CHARACTERS_URL)
    parser.add_argument("--translations-url", default=DEFAULT_TRANSLATIONS_URL)
    parser.add_argument("--characters-file", type=Path)
    parser.add_argument("--translations-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Download source files again even when the local cache exists.",
    )
    args = parser.parse_args()

    data_root = args.data_root.expanduser().resolve()
    source_root = data_root / "character_dictionary_sources"
    output = (args.output or data_root / "character_dictionary.json").expanduser().resolve()
    source_root.mkdir(parents=True, exist_ok=True)

    print("AstrAutoAnima 本地中文角色词典安装器")
    print("角色结构数据：tcpassos/mcp-danbooru-characters（MIT）")
    print("中文翻译数据：ffdkj Danbooru 中英翻译表（由本机直接下载，不随插件分发）")

    characters = (
        args.characters_file.expanduser().resolve()
        if args.characters_file
        else _download(
            args.characters_url,
            source_root / "characters.jsonl",
            force=args.force_download,
        )
    )
    translations = (
        args.translations_file.expanduser().resolve()
        if args.translations_file
        else _download(
            args.translations_url,
            source_root / "tag.sqlite",
            force=args.force_download,
        )
    )
    if not characters.is_file():
        raise SystemExit(f"角色数据不存在：{characters}")
    if not translations.is_file():
        raise SystemExit(f"中文翻译数据库不存在：{translations}")

    print("检查源数据……")
    character_count = _validate_characters(characters)
    translation_count = _validate_translations(translations)
    print(f"角色结构：{character_count} 条；中文角色译名：{translation_count} 条")

    builder = Path(__file__).with_name("build_character_dictionary.py")
    if not builder.is_file():
        raise SystemExit(f"找不到词典生成器：{builder}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(output.name + ".new")
    command = [
        sys.executable,
        str(builder),
        "--characters-jsonl",
        str(characters),
        "--translation-sqlite",
        str(translations),
        "--output",
        str(temporary_output),
    ]
    subprocess.run(command, check=True)
    built_count = len(json.loads(temporary_output.read_text(encoding="utf-8"))["characters"])
    if built_count < 1000:
        temporary_output.unlink(missing_ok=True)
        raise SystemExit(f"生成后的词典只有 {built_count} 条，拒绝覆盖现有词典")

    backup = _backup_output(output)
    temporary_output.replace(output)
    print(f"安装完成：{output}")
    print(f"可识别角色条目：{built_count}")
    if backup:
        print(f"旧词典备份：{backup}")
    print("插件配置中启用“中文角色名词典”即可；词典会在下一次请求时自动读取。")


if __name__ == "__main__":
    main()
