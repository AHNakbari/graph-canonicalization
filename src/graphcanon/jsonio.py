"""Deterministic JSONL reading and writing."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator

_CHUNK = 1 << 20


class InputError(RuntimeError):
    """A malformed or unreadable input file. Always fatal - never skipped."""


def read_jsonl(path: Path) -> Iterator[tuple[int, dict]]:
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot open {path}: {exc}") from exc
    with handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise InputError(f"{path.name}:{line_no}: invalid JSON: {exc}") from exc


def dumps(obj: Any) -> str:
    # sort_keys and compact separators are what make output bytes a function of
    # content alone. The two-run hash agreement check depends on both.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class JsonlWriter:
    __slots__ = ("path", "_handle", "count")

    def __init__(self, path: Path) -> None:
        self.path = path
        self.count = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="" suppresses Python's newline translation, so a Windows run
        # produces byte-identical output to a Linux one.
        self._handle = path.open("w", encoding="utf-8", newline="")

    def write(self, obj: Any) -> None:
        self._handle.write(dumps(obj))
        self._handle.write("\n")
        self.count += 1

    def write_raw(self, line: str) -> None:
        # Bypasses json.dumps. Only safe for the unresolved-pair enumerator,
        # whose rows are built solely from identifiers that loading.py has
        # already checked against ENTITY_ID_RE. Anything that could contain a
        # quote, a backslash or a control character must use write().
        self._handle.write(line)
        self._handle.write("\n")
        self.count += 1

    def write_all(self, objs: Iterable[Any]) -> int:
        for obj in objs:
            self.write(obj)
        return self.count

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "JsonlWriter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        json.dump(obj, handle, sort_keys=True, indent=2, ensure_ascii=False)
        handle.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    return os.path.getsize(path)
