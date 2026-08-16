"""Shared test utilities.

Kept out of conftest.py because pytest loads conftest as a top-level plugin,
not as a package member, so `from .conftest import ...` does not work.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"


def load_tool(name: str) -> ModuleType:
    """Import one of the supplied acceptance tools as a module.

    Several tests assert that our behaviour matches the graders' rather than
    merely matching a copy of their rules that we wrote down ourselves.
    """
    path = TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_tool_{name}", path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_tool(name: str, *args: str) -> subprocess.CompletedProcess:
    """Run a supplied acceptance tool as a subprocess."""
    return subprocess.run(
        [sys.executable, str(TOOLS / f"{name}.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
