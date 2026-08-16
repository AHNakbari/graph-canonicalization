from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
MINI = FIXTURES / "mini"
TOOLS = REPO_ROOT / "tools"

# Support running pytest without installing the package first, and let test
# modules import tests/helpers.py directly.
for extra in (REPO_ROOT / "src", REPO_ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from helpers import load_tool  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def mini_input() -> Path:
    return MINI


@pytest.fixture(scope="session")
def tools_dir() -> Path:
    return TOOLS


@pytest.fixture(scope="session")
def validate_submission_tool() -> ModuleType:
    return load_tool("validate_submission")


@pytest.fixture(scope="session")
def mini_output(tmp_path_factory) -> Path:
    """A complete, clean submission built from the mini fixture."""
    from graphcanon.config import Config
    from graphcanon.pipeline import run

    out = tmp_path_factory.mktemp("mini_output")
    run(Config(input_dir=MINI, output_dir=out))
    return out


@pytest.fixture
def mutable_output(mini_output, tmp_path) -> Path:
    """A private copy of the clean submission, safe to corrupt."""
    target = tmp_path / "output"
    shutil.copytree(mini_output, target)
    return target
