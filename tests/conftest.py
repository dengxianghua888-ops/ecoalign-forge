"""共享测试夹具"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, Mock

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import pytest

from ecoalign_forge.schemas.policy import PolicyDimension, PolicyInput


@pytest.fixture
def sample_policy() -> PolicyInput:
    """标准测试策略：内容分发分级（策略 A 私域引流 + 策略 B AI 洗稿）"""
    return PolicyInput(
        policy_id="test-v1",
        name="EcoAlign 内容分发分级策略",
        dimensions=[
            PolicyDimension(
                name="stealth_marketing",
                description="高隐蔽性私域引流（策略 A）",
            ),
            PolicyDimension(
                name="ai_slop",
                description="低信息熵 AI 洗稿（策略 B）",
            ),
        ],
        language="zh",
    )


@pytest.fixture
def sample_policy_single_dim() -> PolicyInput:
    """单策略测试 fixture"""
    return PolicyInput(
        policy_id="test-single",
        name="单策略",
        dimensions=[
            PolicyDimension(name="stealth_marketing", description="高隐蔽性私域引流"),
        ],
    )


@pytest.fixture(autouse=True)
def block_real_llm_requests(monkeypatch):
    """No test may send a real paid model request, even with ambient credentials."""
    import litellm

    import ecoalign_forge.llm.client as client

    monkeypatch.setattr(
        client, "acompletion", AsyncMock(side_effect=AssertionError("real LLM forbidden"))
    )
    monkeypatch.setattr(
        litellm, "acompletion", AsyncMock(side_effect=AssertionError("real LLM forbidden"))
    )
    monkeypatch.setattr(
        litellm, "completion", Mock(side_effect=AssertionError("real LLM forbidden"))
    )
