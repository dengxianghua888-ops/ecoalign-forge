"""Real journal accounting around deterministic transport faults."""

import asyncio
from decimal import Decimal

import pytest

from ecoalign_forge.runtime.configuration import resolve_config
from ecoalign_forge.runtime.control import (
    Quota,
    RequestController,
    RequestFailedError,
    RunPausedError,
    TransportError,
    budget_snapshot,
)
from ecoalign_forge.runtime.journal import Journal
from ecoalign_forge.schemas.kernel import GenerationResult, RunConfig


def setup(tmp_path, **kwargs):
    defaults = RunConfig()
    prices = {
        m.model: dict(input_per_million=1, output_per_million=2, max_input_tokens=1000)
        for m in defaults.models.values()
    }
    c = RunConfig(execution_mode="live", max_run_cost=1, prices=prices, **kwargs)
    j = Journal(tmp_path / "run")
    j.initialize(dict(run_id="run"), [])
    q = Quota(tmp_path, c)
    return c, j, q


def result(aid, content='{"ok":true}', usage=True):
    return GenerationResult(
        content=content,
        model="actual-returned-model",
        attempt_id=aid,
        finish_reason="stop",
        usage=dict(prompt_tokens=5, completion_tokens=3, total_tokens=8) if usage else None,
    )


@pytest.mark.asyncio
async def test_saved_response_replayed_without_call(tmp_path):
    import json

    c, j, q = setup(tmp_path)

    async def transport(payload, aid, cfg):
        return result(aid)

    controller = RequestController(j, q, c, transport)
    j.hook = lambda event, data: (
        (_ for _ in ()).throw(RuntimeError("crash")) if event == "response_committed" else None
    )
    with pytest.raises(RuntimeError):
        await controller.call("q", "judge", [], [], json.loads)
    j.hook = lambda *_: None

    async def forbidden(*args):
        raise AssertionError("should replay local raw response")

    controller.transport = forbidden
    assert await controller.call("q", "judge", [], [], json.loads) == {"ok": True}
    assert len(j.attempts()) == 1
    assert budget_snapshot(j)["estimated_usd"] == "0.000011"
    q.close()
    j.close()


@pytest.mark.asyncio
async def test_parse_retries_share_total_and_cost(tmp_path):
    import json

    c, j, q = setup(tmp_path, max_attempts=3)

    async def transport(payload, aid, cfg):
        return result(aid, "{broken")

    controller = RequestController(j, q, c, transport)
    with pytest.raises(RequestFailedError, match="attempt_limit"):
        await controller.call("q", "judge", [], [], json.loads)
    assert len(j.attempts()) == 3
    assert Decimal(budget_snapshot(j)["estimated_usd"]) == Decimal(".000033")
    q.close()
    j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("code,attempts", [(401, 1), (403, 1), (404, 1), (429, 3), (503, 3)])
async def test_error_classification(tmp_path, monkeypatch, code, attempts):
    import json

    c, j, q = setup(tmp_path)
    original = asyncio.sleep

    async def fast(delay):
        await original(0)

    monkeypatch.setattr("ecoalign_forge.runtime.control.asyncio.sleep", fast)

    async def transport(*args):
        raise TransportError("permanent" if code < 429 else "transient", code)

    controller = RequestController(j, q, c, transport)
    with pytest.raises(RequestFailedError):
        await controller.call("q", "judge", [], [], json.loads)
    assert len(j.attempts()) == attempts
    if code == 503:
        assert Decimal(budget_snapshot(j)["unresolved_reserved_usd"]) > 0
    q.close()
    j.close()


@pytest.mark.asyncio
async def test_unknown_pauses_and_budget_does_not_treat_missing_usage_as_free(tmp_path):
    import json

    c, j, q = setup(tmp_path)

    async def transport(*args):
        raise TransportError("unknown")

    ctrl = RequestController(j, q, c, transport)
    with pytest.raises(RunPausedError, match="unknown"):
        await ctrl.call("q", "judge", [], [], json.loads)
    with pytest.raises(RunPausedError, match="unknown"):
        await ctrl.call("q", "judge", [], [], json.loads)
    assert len(j.attempts()) == 1 and Decimal(budget_snapshot(j)["unresolved_reserved_usd"]) > 0
    c2 = c.model_copy(update={"max_run_cost": Decimal(".0000001")})
    with pytest.raises(RunPausedError, match="budget"):
        await RequestController(j, q, c2, transport).call("new", "judge", [], [], json.loads)
    assert len(j.attempts()) == 1
    q.close()
    j.close()


@pytest.mark.asyncio
async def test_concurrency_shared_between_controllers(tmp_path):
    import json

    c, j, q = setup(tmp_path, max_concurrent=2, tpm=1000000)
    current = peak = 0

    async def transport(payload, aid, cfg):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.01)
        current -= 1
        return result(aid)

    ctrl = RequestController(j, q, c, transport)
    await asyncio.gather(*[ctrl.call(str(i), "judge", [], [], json.loads) for i in range(6)])
    assert peak == 2
    q.close()
    j.close()


def test_configuration_precedence_and_required_live_prices(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"max_concurrent":3}')
    c = resolve_config(
        path=p, explicit={"max_concurrent": 2}, environ={"ECOALIGN_MAX_CONCURRENT": "1"}
    )
    assert c.max_concurrent == 2
    assert resolve_config(path=p, environ={"ECOALIGN_MAX_CONCURRENT": "1"}).max_concurrent == 3
