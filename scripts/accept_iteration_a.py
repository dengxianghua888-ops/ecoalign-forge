"""Offline acceptance artifacts for a specific Git commit (no model requests)."""

import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

from ecoalign_forge.config import settings
from ecoalign_forge.demo.fixtures import (
    demo_chaos_run,
    demo_judge_evaluate,
    demo_moderator_run,
)
from ecoalign_forge.engine.orchestrator import AgentOrchestrator
from ecoalign_forge.exceptions import AgentError
from ecoalign_forge.schemas.pipeline import PipelineConfig
from ecoalign_forge.schemas.policy import PolicyDimension, PolicyInput


async def run(output):
    settings.data_dir = output / "data"
    settings.datasets_dir = output / "datasets"
    policy = PolicyInput(
        policy_id="alpha-acceptance",
        version="acceptance-v7",
        name="Deterministic Alpha acceptance",
        dimensions=[
            PolicyDimension(name="stealth_marketing", description="A"),
            PolicyDimension(name="ai_slop", description="B"),
        ],
    )
    success = await AgentOrchestrator(demo=True).run(policy, num_samples=5)
    assert success.status == "completed"
    assert success.counts.completed == 5 and success.counts.dpo_pairs == 3
    pairs = [json.loads(line) for line in Path(success.output_path).read_text().splitlines()]
    assert len(pairs) == 3
    assert all(
        p["lineage"]["execution_mode"] == "demo"
        and p["lineage"]["judge_model"] is None
        and p["lineage"]["source_policy_version"] == "acceptance-v7"
        for p in pairs
    )

    failure_orch = AgentOrchestrator(
        config=PipelineConfig(batch_size=1), execution_mode="mock", enable_constitutional=False
    )
    first = await demo_chaos_run(policy, 1)
    failure_orch.chaos_creator.run = AsyncMock(
        side_effect=[first, AgentError("fixture", "controlled batch failure")]
    )
    failure_orch.moderator.run = demo_moderator_run
    failure_orch.judge.evaluate = demo_judge_evaluate
    failure = await failure_orch.run(policy, num_samples=2)
    assert failure.status == "partial_failed" and failure.status.exit_code == 3
    assert failure.counts.completed == 1 and failure.counts.failed == 1
    failure.counts.assert_conserved()
    failure_file = json.loads(Path(failure.diagnostics_path).read_text())
    assert any(
        e.get("reason", "").endswith("controlled batch failure") for e in failure_file["entries"]
    )
    return success, failure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be a new or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    success, failure = asyncio.run(run(output))
    artifacts = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "acceptance.json" and path.suffix in (".json", ".jsonl"):
            # Strip machine-local paths from persisted diagnostic copies before publication.
            text = path.read_text().replace(str(output) + "/", "")
            path.write_text(text)
            artifacts[str(path.relative_to(output))] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = dict(
        commit=commit,
        working_tree_dirty=dirty,
        verification="deterministic_only",
        model_calls=0,
        success=dict(
            status=success.status,
            execution_mode=success.execution_mode,
            fixture_version=success.fixture_version,
            counts=success.counts.model_dump(),
        ),
        controlled_failure=dict(
            status=failure.status,
            execution_mode=failure.execution_mode,
            exit_code=failure.status.exit_code,
            counts=failure.counts.model_dump(),
        ),
        artifact_sha256=artifacts,
        unverified=[
            "real model quality",
            "training benefit",
            "PolicyPack",
            "semantic gates",
            "restart recovery",
            "budget control",
            "variable-rater agreement",
            "TRL trainer import",
        ],
    )
    (output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
