"""Run configuration and its fingerprint."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

# Bump whenever a change to the resolution rules could move an output byte:
# it feeds the fingerprint that tells a reviewer which policy produced which
# artifacts.
ALGORITHM_VERSION = "1.0.0"


class ConfigError(ValueError):
    """An invalid configuration. Raised before any work starts."""


@dataclass(frozen=True)
class Config:
    # --- identity policy (fingerprinted) ---
    # Non-default values here are comparison runs, not supported modes; the
    # measurements that rejected them are in docs/FINDINGS.md §4.
    one_token_person_scope: str = "source_event"
    merge_on_alias: bool = False
    alias_min_support: int = 2
    possible_duplicate_pair_budget: int | None = None
    drop_self_loops: bool = True
    # Sensitivity-analysis knobs only. Nothing is ever discarded for being
    # low-confidence; raising these breaks the coverage invariants.
    min_occurrence_confidence: float = 0.0
    min_fact_confidence: float = 0.0

    # --- operational (NOT fingerprinted) ---
    input_dir: Path = field(default=Path("data/input"))
    output_dir: Path = field(default=Path("submission/output"))
    progress_every: int = 100_000

    # Anything added here must be incapable of changing output bytes, or the
    # fingerprint stops identifying the policy that produced a run.
    _UNFINGERPRINTED = ("input_dir", "output_dir", "progress_every")

    def __post_init__(self) -> None:
        if self.one_token_person_scope not in {"source_event", "global"}:
            raise ConfigError(
                f"one_token_person_scope must be 'source_event' or 'global', "
                f"got {self.one_token_person_scope!r}"
            )
        if self.alias_min_support < 1:
            raise ConfigError("alias_min_support must be >= 1")
        if (
            self.possible_duplicate_pair_budget is not None
            and self.possible_duplicate_pair_budget < 0
        ):
            raise ConfigError("possible_duplicate_pair_budget must be >= 0 or null")
        for name in ("min_occurrence_confidence", "min_fact_confidence"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ConfigError(f"{name} must be within [0, 1], got {value}")

    def policy(self) -> dict[str, Any]:
        skip = set(self._UNFINGERPRINTED)
        data = {f.name: getattr(self, f.name) for f in fields(self) if f.name not in skip}
        data["algorithm_version"] = ALGORITHM_VERSION
        return data

    def fingerprint(self) -> str:
        payload = json.dumps(self.policy(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def describe(self) -> dict[str, Any]:
        return {
            "algorithm_version": ALGORITHM_VERSION,
            "configuration_fingerprint": self.fingerprint(),
            "policy": self.policy(),
        }

    @classmethod
    def from_toml(cls, path: Path, **overrides: Any) -> "Config":
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"cannot read config {path}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

        settings = dict(raw.get("resolution", {}))
        settings.update(raw.get("runtime", {}))
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(settings) - known)
        if unknown:
            raise ConfigError(f"unknown settings in {path}: {unknown}")

        settings.update({k: v for k, v in overrides.items() if v is not None})
        for key in ("input_dir", "output_dir"):
            if key in settings:
                settings[key] = Path(settings[key])
        return cls(**settings)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["input_dir"] = str(self.input_dir)
        data["output_dir"] = str(self.output_dir)
        return data
