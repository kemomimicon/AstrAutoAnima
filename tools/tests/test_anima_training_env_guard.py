from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from tools.install_anima_training_env_guard import GUARD_MODULE, patch_runner, patch_wrapper


def test_patches_runner_and_wrapper_idempotently(tmp_path: Path) -> None:
    runner = tmp_path / "train_runner.py"
    wrapper = tmp_path / "wrapper.py"
    runner.write_text(
        "import subprocess\n\ndef launch(command):\n"
        "    return subprocess.Popen(command, cwd='/tmp')\n",
        encoding="utf-8",
    )
    wrapper.write_text(
        '"""wrapper"""\nfrom __future__ import annotations\nimport torch\n',
        encoding="utf-8",
    )

    assert patch_runner(runner)
    assert patch_wrapper(wrapper)
    assert not patch_runner(runner)
    assert not patch_wrapper(wrapper)
    runner_source = runner.read_text(encoding="utf-8")
    wrapper_source = wrapper.read_text(encoding="utf-8")
    ast.parse(runner_source)
    ast.parse(wrapper_source)
    assert "env=build_single_gpu_train_env()" in runner_source
    assert wrapper_source.index("scrub_current_process_for_single_gpu()") < wrapper_source.index("import torch")


def test_patches_multiline_popen_with_trailing_comma(tmp_path: Path) -> None:
    runner = tmp_path / "train_runner.py"
    runner.write_text(
        "import subprocess\n\ndef launch(command):\n"
        "    return subprocess.Popen(\n"
        "        command,\n"
        "        text=True,\n"
        "        bufsize=1,\n"
        "    )\n",
        encoding="utf-8",
    )

    assert patch_runner(runner)
    source = runner.read_text(encoding="utf-8")
    ast.parse(source)
    assert "bufsize=1,\n        env=build_single_gpu_train_env()," in source


def test_patches_popen_when_ast_column_contains_non_ascii(tmp_path: Path) -> None:
    runner = tmp_path / "train_runner.py"
    runner.write_text(
        "import subprocess\n\ndef launch(command):\n"
        "    return subprocess.Popen(command, cwd='训练目录')\n",
        encoding="utf-8",
    )

    assert patch_runner(runner)
    source = runner.read_text(encoding="utf-8")
    ast.parse(source)
    assert "cwd='训练目录', env=build_single_gpu_train_env()" in source


def test_guard_preserves_device_and_removes_rank(tmp_path: Path, monkeypatch) -> None:
    module_path = tmp_path / "anima_process_env_guard.py"
    module_path.write_text(GUARD_MODULE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("aaa_test_guard", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("LOCAL_RANK", "0")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2")

    env = module.build_single_gpu_train_env()

    assert "LOCAL_RANK" not in env
    assert env["CUDA_VISIBLE_DEVICES"] == "2"
    assert env["ANIMA_EXECUTION_MODE"] == "single_gpu"
