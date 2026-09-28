# Iteration C acceptance — candidate 0.4.0a1

C implements the original F12–F13 scope on top of B's published commit
`a329682322ae94a3130a75b1000777bf211ce5cb`. The integration branch is
`codex/iteration-c`. Engineering checks and three first-user walkthroughs are
separate gates. **F13 human acceptance is still 0/3; C release readiness is pending.**

## Engineering evidence

- Real SQLite review revisions: accept/correct/abstain/exclude, parent chain,
  optimistic stale-write rejection, operation idempotency and two-process ownership.
- Chinese, English and Arabic fixture sources; exact Unicode evidence and gated
  corrections. Original machine journal and older exports retain identical bytes.
- Reviewed-default export; explicit machine preview; duplicate decision conflicts,
  additive family grouping, deterministic train/eval partitions and immutable versions.
- SIGKILL before/after dataset directory publication: no partial published version,
  restart verifies/reuses a complete version and never duplicates pairs.
- HTML report plus JSON/JSONL/SHA256SUMS readback; machine/run counts and curated
  dataset counts are separate and the reported hash matches actual bytes.
- Streamlit interaction: actual source/run selection, accepts, corrections,
  abstentions, generated version and report, original-to-review trace, corrupt-run
  error state. Actual Chrome ZIP download was extracted and all manifest files verified.
- Controlled consumer datasets are loaded/template-processed/tokenized/collated with
  the existing separate TRL 1.14.0 and LLaMA-Factory 0.9.5 locked environments.
- Python 3.11/3.12 regression, full Ruff, changed formatting and scoped mypy checks
  are recorded with their exact final commit in the candidate evidence bundle.

Run `python scripts/accept_iteration_c.py --output PATH` for the deterministic
walkthrough: five demo cases, three reviewed pairs, then two after an abstention,
plus English/Arabic correction and deduplication examples. The fixture reviewer is
explicitly named `automated-acceptance-fixture`; it is not a real human participant.

## Issues caught during acceptance

- Streamlit form state initially reused its form widget key; a dedicated metadata
  key/form suffix removed that conflict.
- Temporary export folders were moved outside the published-version namespace so a
  hard-killed staging directory cannot appear as a complete dataset.
- A mocked checkpoint without an injected transport could fall through to a real
  provider on resume; C now rejects that path before any new request.
- Python 3.11's first Altair schema import exceeded the initial 20-second AppTest
  deadline. The diagnostic stack confirmed cold import; the harness now allows 60
  seconds for that load. This does not relax request/runtime deadlines.
- The inherited CSS overrode native icon fonts and muted caption contrast; the
  workbench preserves native icons and readable captions, and exposes mobile navigation.

No old semantic assertions were weakened. New counters describe human revision and
curated dataset selection separately; B's machine-run counts remain unchanged.

## Unmet acceptance

The original F13 exit condition requires **three actual first-time users** to finish
installation, source review, correction, next-version export and hash/report checks.
[Instructions and an empty result template](first-user-acceptance.md) are ready.
No user records have been invented. The integration PR can be reviewed while this
condition is pending; do not tag or publish the C Alpha until required gates pass.
F14 real-model validity, independent human preference quality and training benefits
remain D work. C does not call paid models, train or publish to PyPI.
