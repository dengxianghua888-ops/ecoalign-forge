"""KPI 卡片组件 — 展示核心指标：总用例、通过、标记、拦截、DPO 训练对、平均质量"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from dashboard.data_loader import DashboardSnapshot

# 用于存储上次 KPI 值的 session_state 键名
_PREV_KEY = "_kpi_prev_values"


def _compute_delta(current: float | int, key: str) -> str | None:
    """根据 session_state 中存储的上次值计算 delta，首次返回 None。"""
    prev_store: dict = st.session_state.get(_PREV_KEY, {})
    prev_val = prev_store.get(key)
    if prev_val is None:
        return None
    diff = current - prev_val
    if isinstance(current, float):
        return f"{diff:+.2f}"
    return f"{diff:+d}"


def _save_current(values: dict[str, float | int]) -> None:
    """将当前值保存到 session_state，供下次计算 delta 使用。"""
    st.session_state[_PREV_KEY] = dict(values)


def render_kpi_cards(snap: DashboardSnapshot) -> None:
    """渲染 6 列 KPI 指标卡片，支持 Demo 模式徽章。"""
    # Demo 模式提示
    if snap.is_demo:
        st.markdown(
            '<div class="badge b-wait" style="margin-bottom:12px">'
            "DEMO MODE \u00b7 使用模拟数据</div>",
            unsafe_allow_html=True,
        )

    # 当前值映射
    current_values: dict[str, float | int] = {
        "total_cases": snap.total_cases,
        "pass_count": snap.pass_count,
        "flag_count": snap.flag_count,
        "block_count": snap.block_count,
        "dpo_pairs": snap.dpo_pairs,
        "avg_quality": snap.avg_quality,
    }

    # 计算 delta
    d_total = _compute_delta(snap.total_cases, "total_cases")
    d_pass = _compute_delta(snap.pass_count, "pass_count")
    d_flag = _compute_delta(snap.flag_count, "flag_count")
    d_block = _compute_delta(snap.block_count, "block_count")
    d_dpo = _compute_delta(snap.dpo_pairs, "dpo_pairs")
    d_quality = _compute_delta(snap.avg_quality, "avg_quality")

    # 渲染 6 列
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("总用例数", f"{snap.total_cases:,}", delta=d_total)
    c2.metric("正常分发 (T2+T3)", f"{snap.pass_count}", delta=d_pass)
    c3.metric("限流 (T1)", f"{snap.flag_count}", delta=d_flag)
    c4.metric("屏蔽 (T0)", f"{snap.block_count}", delta=d_block)
    c5.metric("DPO 训练对", f"{snap.dpo_pairs}", delta=d_dpo)
    c6.metric("平均严重度", f"{snap.avg_quality}", delta=d_quality)

    # 保存当前值用于下次 delta 计算
    _save_current(current_values)
