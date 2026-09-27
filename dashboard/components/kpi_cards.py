"""Counts and severity for the selected run (no cross-source deltas)."""

import streamlit as st


def render_kpi_cards(snap) -> None:
    if snap.is_demo:
        st.warning("DEMO MODE · 预录 fixture 数据")
    columns = st.columns(6)
    for column, label, value in zip(
        columns,
        [
            "有效最终判决",
            "正常分发 (T2+T3)",
            "限流 (T1)",
            "屏蔽 (T0)",
            "DPO 训练对",
            "平均判决严重度",
        ],
        [
            snap.total_cases,
            snap.pass_count,
            snap.flag_count,
            snap.block_count,
            snap.dpo_pairs,
            f"{snap.avg_decision_severity:.2f}",
        ],
        strict=True,
    ):
        column.metric(label, value)
