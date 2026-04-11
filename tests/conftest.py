"""共享测试夹具"""

from __future__ import annotations

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
