"""Offline release evidence, using the same prompts/parsers/storage as real runs."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Scripts execute from a checkout or extracted sdist, including controlled test fixtures.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

from tests.test_iteration_b_kernel import RecordedTransport
from tests.test_iteration_b_policy import pack_data

from ecoalign_forge.engine.kernel import SynthesisKernel, code_identity
from ecoalign_forge.policy.builtin import builtin_pack
from ecoalign_forge.policy.models import PolicyPack
from ecoalign_forge.runtime.journal import Journal
from ecoalign_forge.schemas.kernel import RunConfig


async def scenarios(output):
    results = {}
    demo = SynthesisKernel(data_dir=output / "data", datasets_dir=output / "datasets")
    results["builtin_demo"] = await demo.run(builtin_pack(), RunConfig())
    assert results["builtin_demo"]["counts"]["dpo_pairs"] == 3
    for language, text in [("en", "Contact raven"), ("ar", "تواصل مع رافن 🐦")]:
        data = pack_data()
        data["language"] = language
        pack = PolicyPack.model_validate(data)
        kernel = SynthesisKernel(
            data_dir=output / "data",
            datasets_dir=output / "datasets",
            transport=RecordedTransport(pack, text=text),
        )
        result = await kernel.run(pack, RunConfig(execution_mode="mock", num_samples=2))
        assert result["counts"]["dpo_pairs"] == 2 and result["status"] == "completed"
        results[language] = result
    pack = PolicyPack.model_validate(pack_data())
    paused = SynthesisKernel(
        data_dir=output / "data",
        datasets_dir=output / "datasets",
        transport=RecordedTransport(pack, corrupt_stage="judge"),
    )
    results["unknown"] = await paused.run(pack, RunConfig(execution_mode="mock", num_samples=1))
    assert results["unknown"]["exit_code"] == 4
    failed = SynthesisKernel(
        data_dir=output / "data",
        datasets_dir=output / "datasets",
        transport=RecordedTransport(
            pack,
            reviewer=lambda _: dict(
                status="abstain", reason="controlled missing material", corrected=None
            ),
        ),
    )
    results["failed"] = await failed.run(pack, RunConfig(execution_mode="mock", num_samples=1))
    assert results["failed"]["exit_code"] == 1
    for result in results.values():
        journal = Journal.readonly(Path(result["run_dir"]))
        try:
            assert journal.counts().model_dump() == result["counts"]
            for pair in journal.pairs():
                assert (
                    json.loads(pair["chosen"])
                    == journal.stage(pair["source_case_id"], "gate")["final"]["evaluation"]
                )
        finally:
            journal.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-fault-tests", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with patch(
        "litellm.acompletion", AsyncMock(side_effect=AssertionError("external LLM forbidden"))
    ):
        results = asyncio.run(scenarios(output))
    gates = {}
    if not args.skip_fault_tests:
        for name, files in [
            ("recovery", ["tests/test_iteration_b_recovery.py"]),
            (
                "budget-quota",
                ["tests/test_iteration_b_control.py", "tests/test_iteration_b_kernel.py"],
            ),
        ]:
            command = [
                sys.executable,
                "-m",
                "pytest",
                *files,
                "-q",
                "--disable-warnings",
                f"--junitxml={output / (name + '.xml')}",
            ]
            checked = subprocess.run(command, capture_output=True, text=True)
            (output / (name + ".log")).write_text(checked.stdout + checked.stderr)
            if checked.returncode:
                raise RuntimeError(name + " acceptance failed; see saved report")
            gates[name] = dict(
                passed=True, command=["python", "-m", "pytest", *files], log=name + ".log"
            )
    manifest_paths = sorted((output / "datasets").rglob("manifest.json"))
    hashes = {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in manifest_paths
    }
    summary = dict(
        version="0.3.0a1",
        code=code_identity(),
        scenarios=results,
        gates=gates,
        manifest_sha256=hashes,
        external_llm_calls=0,
        training_performed=False,
        scope="deterministic engineering only; model semantics and multilingual performance unverified",
    )
    text = json.dumps(summary, ensure_ascii=False, indent=2).replace(
        str(output), "$ACCEPTANCE_ROOT"
    )
    (output / "acceptance.json").write_text(text + "\n")
    print(
        json.dumps(
            dict(
                passed=True,
                scenarios={k: v["status"] for k, v in results.items()},
                output=str(output),
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
