"""Resolve and freeze all effective parameters before a run is created."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ecoalign_forge.schemas.kernel import RunConfig


def resolve_config(
    *, explicit: dict | None = None, path: Path | None = None, environ=None
) -> RunConfig:
    env = os.environ if environ is None else environ
    supported = {"ECOALIGN_" + name.upper() for name in RunConfig.model_fields}
    unknown = {key for key in env if key.startswith("ECOALIGN_")} - supported
    if unknown:
        raise ValueError("Unsupported configuration keys: " + ", ".join(sorted(unknown)))
    values = {}
    for name in RunConfig.model_fields:
        key = "ECOALIGN_" + name.upper()
        if key in env:
            try:
                values[name] = json.loads(env[key])
            except json.JSONDecodeError:
                values[name] = env[key]
    if path:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict):
            raise ValueError("Run configuration must be a JSON object")
        values.update(data)
    values.update({k: v for k, v in (explicit or {}).items() if v is not None})
    return RunConfig.model_validate(values)
