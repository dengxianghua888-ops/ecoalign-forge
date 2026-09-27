"""SIGKILL across commit boundaries, with an external durable transport call log."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ecoalign_forge.engine.kernel import SynthesisKernel
from ecoalign_forge.policy.models import PolicyPack
from ecoalign_forge.runtime.journal import Journal
from tests.test_iteration_b_kernel import RecordedTransport
from tests.test_iteration_b_policy import pack_data

CHILD = """
import asyncio, os, signal, sys
from pathlib import Path
from ecoalign_forge.engine.kernel import SynthesisKernel
from ecoalign_forge.policy.models import PolicyPack
from ecoalign_forge.schemas.kernel import RunConfig
from tests.test_iteration_b_kernel import RecordedTransport
from tests.test_iteration_b_policy import pack_data
root=Path(sys.argv[1]); point=sys.argv[2]
def hook(event,data):
    key=event+(':'+data['stage'] if event=='stage_committed' else '')
    if key==point: os.kill(os.getpid(),signal.SIGKILL)
p=PolicyPack.model_validate(pack_data())
k=SynthesisKernel(data_dir=root/'data',datasets_dir=root/'datasets',transport=RecordedTransport(p,call_log=root/'calls.log'),hook=hook)
asyncio.run(k.run(p,RunConfig(execution_mode='mock',num_samples=1,request_timeout=.3)))
"""


@pytest.mark.parametrize(
    "point",
    [
        "initialized",
        "before_request_intent",
        "quota_acquired",
        "request_intent_committed",
        "before_response_commit",
        "response_committed",
        "attempt_finished",
        "generation_committed",
        "stage_committed:moderator",
        "stage_committed:judge",
        "stage_committed:review",
        "stage_committed:gate",
        "case_committed",
        "before_export",
        "export_content_committed",
        "export_committed",
    ],
)
def test_hard_kill_and_resume(tmp_path, point):
    child = subprocess.run(
        [sys.executable, "-c", CHILD, str(tmp_path), point],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode == -9, child.stderr
    run_dir = next((tmp_path / "data/mock/runs").iterdir())
    journal = Journal(run_dir)
    attempts_before = journal.attempts()
    saved = {a["id"] for a in attempts_before if a["result"]}
    journal.close()
    p = PolicyPack.model_validate(pack_data())
    transport = RecordedTransport(p, call_log=tmp_path / "calls.log")
    kernel = SynthesisKernel(
        data_dir=tmp_path / "data", datasets_dir=tmp_path / "datasets", transport=transport
    )
    result = asyncio.run(kernel.resume(run_dir))
    if point in {"request_intent_committed", "before_response_commit"}:
        assert result["status"] == "paused" and not transport.calls
        assert result["counts"]["in_progress"] == 1
        result = asyncio.run(
            kernel.resume(
                run_dir, unknown_decisions={a: "retry" for a in result["unknown_attempts"]}
            )
        )
    assert result["status"] == "completed" and result["counts"]["dpo_pairs"] == 1
    assert not saved.intersection(aid for _, aid, _ in transport.calls)
    before = Path(result["output_path"]).read_bytes()
    again = asyncio.run(kernel.resume(run_dir))
    assert again["counts"] == result["counts"] and Path(again["output_path"]).read_bytes() == before
    journal = Journal(run_dir)
    assert len(journal.pairs()) == 1
    for request in journal.db.execute("SELECT id FROM requests"):
        successful = [a for a in journal.attempts(request[0]) if a["state"] == "succeeded"]
        assert len(successful) == 1
    journal.close()
    assert len(json.loads(before.splitlines()[0])["lineage"]["policy_hash"]) == 64
