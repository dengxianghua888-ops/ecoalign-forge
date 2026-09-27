# Iteration A migration — 0.2.1a1 Alpha

This describes the 0.2.1a1 Alpha contracts. Verification and release status are kept in [the acceptance record](iteration-a-acceptance.md). It does not establish human-label validity, model-training gains or production readiness.

## Run statuses and counters

Use `PipelineResult.status` and `counts`, rather than treating a non-empty output path as success. Terminal outcomes are:

| Status | CLI exit code | Meaning |
|---|---:|---|
| `completed` | 0 | Every requested case completed its required processing stages; a completed case may have no preference signal |
| `partial_failed` | 3 | Some cases completed and others failed |
| `failed` | 1 | Run failed; inspect error and diagnostics |
| `cancelled` | 130 | Execution was interrupted/cancelled |
| Argument error | 2 | Invalid CLI parameters; no successful run is implied |

`counts` includes `requested`, `generated`, `moderated`, `judged`, `completed`, `failed`, `unattempted`, `no_signal`, and `dpo_pairs`. Terminal accounting satisfies `completed + failed + unattempted = requested`. `generated`/`moderated`/`judged` describe distinct stages, not additional disjoint outcomes. DPO pair count is not completed case count. Failed required review is not a successful consistency result.

The CLI now ends with the corresponding exit code. Update shell/CI callers that previously accepted every normal process return. Existing top-level counters remain for compatibility; use the explicit stage counters for new integrations.

## Metric names and meanings

| Old field | Canonical field | Migration |
|---|---|---|
| `avg_quality_score` on pipeline/round metrics | `avg_decision_severity` | Old data described tier severity. Compatibility reads warn; do not reinterpret it as accuracy |
| `avg_quality` on snapshots/reports | `avg_decision_severity` | Deprecated alias; HTML report calls warn and canonical input takes precedence |
| `quality_distribution` in HTML report calls | `severity_distribution` | Deprecated alias, still interpreted as severity observations |
| No reliable prior field | `avg_pair_quality_heuristic` | Nullable; leave missing historical values unknown rather than synthesizing them from severity |
| Historical `quality_trend`/improvement/convergence | Separate descriptive trends; evaluation remains unknown | Never reuse those fields as measured model improvement or training convergence |

HTML reports accept `avg_decision_severity`, `avg_pair_quality_heuristic`, `severity_distribution` and `pair_quality_heuristic_distribution`. Each histogram labels its observation count; its denominator can differ from the number of pairs. Model accuracy is not measured by either distribution. Historical flywheel values are ignored for outcome claims, even if passed explicitly in `flywheel_summary`.

## Mode and historical data

New mode values are `live`, `demo` and `mock`. `unknown` is reserved for reading historical records whose provenance cannot be verified. Persisted run/lineage data includes `execution_mode`; fixture-based demo output also contains `fixture_version`. Demo and mock lineage do not claim a real model ID as execution evidence.

With default settings, metrics, run history, flywheel state and diagnostics live under `data/<mode>/`; candidate JSONL files live under `data/datasets/<mode>/`. `DATA_DIR` and `DATASETS_DIR` can change the base directories. The dashboard requires an explicit source selection and does not turn missing/corrupt data into generated demo observations.

Back up existing output before migrating consumers. Keep old flat files as historical/unknown evidence. Do not merely move them into `live/` or add `execution_mode=live` unless their actual origin has been established. This iteration does not provide stage checkpoints, resume or retrospective reconstruction of missing model-call evidence.

For HTML reports, pass `execution_mode`, `run_id` and `fixture_version` from the same `PipelineResult`. Omitted mode is displayed as `unknown`; report generation does not inspect arbitrary inputs and infer provenance.

## Rule and generation contracts

The sole authoritative handbook is [the packaged resource](../src/ecoalign_forge/resources/guidelines.md). The root `guidelines.md` is a navigation stub. A normal wheel installation loads rules from package resources rather than expecting a repository at the current working directory.

`PolicyInput` remains loadable for historical records. Before execution, `validate_supported()` accepts only `zh`/`zh-CN`, unique non-empty subsets of `stealth_marketing`/`ai_slop`, and the default severity metadata. Descriptions, context and examples are descriptive metadata; they do not define a new rule pack. Selected dimensions guide generation topics and do not alter the fixed A/B tier matrix.

New generation requests use the local request ID as case identity and allocate stable IDs and per-item targets before model invocation. Parsing retries reuse that request mapping. Missing, duplicate, extra or unknown IDs invalidate the complete generation response; valid shuffled responses are restored to request order. Parsing diagnostics retain received/requested counts where readable. Historical `ChaosCase` records may lack `request_item_id`.

`metadata.generation_target` is written from the local request. It expresses intended generation, not truth. Model-provided `ground_truth` is not accepted as a verified label. Human/model verification must remain a separate future evidence field. The legacy `expected_action` field is a generation hint, not a correctness criterion.

Review outcomes retain `passed`, `corrected`, `failed`, `abstain` or `skipped` status. The reviewer currently receives the judgment and handbook, not the original content; checking whether cited evidence actually exists in that content remains follow-up work. Candidate labels remain inspectable; this iteration does not add a complete final semantic gate. F08's general PolicyPack and F09's semantic verification remain open beyond these A-scope changes.

## Configuration and exports still need care

`PipelineConfig.num_samples` and `batch_size` set run size. `DEFAULT_*` synthesis environment fields, `max_concurrent`, `temperature` and `min_preference_gap` are not fully connected to execution. Do not treat them as enforced controls. The quickstart intentionally omits them and uses recorded demo data. Model usage, budget caps, global throttling and normalized configuration are not completed by this migration.

The dashboard still requires a source checkout plus its optional dependencies:

```bash
# In the cloned repository root, with your virtual environment active:
python -m pip install -e '.[dashboard]'
python -m streamlit run dashboard/app.py --server.port 8501
```

Plain-text TRL export can preserve lineage when `include_metadata=True`. Full trainer-consumption verification and conversational-format correction remain F10 work. Do not remove provenance merely to make a fixture look like live training data.
