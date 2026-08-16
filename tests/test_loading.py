"""Input loading and scope resolution."""

from __future__ import annotations

import pytest

from graphcanon.jsonio import InputError
from graphcanon.loading import (
    check_inputs,
    count_chunks,
    iter_facts,
    iter_occurrences,
    load_scopes,
)


def _occurrences(path):
    return {occ.candidate_entity_id: occ for occ in iter_occurrences(path, load_scopes(path))}


def test_scopes_come_from_the_ledger(mini_input) -> None:
    scopes = load_scopes(mini_input)
    assert scopes["event_alpha"] == ("org_alpha", "ws_alpha")
    assert scopes["event_gamma"] == ("org_beta", "ws_beta")
    assert scopes["event_delta"] == ("org_alpha", "ws_delta")


def test_occurrences_inherit_the_workspace_they_never_declare(mini_input) -> None:
    occurrences = _occurrences(mini_input)
    assert len(occurrences) == 13
    assert occurrences["cent_e001"].workspace_id == "ws_alpha"
    assert occurrences["cent_e004"].workspace_id == "ws_delta"
    assert occurrences["cent_e003"].scope == ("org_beta", "ws_beta")


def test_aliases_keep_their_surface_form(mini_input) -> None:
    occurrences = _occurrences(mini_input)
    assert occurrences["cent_a001"].aliases == ("Organization-CCCCCCCCCCCC",)
    assert occurrences["cent_p001"].aliases == ()


def test_facts_load_with_both_endpoints(mini_input) -> None:
    facts = {fact.candidate_fact_id: fact for fact in iter_facts(mini_input)}
    assert len(facts) == 6
    assert facts["cfact_f001"].subject_candidate_id == "cent_p001"
    assert facts["cfact_f001"].object_candidate_id == "cent_e001"
    assert facts["cfact_f001"].predicate == "WorksAt"


def test_chunk_count(mini_input) -> None:
    assert count_chunks(mini_input) == 5


def test_missing_files_fail_before_any_work(tmp_path) -> None:
    with pytest.raises(InputError, match="missing input files"):
        check_inputs(tmp_path)


def _write(tmp_path, mini_input, **replacements):
    """Copy the mini fixture, overriding named files with raw text."""
    for name in (
        "source_ledger.jsonl",
        "candidate_entities.jsonl",
        "candidate_facts.jsonl",
        "extraction_artifacts.jsonl",
    ):
        text = replacements.get(name, (mini_input / name).read_text(encoding="utf-8"))
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_duplicate_occurrence_id_aborts_the_run(tmp_path, mini_input) -> None:
    original = (mini_input / "candidate_entities.jsonl").read_text(encoding="utf-8")
    doubled = original + original.splitlines(keepends=True)[0]
    path = _write(tmp_path, mini_input, **{"candidate_entities.jsonl": doubled})
    with pytest.raises(InputError, match="duplicate ID"):
        _occurrences(path)


def test_occurrence_from_an_unknown_event_aborts_the_run(tmp_path, mini_input) -> None:
    orphan = (
        '{"aliases":[],"candidate_entity_id":"cent_x","chunk_id":"chunk_zz",'
        '"confidence":0.9,"name":"Organization-999999999999",'
        '"normalized_name":"organization-999999999999","org_id":"org_alpha",'
        '"source_event_id":"event_missing","type":"LegalEntity"}\n'
    )
    text = (mini_input / "candidate_entities.jsonl").read_text(encoding="utf-8") + orphan
    path = _write(tmp_path, mini_input, **{"candidate_entities.jsonl": text})
    with pytest.raises(InputError, match="absent from the ledger"):
        _occurrences(path)


def test_org_contradicting_the_ledger_aborts_the_run(tmp_path, mini_input) -> None:
    # An occurrence claiming an organization its source event does not belong
    # to would let a component cross an isolation boundary undetected.
    lines = (mini_input / "candidate_entities.jsonl").read_text(encoding="utf-8").splitlines(
        keepends=True
    )
    lines[0] = lines[0].replace('"org_id":"org_alpha"', '"org_id":"org_beta"')
    path = _write(tmp_path, mini_input, **{"candidate_entities.jsonl": "".join(lines)})
    with pytest.raises(InputError, match="contradicts ledger"):
        _occurrences(path)


def test_duplicate_ledger_event_aborts_the_run(tmp_path, mini_input) -> None:
    original = (mini_input / "source_ledger.jsonl").read_text(encoding="utf-8")
    doubled = original + original.splitlines(keepends=True)[0]
    path = _write(tmp_path, mini_input, **{"source_ledger.jsonl": doubled})
    with pytest.raises(InputError, match="duplicate source_event_id"):
        load_scopes(path)
