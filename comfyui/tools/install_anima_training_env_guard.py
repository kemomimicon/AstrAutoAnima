#!/usr/bin/env python3
"""Install the single-GPU Accelerate environment guard on an AAA server.

The tool patches the two process boundaries identified in the 2026-09-05
incident report.  It is deliberately fail-closed: an unexpected runner shape
is never rewritten.  Every changed file receives a timestamped sibling backup.
"""
from __future__ import annotations

import argparse
import ast
import shutil
from datetime import datetime, timezone
from pathlib import Path


GUARD_MODULE = '''"""AstrAutoAnima single-GPU child environment guard."""
from __future__ import annotations

import os
from collections.abc import Mapping

DISTRIBUTED_ENV_KEYS = frozenset({
    "RANK", "LOCAL_RANK", "WORLD_SIZE", "LOCAL_WORLD_SIZE",
    "MASTER_ADDR", "MASTER_PORT", "GROUP_RANK", "ROLE_RANK", "NODE_RANK",
    "TORCHELASTIC_RUN_ID", "TORCHELASTIC_RESTART_COUNT",
    "ACCELERATE_USE_FSDP", "ACCELERATE_USE_DEEPSPEED",
    "PMI_RANK", "PMI_SIZE", "PMIX_RANK",
    "OMPI_COMM_WORLD_RANK", "OMPI_COMM_WORLD_LOCAL_RANK",
    "OMPI_COMM_WORLD_SIZE", "SLURM_PROCID", "SLURM_LOCALID", "SLURM_NTASKS",
})


def build_single_gpu_train_env(
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    for key in DISTRIBUTED_ENV_KEYS:
        env.pop(key, None)
    if extra_env:
        conflicts = sorted(DISTRIBUTED_ENV_KEYS.intersection(extra_env))
        if conflicts:
            raise ValueError(
                "single-GPU training cannot accept distributed env keys: "
                + ", ".join(conflicts)
            )
        env.update(extra_env)
    env["ANIMA_EXECUTION_MODE"] = "single_gpu"
    env["ANIMA_LAUNCH_ENV_VERSION"] = "1"
    return env


def scrub_current_process_for_single_gpu() -> tuple[str, ...]:
    if os.environ.get("ANIMA_EXECUTION_MODE", "single_gpu") != "single_gpu":
        return ()
    removed = tuple(sorted(key for key in DISTRIBUTED_ENV_KEYS if key in os.environ))
    for key in removed:
        os.environ.pop(key, None)
    if removed:
        print(
            "[anima-wrapper] removed inherited distributed env keys: "
            + ", ".join(removed),
            flush=True,
        )
    return removed
'''

RUNNER_IMPORT = (
    "\n# AAA_ACCELERATE_ENV_GUARD_V1\n"
    "from anima_process_env_guard import build_single_gpu_train_env\n"
)
WRAPPER_IMPORT = (
    "\n# AAA_ACCELERATE_ENV_GUARD_V1\n"
    "from anima_process_env_guard import scrub_current_process_for_single_gpu\n"
    "scrub_current_process_for_single_gpu()\n"
)


def _backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.before_aaa_env_guard_{stamp}")
    shutil.copy2(path, backup)
    return backup


def _preamble_offset(source: str) -> int:
    tree = ast.parse(source)
    body = list(tree.body)
    index = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        index = 1
    while index < len(body) and isinstance(body[index], ast.ImportFrom) and body[index].module == "__future__":
        index += 1
    if index == 0:
        return 0
    lines = source.splitlines(keepends=True)
    return sum(len(line) for line in lines[: body[index - 1].end_lineno])


def _character_column(line: str, utf8_column: int) -> int:
    """Translate CPython AST's UTF-8 byte column into a string offset."""
    prefix = line.encode("utf-8")[:utf8_column]
    return len(prefix.decode("utf-8"))


def _insert_popen_env(source: str, call: ast.Call) -> str:
    lines = source.splitlines(keepends=True)
    closing_line = lines[call.end_lineno - 1]
    closing_column = _character_column(closing_line, call.end_col_offset) - 1
    if closing_column < 0 or closing_line[closing_column] != ")":
        raise RuntimeError("could not locate the Popen closing parenthesis")

    close_offset = sum(len(line) for line in lines[: call.end_lineno - 1]) + closing_column
    before_close = source[:close_offset]
    body_end = len(before_close.rstrip())
    if body_end == 0:
        raise RuntimeError("could not locate the final Popen argument")

    if call.lineno == call.end_lineno:
        separator = "" if before_close[body_end - 1] == "," else ","
        insertion = separator + " env=build_single_gpu_train_env()"
        return source[:body_end] + insertion + source[body_end:]

    closing_indent = closing_line[:closing_column]
    if closing_indent.strip():
        raise RuntimeError("unexpected content before the Popen closing parenthesis")
    newline = "\r\n" if "\r\n" in source else "\n"
    separator = "" if before_close[body_end - 1] == "," else ","
    argument_indent = closing_indent + "    "
    insertion = (
        separator
        + newline
        + argument_indent
        + "env=build_single_gpu_train_env(),"
        + newline
        + closing_indent
    )
    return source[:body_end] + insertion + source[close_offset:]


def patch_runner(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if "AAA_ACCELERATE_ENV_GUARD_V1" in source:
        return False
    tree = ast.parse(source)
    candidates: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "Popen":
            continue
        if any(keyword.arg == "env" for keyword in node.keywords):
            continue
        candidates.append(node)
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one unguarded subprocess.Popen in {path}, found {len(candidates)}"
        )
    call = candidates[0]
    patched = _insert_popen_env(source, call)
    offset = _preamble_offset(patched)
    patched = patched[:offset] + RUNNER_IMPORT + patched[offset:]
    ast.parse(patched)
    _backup(path)
    path.write_text(patched, encoding="utf-8", newline="\n")
    return True


def patch_wrapper(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if "AAA_ACCELERATE_ENV_GUARD_V1" in source:
        return False
    offset = _preamble_offset(source)
    patched = source[:offset] + WRAPPER_IMPORT + source[offset:]
    ast.parse(patched)
    _backup(path)
    path.write_text(patched, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runner",
        type=Path,
        default=Path("/workspace/ComfyUI/custom_nodes/ComfyUI-AnimaBatchLoraTrainer/train_runner.py"),
    )
    parser.add_argument(
        "--wrapper",
        type=Path,
        default=Path("/workspace/anima_train_network_wrapper.py"),
    )
    parser.add_argument(
        "--guard-module",
        type=Path,
        default=Path("/workspace/anima_process_env_guard.py"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    for path in (args.runner, args.wrapper):
        if not path.is_file():
            raise SystemExit(f"missing required file: {path}")
        ast.parse(path.read_text(encoding="utf-8"))

    if args.check:
        runner_ok = "AAA_ACCELERATE_ENV_GUARD_V1" in args.runner.read_text(encoding="utf-8")
        wrapper_ok = "AAA_ACCELERATE_ENV_GUARD_V1" in args.wrapper.read_text(encoding="utf-8")
        module_ok = args.guard_module.is_file()
        print(f"runner_guard={runner_ok} wrapper_guard={wrapper_ok} module={module_ok}")
        return 0 if runner_ok and wrapper_ok and module_ok else 1

    args.guard_module.write_text(GUARD_MODULE, encoding="utf-8", newline="\n")
    ast.parse(args.guard_module.read_text(encoding="utf-8"))
    runner_changed = patch_runner(args.runner)
    wrapper_changed = patch_wrapper(args.wrapper)
    print(
        f"installed: runner_changed={runner_changed} "
        f"wrapper_changed={wrapper_changed} module={args.guard_module}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
