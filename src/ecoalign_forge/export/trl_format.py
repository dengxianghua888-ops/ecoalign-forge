"""Consistent standard/conversational preference records and manifest-based cards."""

from __future__ import annotations

import json
from pathlib import Path

from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.kernel import PreferencePair


def prompt_messages(pair):
    if isinstance(pair, PreferencePair):
        messages = json.loads(pair.prompt)
        if (
            not isinstance(messages, list)
            or not messages
            or any(
                set(m) != {"role", "content"}
                or m["role"] not in {"system", "user", "assistant"}
                or not isinstance(m["content"], str)
                for m in messages
            )
        ):
            raise ValueError("Invalid serialized prompt messages")
        return messages
    return [{"role": "user", "content": pair.prompt}]


def to_trl_dict(pair: DPO_Pair | PreferencePair, *, include_metadata=False, conversational=False):
    messages = prompt_messages(pair)
    if conversational:
        record = dict(
            prompt=messages,
            chosen=[dict(role="assistant", content=pair.chosen)],
            rejected=[dict(role="assistant", content=pair.rejected)],
        )
    else:
        prompt = (
            pair.prompt
            if isinstance(pair, DPO_Pair)
            else "".join(f"{m['role']}:\n{m['content']}\n" for m in messages) + "assistant:\n"
        )
        record = dict(prompt=prompt, chosen=pair.chosen, rejected=pair.rejected)
    if include_metadata:
        record.update(source_case_id=pair.source_case_id, pair_id=pair.pair_id)
        if isinstance(pair, PreferencePair):
            record.update(label_distance=pair.label_distance, lineage=pair.lineage)
        else:
            record.update(
                chosen_rating=pair.chosen_score,
                rejected_rating=pair.rejected_score,
                preference_gap=pair.preference_gap,
                dimension=pair.dimension,
                difficulty=pair.difficulty,
            )
            if pair.lineage:
                record["lineage"] = pair.lineage.model_dump(mode="json")
    return record


def export_trl(pairs, output_path, *, include_metadata=False, conversational=False):
    from ecoalign_forge.runtime.journal import atomic_write

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path,
        "".join(
            json.dumps(
                to_trl_dict(p, include_metadata=include_metadata, conversational=conversational),
                ensure_ascii=False,
            )
            + "\n"
            for p in pairs
        ),
    )
    return path


def dataset_card(manifest, *, dataset_name="ecoalign-forge-dpo", description=""):
    language = json.dumps(manifest.get("language") or "unspecified", ensure_ascii=False)
    license_name = json.dumps(manifest.get("data_license") or "unspecified")
    return f"""---
language: [{language}]
license: {license_name}
tags: [dpo, synthetic]
---
# {dataset_name}

{description}

Pairs: {manifest.get("pairs", 0)}. Mode: {manifest.get("execution_mode", "unknown")}.
Run: {manifest.get("run_id", "unknown")}.
Policy SHA-256: {manifest.get("policy_hash", "unknown")}.

Validation: {manifest.get("verification", "not specified")}.
Machine preferences pass structural, evidence-reference and rule-consistency checks.
They are not human ground truth. Semantic accuracy, language quality and training gains are unverified.
An unspecified data license does not inherit the source-code license.

`pairs.jsonl` retains source case IDs, evidence, rule snapshots and response hashes.
`trl_standard.jsonl`, `trl_conversational.jsonl` and `train_sharegpt.json` are consumer views.
The conversational view uses message lists for prompt, chosen and rejected.
"""


def export_trl_dataset_card(
    pairs, output_dir, *, dataset_name="ecoalign-forge-dpo", description="", manifest=None
):
    from ecoalign_forge.runtime.journal import atomic_write

    path = Path(output_dir) / "README.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path,
        dataset_card(
            manifest or {"pairs": len(pairs)}, dataset_name=dataset_name, description=description
        ),
    )
    return path
