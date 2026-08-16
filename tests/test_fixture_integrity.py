"""The mini fixture must stay a legal input package.

Runs the graders' own tools/validate_inputs.py over it, so the fixture cannot
drift into something their validator would reject.
"""

from __future__ import annotations

import json
import subprocess
import sys


def test_mini_fixture_passes_the_supplied_input_validator(mini_input, tools_dir) -> None:
    result = subprocess.run(
        [sys.executable, str(tools_dir / "validate_inputs.py"), str(mini_input)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["candidate_entities"] == 13
    assert payload["candidate_facts"] == 6
    assert payload["source_ledger_rows"] == 4
    assert payload["chunks"] == 5
