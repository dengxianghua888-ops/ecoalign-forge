# Iteration B maintenance acceptance — 0.3.0a2

[Published Alpha and evidence](https://github.com/dengxianghua888-ops/ecoalign-forge/releases/tag/v0.3.0a2) bind commit `26760ca62d9560f9b072ede635831a9ee36ec6b5`.

- Python 3.11/3.12: 440 regressions each; all four [main CI jobs](https://github.com/dengxianghua888-ops/ecoalign-forge/actions/runs/36439234355) pass.
- Missing external material now rejects both definitive hit and miss. The built-in 5-case demo produces 1 completion/pair and 4 abstentions (exit 3). Earlier counts below are historical.
- Exact-commit acceptance includes built-in, English and Arabic exports; 16 recovery and 32 budget/quota tests; separate TRL 1.14.0 and LLaMA-Factory 0.9.5 loading/template/tokenizer/collator checks.
- Clean Python 3.12 wheel and Python 3.11 sdist-rebuilt wheel run, inspect, resume and export outside the checkout with LLM transport blocked. Resume creates no new attempts or duplicate pair. Both wheel files are identical.
- Browser interaction confirms actual run selection, 1 accepted pair / 4 failed cases, action chart and unknown-request pause with request ID.
- Published assets were downloaded again: wheel, sdist and evidence ZIP match SHA256SUMS; package versions, tag target, evidence commit and fixture manifest hashes agree.
- No real-model quality, training benefit or human-first-use claim is implied. C remains draft with 0/3 first-time users.

## Historical 0.3.0a1 record

> Historical record: 0.3.0a1 was withdrawn after the external-miss bypass was found.
> Its original counts are retained below, not asserted for the corrected gate. See
> [current status](project-status.md) and PR #15.

Engineering acceptance uses controlled transports and forbids external LLM requests. No training, paid inference or PyPI publication is part of this release. Live mode's accounting is exercised with transport doubles, not real supplier billing.

## Verified release-candidate gates

- Python 3.11 and 3.12 full regression passed; final release attachments carry the exact final count and commit.
- Repository Ruff passed; changed Python files passed formatting checks.
- Separate actual TRL / LLaMA-Factory consumer checks passed locally and in CI.
- Clean wheel installation and wheel rebuilt from sdist both ran and resumed the 5-case / 3-pair demo outside the checkout. Their wheel bytes matched.
- Browser interaction verified mode and actual run selection, dimension/action tabs, Arabic-run labels, unknown and budget pauses, review failure, and corrupted SQLite with no synthetic fallback. Screenshots are part of the release evidence.
- Integration PR: [#14](https://github.com/dengxianghua888-ops/ecoalign-forge/pull/14). The final release gate additionally rebuilds the exact merge commit and downloads published assets to recheck hashes.

## Evidence map

| Finding | Contract and executable evidence |
|---|---|
| F07 | `test_iteration_b_recovery.py`: SIGKILL at initialization, quota acquisition, request intent, response, parse, generation, moderator, judge, review, gate, case and export boundaries. Successful saved responses are never resent; pair IDs remain unique. |
| F08 | `test_iteration_b_policy.py`, `test_iteration_b_kernel.py`: immutable compilation, default and invalid references, A/B matrix and exceptions, different policies on identical content, original-source review, Chinese/English/Arabic and Unicode labels. |
| F09 | Source hashes and Unicode spans, missing material, document evidence, invalid corrections, model skip attempts and abstentions. Only accepted FinalEvaluation can produce chosen. |
| F10 | Coincidence results versus Krippendorff 0.8.2, unequal raters/missing cells/10k cases; actual TRL 1.14.0 and LLaMA-Factory 0.9.5 loaders, templates, tokenizers and collators in separate locked environments. |
| F11 | Two-process shared quota, bounded RPM/TPM and retries, real LiteLLM authentication exception mapping, usage-only stream chunks, interrupted streams, unknown cost reservations, budget pause and upward-only resume revision. |

`python scripts/accept_iteration_b.py --output PATH` writes complete builtin/English/Arabic sample exports, an unknown pause, a controlled failure, recovery and budget/quota JUnit reports, and a sanitized commit/hash/run/manifest summary. Consumer reports bind the dataset manifest and file hashes. Release attachments are the authority for exact final test counts, CI, browser captures, clean installation and download verification; a local test pass alone does not close the release.

## Regression changes

The detailed [migration guide](iteration-b-migration.md#changed-historical-assertions) identifies the adjusted A assertions. The original A final-pair, counter, provenance, packaging and no-network regressions remain applicable. Historical APIs remain readable; legacy live orchestration is explicitly refused instead of silently bypassing budgets.

## Failures found and repaired during acceptance

- A mock/demo token reservation originally consumed live TPM and delayed fixtures; model token reservation is now zero in these modes.
- CLI migration initially used the wrong built-in factory import; the compatibility exit-code tests caught and corrected it.
- Two first-start processes exposed SQLite WAL initialization locking despite busy_timeout; initialization now has a bounded lock retry and a two-process regression.
- Default LLaMA-Factory dependency resolution installed torchaudio 2.11 against Torch 2.8; its independent lock now pins torchaudio 2.8.
- Transformers 5 returns structured chat-template results by default; the acceptance assertion now explicitly requests token IDs while exercising the actual consumer template method.
- A model could try returning `skipped` to the enabled reviewer; parsing now rejects that runtime-only state.

## Evidence boundary

Rule consistency is not semantic accuracy. Arbitrary language support is structural and procedural, not proof of multilingual model quality. No human gold labels, real-model evaluation or training gains are established. F12–F14 remain open; the dashboard is read-only run inspection, not a review workbench. The original F ledger remains authoritative.
