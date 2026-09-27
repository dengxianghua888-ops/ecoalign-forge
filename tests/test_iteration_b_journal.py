"""Durability, ownership and conservation of the authoritative journal."""

import json
import subprocess
import sys

import pytest

from ecoalign_forge.runtime.journal import Journal


def init(path):
    j = Journal(path)
    j.initialize(
        {
            "run_id": "one",
            "execution_mode": "mock",
            "policy_hash": "hash",
            "policy": {"language": "en"},
        },
        [{"request_item_id": str(i), "batch_index": 0} for i in range(2)],
    )
    return j


def test_rebuild_counts_and_immutable_stages(tmp_path):
    j = init(tmp_path)
    j.set_case("0", state="in_progress", source={"source_id": "0", "content": "hello"})
    assert j.counts().in_progress == 1
    j.commit_stage("0", "moderator", {"value": "a"})
    j.commit_stage("0", "moderator", {"value": "a"})
    with pytest.raises(ValueError):
        j.commit_stage("0", "moderator", {"value": "b"})
    j.commit_case("0", "accepted", "no_signal")
    j.commit_case("1", "excluded", "invalid_evidence")
    j.close()
    with_j = Journal(tmp_path)
    counts = with_j.counts()
    assert counts.completed == 2 and counts.accepted_cases == counts.excluded_cases == 1
    assert counts.no_signal == 1 and counts.moderated == 1
    with_j.close()


def test_unknown_requires_explicit_choice_and_keeps_attempt(tmp_path):
    j = init(tmp_path)
    j.request("q", "judge", ["0"], {"messages": []})
    aid = j.start_attempt("q", ".01")
    j.close()
    j = Journal(tmp_path)
    with j.owner():
        j.recover_inflight()
        assert j.unknown()[0]["id"] == aid
        j.resolve_unknown({})
        assert len(j.unknown()) == 1
        with pytest.raises(ValueError):
            j.resolve_unknown({"not-real": "retry"})
        j.resolve_unknown({aid: "retry"})
        assert not j.unknown() and j.attempts()[0]["reservation"] == ".01"
        assert j.start_attempt("q", ".01") == "q:2"
    j.close()


def test_lock_excludes_other_process_and_releases(tmp_path):
    j = init(tmp_path)
    script = 'from ecoalign_forge.runtime.journal import Journal; import sys; j=Journal(sys.argv[1]);\nwith j.owner(): print("owned")'
    with j.owner():
        child = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True
        )
        assert child.returncode != 0 and "RunBusyError" in child.stderr
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True
    )
    assert child.returncode == 0 and "owned" in child.stdout
    j.close()


def test_export_recovers_after_content_commit(tmp_path):
    j = init(tmp_path / "run")
    j.hook = lambda event, data: (
        (_ for _ in ()).throw(RuntimeError("crash"))
        if event == "export_content_committed"
        else None
    )
    with pytest.raises(RuntimeError):
        j.export(tmp_path / "datasets")
    j.hook = lambda *_: None
    first = j.export(tmp_path / "datasets")
    assert first == j.export(tmp_path / "datasets")
    assert json.loads((first.parent / "manifest.json").read_text())["pairs"] == 0
    assert len(list((tmp_path / "datasets").rglob("pairs.jsonl"))) == 1
    j.close()
