# Iteration A acceptance — 0.2.1a1 Alpha

Iteration A's deterministic engineering checks passed. The exact release commit, final clean-install results and downloadable asset hashes are recorded in `acceptance-summary.json` and `SHA256SUMS` on the [v0.2.1a1 pre-release](https://github.com/dengxianghua888-ops/ecoalign-forge/releases/tag/v0.2.1a1). This document describes the source checks; the release page and downloaded assets establish publication.

No paid model calls, human-label evaluation or training were performed. Passing these checks does not establish real-model correctness, training benefit or production readiness.

## Verification performed

| Layer | Observed result |
|---|---|
| Python 3.11.15 and 3.12.11 | 341 tests passed in each local environment; existing applicable cases retained |
| Lint and formatting | Whole-repository Ruff check passed; all 46 modified/new Python files formatted, without reformatting untouched files |
| Final judgment | Added/removed/reversed preference signals and unchanged neighboring cases verified; actual JSONL read back against final judgments |
| Failure accounting | Missing stages, partial/all failure, bounded parse exhaustion, cancellation, fatal errors and persistence faults verified; counts conserved and CLI exits 0/3/1/130/2 |
| Atomic batch aggregation | A fault after the temporary metrics update does not leak an uncommitted batch into persisted metrics |
| Late persistence failure | Failed run-ledger write also updates the saved diagnostic to failure; earlier completed-batch pairs survive |
| Review | Five statuses, failed/abstained exclusion, null empty-denominator rates and legacy list return tested; UI says “无有效复核” when appropriate |
| Generation | Reordered IDs restored; missing/extra/duplicate/unknown IDs exhaust bounded retries; local targets and case identity override model claims |
| Metrics/provenance | Severity and heuristic separated; strict/lenient mirror scores equal; no quality convergence inferred; live/demo/mock/unknown isolated |
| Packaging | Fresh environments installed wheel and sdist-rebuilt wheel; both ran Demo from empty directories outside checkout and loaded package resources from site-packages |
| Recorded success | 5 requested/generated/moderated/judged/completed, 0 failed/unattempted, 2 no-signal, 3 DPO pairs; demo mode, fixture version, null model IDs |
| Controlled failure | 2 requested, 1 completed, 1 failed, 1 pair; `partial_failed`, exit 3; actual JSONL and diagnostics read back |
| Browser | Actual HTTP page loaded; source selector and chart tabs interacted with; empty live, populated demo and malformed-file error observed and screenshots saved |
| Quickstart/report | Documented example ran offline; JSONL and HTML reopened, run ID/mode/fixture/counts reconciled; old static improvement report replaced |

The automated pipeline forbids real LLM requests in demo/mock mode. Tests additionally block provider completion entry points. CI runs the two supported Python versions, tests, whole-repository Ruff, distribution building, an installed CLI demo outside checkout, and deterministic success/failure evidence generation.

`python scripts/accept_iteration_a.py --output /absolute/path/to/new-evidence-dir` generates the two recorded scenarios and an artifact hash manifest. It rejects non-empty output directories. `working_tree_dirty` must be `false` for release evidence; a dirty-tree run is only development evidence.

## Changes to historical assertions

- `test_agents`: mocked generation responses now echo the actual request IDs; generated intent is asserted under `metadata.generation_target`, not `ground_truth`.
- `test_orchestrator`: mocks target `Judge.evaluate`; successful multi-batch fixtures return the exact requested cardinality instead of treating one returned case as a full batch.
- `test_guidelines_loader`: the project-root path assertion was renamed/replaced by the packaged-resource assertion, with additional wheel/sdist loading tests.
- `test_metrics`: the dashboard reads an explicitly selected mode directory; new metric fields retain severity meaning, and deprecated access is tested separately.
- `test_phase2`: zero effective reviews now means null rates; passed+corrected is the denominator. The two flywheel tests were renamed to assert that severity changes never imply quality improvement or convergence. Report assertions now require explicit severity and “未评估”.
- `test_quality`: decision consistency is neutral 0.5, excluded from default weighting; mirror-direction cases receive the same aggregate score.

These changes remove incorrect success/quality expectations; they do not delete coverage to obtain a green suite. All other original test names remain. One expected deprecation warning remains for the old `PipelineResult.avg_quality_score` access in the historical schema test.

## Finding disposition

[review-findings.csv](review-findings.csv) preserves F01–F14 and their original dependencies. F01–F06 are closed for the deterministic A scope. F08's supported-scope/version subtask and F09's explicit-review-status subtask passed; both overall findings remain open.

F07 and F10–F14 remain open. General PolicyPack support, original-content evidence review, final semantic gates, checkpoints/resume, budget/global-concurrency enforcement, variable-rater agreement correction, pinned trainer-consumption checks, the review workbench and independent real-model/human/training evaluation require later iterations. Documentation and report cleanup do not close F13's full new-user acceptance scope.
