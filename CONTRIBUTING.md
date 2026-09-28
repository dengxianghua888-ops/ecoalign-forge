# Contributing

Use Python 3.11 or 3.12 on macOS/Linux. From a source checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,dashboard]'
python -m pytest tests -q
ruff check .
python -m hatchling build
```

Tests block external model requests. Keep reproductions deterministic and never
commit keys, provider responses containing personal data, or `.env` files.

Report the exact commit/version, Python/OS, command, expected/observed behavior,
exit code and a redacted minimal reproduction. The recorded demo's exit 3 is
expected: four cases require unavailable external evidence.

For a rule change, provide a declarative PolicyPack plus source/expected-decision
fixtures, evidence requirements, exceptions and boundary cases. Do not execute
arbitrary code from a rule pack. For a code change, add a focused regression when
behavior changes, run relevant tests and check changed-file formatting. Do not
reformat unrelated files.

Use a scoped branch and PR; describe the user-visible change and actual validation.
The C workbench is an open preview PR, not a default-branch API. Coordinate changes
that touch its shared contracts and do not use automated fixtures as first-user
acceptance. See [project status](docs/project-status.md).

Dataset licensing is separate from this repository's code license. Please include
source permissions and avoid real personal information in example data.
