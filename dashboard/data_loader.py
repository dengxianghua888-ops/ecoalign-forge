"""Dashboard 数据加载层 — 连接后端或回退到 Demo 数据"""

from __future__ import annotations

import datetime
import logging
import random
import sys
from pathlib import Path

import numpy as np
import streamlit as st

# 模块顶层添加 src 路径，避免在每次刷新时重复修改 sys.path
_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# 直接从后端导入 DashboardSnapshot 作为唯一数据契约
from ecoalign_forge.storage.dashboard_bridge import DashboardBridge, DashboardSnapshot

logger = logging.getLogger(__name__)


def _generate_demo_snapshot() -> DashboardSnapshot:
    """生成 Demo 模式数据快照"""
    cases = random.randint(820, 1280)
    pass_c = int(cases * random.uniform(0.42, 0.52))
    flag_c = int(cases * random.uniform(0.22, 0.30))
    block_c = cases - pass_c - flag_c
    dpo = int(cases * random.uniform(0.60, 0.78))
    quality = round(random.uniform(0.81, 0.93), 2)

    dims = {
        "violence": random.uniform(0.60, 0.95),
        "sexual": random.uniform(0.60, 0.95),
        "discrimination": random.uniform(0.60, 0.95),
        "privacy": random.uniform(0.60, 0.95),
        "political": random.uniform(0.60, 0.95),
        "misinformation": random.uniform(0.60, 0.95),
    }

    strategies = {
        "direct_violation": random.randint(30, 120),
        "edge_case": random.randint(30, 120),
        "subtle_harm": random.randint(30, 120),
        "jailbreak_roleplay": random.randint(30, 120),
        "multilingual_evasion": random.randint(30, 120),
        "context_injection": random.randint(30, 120),
        "gradual_escalation": random.randint(30, 120),
        "emotional_manipulation": random.randint(30, 120),
    }

    now = datetime.datetime.now()
    timeline = [
        {
            "timestamp": (now - datetime.timedelta(minutes=30 * i)).isoformat(),
            "cases": random.randint(10, 40),
            "dpo_pairs": random.randint(5, 25),
        }
        for i in range(48)
    ][::-1]

    runs: list[dict] = []
    statuses = ["running", "running", "completed", "completed", "completed", "failed", "pending"]
    for _ in range(8):
        s = random.choice(statuses)
        runs.append({
            "run_id": f"run-{random.randint(1000, 9999)}",
            "status": s,
            "total": random.randint(50, 500),
            "completed": random.randint(20, 400),
            "dpo_pairs_generated": random.randint(20, 350),
            "progress_pct": (
                100.0 if s == "completed"
                else 0.0 if s == "pending"
                else random.uniform(15, 92)
            ),
            "started_at": (
                now - datetime.timedelta(hours=random.randint(0, 48))
            ).strftime("%m-%d %H:%M"),
        })

    return DashboardSnapshot(
        total_cases=cases,
        pass_count=pass_c,
        flag_count=flag_c,
        block_count=block_c,
        dpo_pairs=dpo,
        avg_quality=quality,
        interception_rate=(flag_c + block_c) / cases,
        dimension_rates=dims,
        attack_strategy_counts=strategies,
        quality_scores=list(np.random.beta(9, 2, 600)),
        sub_scores={
            "stealth_marketing_rate": random.uniform(0.05, 0.25),
            "ai_slop_rate": random.uniform(0.10, 0.35),
            "avg_severity": random.uniform(0.30, 0.70),
        },
        decision_distribution={
            "T0_Block": random.randint(5, 30),
            "T1_Shadowban": random.randint(20, 60),
            "T2_Normal": random.randint(80, 200),
            "T3_Recommend": random.randint(40, 120),
        },
        pipeline_runs=runs,
        timeline_data=timeline,
        is_demo=True,
    )


def _load_real_snapshot() -> DashboardSnapshot | None:
    """尝试从后端持久化数据加载真实快照"""
    try:
        bridge = DashboardBridge()
        snap = bridge.get_latest_snapshot()
        if snap.total_cases > 0:
            return snap
    except Exception as e:
        # 记录失败原因，避免静默吞没异常
        logger.warning("后端数据加载失败，回退至 Demo 模式: %s", e, exc_info=True)
    return None


@st.cache_data(ttl=5)
def load_snapshot() -> DashboardSnapshot:
    """加载数据快照：优先真实数据，回退 Demo"""
    real = _load_real_snapshot()
    if real is not None:
        return real
    return _generate_demo_snapshot()
