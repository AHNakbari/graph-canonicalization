"""Required scenario 9: behaviour when an optional external dependency fails.

There is no such dependency, and this asserts it mechanically rather than
promising it. Adding an HTTP client or a model call will fail these tests - at
which point the fallback the acceptance criteria ask for has to be designed and
documented.
"""

from __future__ import annotations

import ast
import socket
import sys
from pathlib import Path

import pytest

from graphcanon.config import Config
from graphcanon.pipeline import run

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "graphcanon"


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, inside this package
                continue
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_the_package_imports_only_the_standard_library():
    offenders: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        third_party = _imported_roots(path) - sys.stdlib_module_names - {"graphcanon"}
        if third_party:
            offenders[path.name] = third_party
    assert offenders == {}, f"third-party imports found: {offenders}"


def test_a_full_run_completes_with_networking_disabled(mini_input, tmp_path, monkeypatch):
    """No silent partial output, because there is nothing remote to degrade to."""

    def refuse(*_args, **_kwargs):
        raise OSError("network access is disabled for this test")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    result = run(Config(input_dir=mini_input, output_dir=tmp_path / "out"))
    assert result.counts["entity_assignments.jsonl"] == 13
    assert result.violations == {}


def test_the_report_states_the_absence_of_external_services(mini_output):
    import json

    report = json.loads((mini_output / "quality_report.json").read_text(encoding="utf-8"))
    safety = report["safety"]
    assert safety["external_services_used"] == []
    assert safety["network_access"] is False
    assert safety["remote_model_calls"] == 0
    assert safety["estimated_cost_usd"] == 0.0
    assert "no remote failure mode" in safety["notes"]


@pytest.mark.parametrize("name", ["requirements-dev.txt"])
def test_dependencies_are_pinned_exactly(repo_root, name):
    for line in (repo_root / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line, f"{name}: {line!r} is not pinned"
