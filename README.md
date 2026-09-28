# EcoAlign-Forge

An experimental, resumable synthesis kernel and local review workbench for traceable preference data.

[中文](README_zh.md) · [Migration and contracts](docs/iteration-b-migration.md) · [Acceptance](docs/iteration-b-acceptance.md) · [Findings F01–F14](docs/review-findings.csv)

**C candidate 0.4.0a1** (published B Alpha: 0.3.0a1). Declarative PolicyPacks define languages, labels, evidence and ordered decisions. The kernel generates cases, stores weak candidates, reviews judge candidates against original text, validates policy consistency, and exports preference pairs with provenance. Acceptance means engineering consistency, **not human ground truth, model accuracy or demonstrated training benefit**.

## Recorded demo

Python 3.11/3.12, macOS/Linux:

```bash
git clone https://github.com/dengxianghua888-ops/ecoalign-forge.git
cd ecoalign-forge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m ecoalign_forge run --demo --num-samples 5
# Historical spelling also works:
python -m ecoalign_forge --demo --num-samples 5
python examples/quickstart.py
```

Five recorded fixtures produce five completed cases and three preference pairs, with zero external model requests. Demo/mock record null actual models. Default CLI mode is demo. To install a release without cloning, download its verified wheel from [GitHub Releases](https://github.com/dengxianghua888-ops/ecoalign-forge/releases), then `python -m pip install /path/to/downloaded.whl`. No PyPI release is implied.

## Rules, execution and recovery

```text
PolicyPack + immutable RunConfig
  → persisted sampling plan → generation
  → weak moderation → judge candidate → original-source review
  → evidence and policy gate → preference pair → immutable exports
```

The built-in Chinese A/B handbook is one pack. A [custom English pack](examples/contact_policy.en.json) shows open labels and actions. The schema and prompt pipeline permit arbitrary language; language-specific model quality remains unverified. Rules allow fixed boolean, label and score comparisons, exceptions and decision tables; packs cannot execute code.

```bash
python -m ecoalign_forge inspect data/demo/runs/RUN_ID
python -m ecoalign_forge resume data/demo/runs/RUN_ID
python -m ecoalign_forge export data/demo/runs/RUN_ID
# Only after explicitly choosing how to handle an unknown remote request:
python -m ecoalign_forge resume data/live/runs/RUN_ID --resolve 'ATTEMPT_ID=retry'
```

Each run has a SQLite WAL journal at `DATA_DIR/<mode>/runs/<run_id>/`. Saved complete responses replay locally. Unknown requests pause instead of silently repeating a potentially charged call. Only budget increases and deadline extensions are allowed on resume; rule, model, prompt and code changes require a new run. One executor owns each run; multiple runs share concurrency/RPM/TPM within the same data root and quota group.

Counts satisfy `completed + failed + unattempted + in_progress = requested`, and `accepted_cases + excluded_cases = completed`. An excluded semantic candidate is completed processing, but never chosen. Review failure/abstention is failed. Exit codes: **0** completed, **1** failed, **2** invalid arguments, **3** partial failure, **4** paused, **130** cancelled.

## Live configuration

Live requires an explicit USD cap and complete price snapshot. Configure provider credentials in environment variables, never in a PolicyPack or RunConfig. Then supply a [RunConfig JSON](docs/iteration-b-migration.md):

```bash
python -m ecoalign_forge run --mode live --config /path/to/verified-live-config.json --policy examples/contact_policy.en.json
```

Defaults enforce 5 concurrent requests, 3 attempts total including parsing retries, 120-second request timeout, 30-second idle stream timeout and 3600-second run deadline. Requested model prices estimate cost from returned usage; missing usage remains reserved. Actual supplier billing stays unknown. This tool does not claim control over other clients using the same account. Release acceptance makes no paid calls.

## Exports and metrics

Each immutable dataset version contains `pairs.jsonl`, `trl_standard.jsonl`, `trl_conversational.jsonl`, `train_sharegpt.json`, `dataset_info.json`, `policy.json`, a data card and a SHA-256 manifest. Source IDs, text hashes, rule snapshot and response hashes remain in lineage. Data licensing is **unspecified** unless the policy declares it; the source-code license does not transfer automatically.

The consumer checks run actual loading, templates, tokenization and collators in **separate locked environments**: TRL 1.14.0 and LLaMA-Factory 0.9.5. They use a local byte tokenizer without pretrained models or training. See `scripts/consumers/verify.py` and the migration guide.

Severity exists only if the pack defines it; unordered labels have no invented quality score. Krippendorff alpha uses normalized coincidences and nullable estimates. Deliberately biased Moderator/Judge comparisons are candidate disagreement diagnostics, not independent-annotator reliability or data-quality gates.

## Source dashboard

From the repository root:

```bash
python -m pip install -e '.[dashboard]'
python -m streamlit run dashboard/app.py --server.port 8501
```

Select mode and an actual run, then use **Run → Review → Dataset**. Inspect original text and rule evidence; accept, correct, abstain or exclude with a reason. Revisions are append-only. Build a new dataset version with exact deduplication and family-grouped train/eval splits, verify it and download its report. Historical views remain read-only; empty/damaged data never becomes random demo data. Use this write-capable workbench only in a trusted local environment.

```bash
python -m ecoalign_forge run --demo --num-samples 5 --persona naive
python -m ecoalign_forge dataset data/demo/runs/RUN_ID --output-root datasets
python -m ecoalign_forge verify datasets/demo/curated/DATASET_VERSION
python -m ecoalign_forge report data/demo/runs/RUN_ID --output-root reports
```

Default curated export requires accepted human decisions; unreviewed data is an explicit candidate preview. `export` retains the legacy machine view. A run uses **one** configurable persona, not a four-persona ensemble. See [C contracts and migration](docs/iteration-c-migration.md).

## Verification and scope

```bash
python -m pytest tests -q
ruff check .
python -m hatchling build
python scripts/accept_iteration_b.py --output /tmp/ecoalign-b
```

The [acceptance record](docs/iteration-b-acceptance.md) links version-bound evidence. F07–F11 cover portable contracts, recovery, evidence gates, consumer correctness and budgets. C implements F12–F13 engineering work. F13 still requires three actual first-time user walkthroughs; [the protocol](docs/first-user-acceptance.md) records that gate separately. F14 real-model quality and training outcomes remain open. Historic A adapters and files remain readable; [migration notes](docs/iteration-b-migration.md) document changed assertions and compatibility limits.

[Contributing](CONTRIBUTING.md) · [Release gates](docs/releasing.md) · [C acceptance](docs/iteration-c-acceptance.md)

Code license: [Apache-2.0](LICENSE).
