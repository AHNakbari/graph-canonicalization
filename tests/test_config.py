"""Configuration and its fingerprint."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphcanon.config import ALGORITHM_VERSION, Config, ConfigError


def test_defaults_encode_the_measured_policy() -> None:
    config = Config()
    assert config.one_token_person_scope == "source_event"
    assert config.merge_on_alias is False
    assert config.possible_duplicate_pair_budget is None  # full enumeration
    assert config.drop_self_loops is True


def test_fingerprint_is_stable_across_instances() -> None:
    assert Config().fingerprint() == Config().fingerprint()


def test_fingerprint_ignores_paths() -> None:
    a = Config(input_dir=Path("data/input"), output_dir=Path("submission/output"))
    b = Config(input_dir=Path("/elsewhere/in"), output_dir=Path("/elsewhere/out"))
    assert a.fingerprint() == b.fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"one_token_person_scope": "global"},
        {"merge_on_alias": True},
        {"alias_min_support": 3},
        {"possible_duplicate_pair_budget": 1000},
        {"drop_self_loops": False},
        {"min_occurrence_confidence": 0.5},
        {"min_fact_confidence": 0.5},
    ],
)
def test_every_policy_knob_moves_the_fingerprint(change: dict) -> None:
    assert Config(**change).fingerprint() != Config().fingerprint()


def test_describe_carries_the_algorithm_version() -> None:
    described = Config().describe()
    assert described["algorithm_version"] == ALGORITHM_VERSION
    assert described["policy"]["algorithm_version"] == ALGORITHM_VERSION
    assert described["configuration_fingerprint"] == Config().fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"one_token_person_scope": "per_chunk"},
        {"alias_min_support": 0},
        {"possible_duplicate_pair_budget": -1},
        {"min_occurrence_confidence": 1.5},
        {"min_fact_confidence": -0.1},
    ],
)
def test_invalid_settings_are_rejected_before_any_work(change: dict) -> None:
    with pytest.raises(ConfigError):
        Config(**change)


def test_toml_round_trip(tmp_path) -> None:
    path = tmp_path / "c.toml"
    path.write_text(
        '[resolution]\nmerge_on_alias = true\nalias_min_support = 4\n'
        '[runtime]\ninput_dir = "in"\n',
        encoding="utf-8",
    )
    config = Config.from_toml(path)
    assert config.merge_on_alias is True
    assert config.alias_min_support == 4
    assert config.input_dir == Path("in")


def test_cli_overrides_beat_the_file(tmp_path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[resolution]\nmerge_on_alias = true\n', encoding="utf-8")
    assert Config.from_toml(path, merge_on_alias=False).merge_on_alias is False
    assert Config.from_toml(path, alias_min_support=9).alias_min_support == 9


def test_absent_overrides_do_not_clobber_the_file(tmp_path) -> None:
    # argparse supplies None for flags the user did not pass; None must mean
    # "not supplied" rather than "set to null".
    path = tmp_path / "c.toml"
    path.write_text('[resolution]\nmerge_on_alias = true\n', encoding="utf-8")
    assert Config.from_toml(path, merge_on_alias=None).merge_on_alias is True


def test_unknown_settings_are_rejected(tmp_path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[resolution]\nmerge_on_alais = true\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown settings"):
        Config.from_toml(path)


def test_shipped_default_config_matches_the_code_defaults(repo_root) -> None:
    # config/default.toml is documentation as much as configuration; if it
    # drifts from the dataclass defaults, the design note starts lying.
    config = Config.from_toml(repo_root / "config" / "default.toml")
    assert config.fingerprint() == Config().fingerprint()
