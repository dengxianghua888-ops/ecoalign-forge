# C first-user acceptance — three actual participants required

Status: **0/3 verified**. Automated fixtures, agents and browser automation do not
count as first-time human users. Use participant IDs rather than publishing names.
The project owner may keep original feedback privately; public evidence should be
redacted. Participants need Python 3.11/3.12 and macOS/Linux, no model key or budget.

## Walkthrough (about 15–25 minutes)

1. Check out the exact candidate commit supplied with the acceptance record. Create
   a new venv and run `python -m pip install -e '.[dashboard]'` from the repository root.
2. Run `python -m ecoalign_forge run --demo --num-samples 5`. Confirm demo, one
   completed case/pair and four abstentions (`partial_failed`, exit 3). Record the run ID and any help needed.
3. Run `python -m streamlit run dashboard/app.py --server.port 8501`. Select demo,
   your run and Review. Open a source and identify its rule/evidence span.
4. Accept case 4 (the gate-accepted fixture) with your participant ID and a reason.
   Correct its evidence/reason after checking rules, preserving external facts as
   unknown; missing material cannot be resolved by claiming miss. Try accepting a
   gate-abstained case and confirm refusal, then record a human abstention on it. Confirm the revision history preserves the original.
5. In Dataset, export the human-reviewed selection. Record counts and exclusions.
   Trace one included pair to source, evidence, review and policy. A zero-pair
   result is valid if your reviewed cases have no preference disagreement.
6. Change a previously accepted review, export again and confirm the first version
   stays unchanged. Download the ZIP, extract it and run
   `python -m ecoalign_forge verify PATH_TO_EXTRACTED_DATASET`.
7. Generate a data report. Compare JSONL line count/hash with `report.json` and
   the HTML report. Explain in your own words why this is not a model-quality score.

## Result record

Copy [first-user-result.template.json](first-user-result.template.json) for each
participant. Record actual commit/version/OS/Python, start/end time, run IDs,
dataset versions, pass/fail per step, unassisted/assisted completion, help requested,
errors and improvement requests. Attach redacted screenshots/logs and their SHA-256.
A reviewer verifies the evidence; a checked checkbox without evidence is insufficient.

All three participants must complete the critical source → review → next-version
export → verify path. Reproduce and repair critical failures, then have affected
participants rerun those steps. Do not pre-fill results or backdate acceptance.
F13 stays open until these records exist. Paid models and training are outside C.
