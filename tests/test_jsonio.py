"""Deterministic serialisation: key order, whitespace, newline translation."""

from __future__ import annotations

import pytest

from graphcanon.jsonio import (
    InputError,
    JsonlWriter,
    dumps,
    read_jsonl,
    sha256_file,
    write_json,
)


def test_dumps_sorts_keys_and_stays_compact() -> None:
    assert dumps({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_dumps_is_insensitive_to_insertion_order() -> None:
    assert dumps({"z": 1, "y": [3, 2], "x": {"n": 1, "m": 2}}) == dumps(
        {"x": {"m": 2, "n": 1}, "y": [3, 2], "z": 1}
    )


def test_writer_emits_lf_endings_on_every_platform(tmp_path) -> None:
    path = tmp_path / "out.jsonl"
    with JsonlWriter(path) as writer:
        writer.write({"b": 1, "a": 2})
        writer.write({"a": 3})
    assert path.read_bytes() == b'{"a":2,"b":1}\n{"a":3}\n'


def test_writer_creates_missing_parents_and_counts_rows(tmp_path) -> None:
    path = tmp_path / "nested" / "deeper" / "out.jsonl"
    with JsonlWriter(path) as writer:
        assert writer.write_all([{"i": i} for i in range(5)]) == 5
    assert path.is_file()


def test_identical_content_hashes_identically(tmp_path) -> None:
    rows = [{"b": i, "a": str(i)} for i in range(50)]
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    with JsonlWriter(first) as writer:
        writer.write_all(rows)
    with JsonlWriter(second) as writer:
        writer.write_all([{"a": row["a"], "b": row["b"]} for row in rows])
    assert sha256_file(first) == sha256_file(second)


def test_read_jsonl_skips_blank_lines_and_reports_line_numbers(tmp_path) -> None:
    path = tmp_path / "in.jsonl"
    path.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")
    assert [(n, row["a"]) for n, row in read_jsonl(path)] == [(1, 1), (3, 2)]


def test_malformed_input_aborts_rather_than_skipping(tmp_path) -> None:
    path = tmp_path / "in.jsonl"
    path.write_text('{"a":1}\nnot json\n', encoding="utf-8")
    with pytest.raises(InputError, match="in.jsonl:2"):
        list(read_jsonl(path))


def test_missing_input_is_an_input_error(tmp_path) -> None:
    with pytest.raises(InputError, match="cannot open"):
        list(read_jsonl(tmp_path / "absent.jsonl"))


def test_write_json_is_readable_and_stable(tmp_path) -> None:
    path = tmp_path / "report.json"
    write_json(path, {"b": 1, "a": {"d": 4, "c": 3}})
    text = path.read_text(encoding="utf-8")
    assert text.startswith('{\n  "a": {')
    assert text.endswith("}\n")
