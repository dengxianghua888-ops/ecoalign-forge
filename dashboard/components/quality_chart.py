"""Descriptive severity and pair heuristics; model quality remains unevaluated."""

import plotly.graph_objects as go
import streamlit as st

from dashboard.components.theme import GRID, TICK, apply_layout


def render_quality_analysis(snap) -> None:
    st.markdown("#### 判决与偏好对描述指标")
    st.caption("严重度反映判决分布；启发式分数不是正确率。模型质量、提升和收敛：未评估。")
    left, right = st.columns(2)
    left.metric("平均判决严重度", f"{snap.avg_decision_severity:.2f}")
    score = snap.avg_pair_quality_heuristic
    right.metric("偏好对启发式均值", "无偏好对" if score is None else f"{score:.3f}")
    if snap.review_consistency_rate is None or snap.review_correction_rate is None:
        st.info("无有效复核（一致率与修正率不可估计）")
    else:
        st.caption(
            f"复核一致率：{snap.review_consistency_rate:.1%}；修正率：{snap.review_correction_rate:.1%}"
        )
    st.caption(f"复核失败数：{snap.review_failed}")
    if not snap.severity_scores:
        st.info("暂无严重度分布")
        return
    fig = go.Figure(go.Histogram(x=snap.severity_scores, nbinsx=10, marker=dict(color="#6c5ce7")))
    apply_layout(
        fig,
        height=280,
        xaxis=dict(title="判决严重度", gridcolor=GRID, tickfont=TICK),
        yaxis=dict(title="判决数", gridcolor=GRID, tickfont=TICK),
    )
    st.plotly_chart(fig, width="stretch")
    st.bar_chart(snap.sub_scores)
