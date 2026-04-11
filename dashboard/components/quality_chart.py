"""质量分析组件 — 仪表盘 + 评分直方图 + 子维度雷达图"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.theme import GRID, TICK, apply_layout

if TYPE_CHECKING:
    from dashboard.data_loader import DashboardSnapshot


def render_quality_analysis(snap: DashboardSnapshot) -> None:
    """渲染质量分析三栏：仪表盘、评分分布直方图、子维度雷达图。"""
    st.markdown(
        '<div class="sh">终审法官质量评估</div>',
        unsafe_allow_html=True,
    )
    q1, q2, q3 = st.columns(3)

    # ── 仪表盘 ──
    with q1:
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=snap.avg_quality * 100,
            number=dict(
                font=dict(family="Space Grotesk", size=42, color="#a29bfe"),
                suffix="%",
            ),
            gauge=dict(
                axis=dict(
                    range=[0, 100],
                    tickfont=dict(color="rgba(255,255,255,0.15)", size=9),
                ),
                bar=dict(color="#6c5ce7", thickness=0.7),
                bgcolor="rgba(255,255,255,0.02)",
                bordercolor="rgba(255,255,255,0.04)",
                borderwidth=1,
                steps=[
                    dict(range=[0, 60], color="rgba(255,118,117,0.06)"),
                    dict(range=[60, 80], color="rgba(255,234,167,0.04)"),
                    dict(range=[80, 100], color="rgba(85,239,196,0.04)"),
                ],
                threshold=dict(
                    line=dict(color="#fd79a8", width=2),
                    thickness=0.8, value=90,
                ),
            ),
            title=dict(
                text="平均质量",
                font=dict(
                    family="Noto Sans SC", size=11,
                    color="rgba(255,255,255,0.35)",
                ),
            ),
        ))
        apply_layout(fig_gauge, height=280)
        st.plotly_chart(fig_gauge, width="stretch")

    # ── 评分分布直方图 ──
    with q2:
        # 优先使用真实质量评分，为空时回退到 Demo 数据
        scores = (
            snap.quality_scores
            if snap.quality_scores
            else list(np.random.beta(9, 2, 600))
        )
        fig_hist = go.Figure(data=[go.Histogram(
            x=scores, nbinsx=35,
            marker=dict(
                color="rgba(108,92,231,0.35)",
                line=dict(color="#6c5ce7", width=0.5),
            ),
        )])
        apply_layout(
            fig_hist,
            height=280,
            xaxis=dict(title="评分", gridcolor=GRID, tickfont=TICK),
            yaxis=dict(title="频次", gridcolor=GRID, tickfont=TICK),
        )
        st.plotly_chart(fig_hist, width="stretch")

    # ── 风险信号雷达图 ──
    with q3:
        # 从 snap.sub_scores 读取内容分发分级模型的两类风险率与平均严重度，
        # 派生"安全率"和"清流率"两个互补指标，凑出 5 个雷达点。
        stealth_rate = snap.sub_scores.get("stealth_marketing_rate", 0.0)
        slop_rate = snap.sub_scores.get("ai_slop_rate", 0.0)
        avg_severity = snap.sub_scores.get("avg_severity", 0.0)
        # 安全率 = 1 - 严重度（值越高表示内容越合规）
        safety_rate = max(0.0, 1.0 - avg_severity)
        # 清流率 = 1 - max(策略 A 命中率, 策略 B 命中率)
        clean_rate = max(0.0, 1.0 - max(stealth_rate, slop_rate))

        sub_dims = ["策略A命中", "策略B命中", "平均严重度", "安全率", "清流率"]
        sub_vals = [stealth_rate, slop_rate, avg_severity, safety_rate, clean_rate]
        sub_vals_closed = [*sub_vals, sub_vals[0]]

        fig_sub = go.Figure(data=go.Scatterpolar(
            r=sub_vals_closed,
            theta=[*sub_dims, sub_dims[0]],
            fill="toself",
            fillcolor="rgba(0,206,201,0.06)",
            line=dict(color="#00cec9", width=2),
            marker=dict(size=5, color="#81ecec"),
        ))
        apply_layout(
            fig_sub,
            height=280,
            polar=dict(
                bgcolor="rgba(0,0,0,0)",
                radialaxis=dict(
                    visible=True, range=[0, 1], gridcolor=GRID,
                    tickfont=dict(size=8, color="rgba(255,255,255,0.15)"),
                ),
                angularaxis=dict(
                    gridcolor="rgba(255,255,255,0.04)",
                    tickfont=dict(
                        family="Inter", size=10,
                        color="rgba(255,255,255,0.4)",
                    ),
                ),
            ),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
        )
        st.plotly_chart(fig_sub, width="stretch")
