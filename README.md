# EcoAlign-Forge

An experimental Python pipeline for Chinese content moderation preference data, with rule citations and provenance.

[中文](README_zh.md) · [Migration](docs/iteration-a-migration.md) · [Acceptance status](docs/iteration-a-acceptance.md) · [Changelog](CHANGELOG.md)

**Alpha — 0.2.1a1.** The pipeline generates synthetic boundary cases, compares reviewer judgments, optionally reviews the judge's result, and builds candidate preference pairs from the final result. Current rules cover covert traffic diversion and low-information content. Generated targets, model judgments and heuristic scores are not verified labels. Human-review validity and downstream training benefits have not been established.

## Start with the recorded demo

Requires Python 3.11 or newer:

```bash
git clone https://github.com/dengxianghua888-ops/ecoalign-forge.git
cd ecoalign-forge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m ecoalign_forge --demo --num-samples 5
```

The demo uses recorded fixtures and does not call an LLM API. It prints execution mode, terminal status, stage counts, decision severity, pair heuristic and output path. This demonstrates the recorded-data workflow, not live-model performance. The [acceptance record](docs/iteration-a-acceptance.md) lists the actual verification status of this revision.

For a runnable Python example that also saves an HTML diagnostic report:

```bash
python examples/quickstart.py
```

This example also defaults to `demo=True`. Open the report path it prints in your browser. Its counts come from the same run; severity and heuristic scores do not measure correctness.

## Workflow and run status

```text
Built-in rules + generation targets
  → synthetic cases with request_item_id
  → reviewer judgments → rule-guided judge
  → optional review of the judgment against rules
  → final judgments → candidate pairs + provenance + diagnostics
```

Every generation response must return every requested ID exactly once. The pipeline restores request order and writes `metadata.generation_target` from the local request. This records intent, not ground truth. Review failures remain visible rather than becoming successful confirmations. The reviewer currently receives the judgment and rules, not the original content; verification of original-content evidence remains F09 follow-up work.

`completed` means processing completed, including valid judgments with no preference signal. It does not mean every case produced a pair or that the pairs are correct. Terminal counts satisfy:

```text
completed + failed + unattempted = requested
```

CLI exit codes: **0** completed, **3** partial failure, **1** failure, **130** cancelled, **2** invalid arguments. Automation must check exit status and `status`, not just dataset-file existence.

## Output locations

New outputs are separated by execution mode:

```text
data/
├── demo/                     # recorded fixtures
│   ├── metrics.json
│   ├── runs.jsonl
│   ├── flywheel_state.json
│   └── diagnostics_<run-id>.json
├── live/                     # real model calls
├── mock/                     # explicit test execution
└── datasets/
    ├── demo/dpo_pairs_*.jsonl
    ├── live/dpo_pairs_*.jsonl
    └── mock/dpo_pairs_*.jsonl
```

Run records and pair lineage carry `execution_mode`; demo records also identify the fixture version. Historical records without a mode stay `unknown` and are not automatically promoted to live evidence. `DATA_DIR` and `DATASETS_DIR` configure base paths. Per-stage recovery and resumable runs remain future work.

## Run a small live batch

From the repository root, copy the configuration and supply provider credentials, base URL and model IDs you can actually access:

```bash
cp .env.example .env
# Edit .env before running: provider configuration and three agent model assignments.
python -m ecoalign_forge --num-samples 5
```

Omitting `--demo` makes real model calls. Content and rules go to the configured provider and API usage can incur charges. This Alpha has no verified per-pair price or automatic budget cap. Start small and inspect failures and outputs.

Execution supports `zh`/`zh-CN`, unique non-empty subsets of `stealth_marketing` and `ai_slop`, and default severity metadata. The authoritative text is [the packaged A/B handbook](src/ecoalign_forge/resources/guidelines.md). Dimension descriptions, examples and platform context are descriptive metadata, not replacement rules. Selected dimensions do not change the fixed A/B decision matrix.

**Configuration boundary:** `PipelineConfig.num_samples` and `batch_size` control run sizing. `DEFAULT_*` synthesis environment fields, `PipelineConfig.max_concurrent`, `temperature` and `min_preference_gap` are not fully wired to execution. Do not rely on them as enforced concurrency, temperature or filtering controls. `PARSE_*` controls bounded parsing retries. Global limits, budgets and configuration unification are separate follow-up work.

## Inspect the dashboard

The dashboard currently runs from a source checkout; a wheel alone does not contain the `dashboard/` application directory. In the activated environment, **from the cloned repository root**:

```bash
python -m pip install -e '.[dashboard]'
python -m streamlit run dashboard/app.py --server.port 8501
```

Open Streamlit's printed local URL and explicitly select the data source. Missing data remains empty and read errors remain errors; the UI does not substitute synthetic success data. Connection labels remain “not checked” until a real probe exists. A visible dashboard is not model-quality validation.

## Export candidate data

Use the plain-text interchange format for inspection:

```python
from ecoalign_forge.export import export_trl
from ecoalign_forge.storage.store import DataStore

pairs = DataStore().load_dpo_pairs("PATH_PRINTED_BY_YOUR_RUN")
export_trl(pairs, "train.jsonl", include_metadata=True)
```

Records contain `prompt`, `chosen` and `rejected`; `include_metadata=True` preserves lineage in this format. ShareGPT and conversational exporters also exist, but a pinned trainer-consumption test is pending. The conversational export is not claimed compatible with current TRL chat templating. Exportable JSON is not evidence of successful training or model improvement. See F10 in the [finding ledger](docs/review-findings.csv).

## Read the metrics

| Metric | Meaning |
|---|---|
| `avg_decision_severity` | Average mapped T0–T3 severity; higher means stricter judgments |
| `avg_pair_quality_heuristic` | Structural and heuristic properties of candidate pairs; `null` means not computed |
| `interception_rate` | Share of T0/T1 judgments, not detection accuracy |
| Rule coverage | References observed in judgments, not validated semantic correctness |
| IAA | Agreement between model judgments; it does not establish which judgment is correct |
| Flywheel history | Synthesis-round records; quality improvement and training convergence remain **not evaluated** |

Historical `avg_quality_score`/`avg_quality` names described severity. Compatibility reads warn. Do not chart their old values as accuracy or training improvements; see [migration](docs/iteration-a-migration.md).

## Scope and development

Current scope is text-based Chinese A/B content-distribution rules. This is not a generic safety-policy engine, AI-authorship detector, production moderation service or autonomous training system. Four reviewer personas exist; default orchestration uses one persona per run. We make no claim of replacing human labeling, fixed generation cost or downstream model improvement.

```bash
python -m pip install -e '.[dev]'
python -m pytest tests/
python -m ruff check src/ tests/
```

For a reproducible issue, include the version/commit, execution mode, command, sanitized configuration, terminal status and diagnostics. Remove credentials and private content. Rule changes should include positive and negative examples and their intended tiers. Original finding IDs remain in the [iteration ledger](docs/review-findings.csv); implementation and acceptance are separate states.

Related work: [Constitutional AI](https://arxiv.org/abs/2212.08073), [HarmBench](https://arxiv.org/abs/2402.04249), [PyRIT](https://github.com/Azure/PyRIT), [TRL](https://github.com/huggingface/trl). References are not claims of equivalent coverage or reproduced performance.

[Apache License 2.0](LICENSE). Input-data rights and provider terms are separate from the software license.
