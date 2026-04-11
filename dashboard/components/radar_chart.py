"""雷达图组件 — 各维度拦截率双雷达图 + 维度明细进度条"""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go
import streamlit as st

from dashboard.components.theme import GRID, apply_layout

if TYPE_CHECKING:
    from dashboard.data_loader import DashboardSnapshot

# 维度英文 → 中文映射
_DIM_ZH: dict[str, str] = {
    "violence": "暴力",
    "sexual": "色情",
    "discrimination": "歧视",
    "privacy": "隐私",
    "political": "政治",
    "misinformation": "虚假信息",
}

# 维度进度条颜色（与原始 6 色保持一致）
_DIM_COLORS: list[str] = [
    "#ff7675", "#fd79a8", "#e17055", "#74b9ff", "#a29bfe", "#55efc4",
]


def render_radar(snap: DashboardSnapshot) -> None:
    """渲染拦截率雷达图（当前 + 基准线）及右侧维度明细进度条。"""
    st.markdown('<div class="sh">各维度拦截率</div>', unsafe_allow_html=True)
    cr1, cr2 = st.columns([3, 2])

    # 从 snap 中按固定顺序读取维度数据
    dim_keys = list(_DIM_ZH.keys())
    dims = [_DIM_ZH[k] for k in dim_keys]
    rates = [snap.dimension_rates.get(k, 0.0) for k in dim_keys]

    # 闭合雷达图数据
    dims_closed = [*dims, dims[0]]
    rates_closed = [*rates, rates[0]]

    with cr1:
        fig = go.Figure()

        # 当前拦截率
        fig.add_trace(go.Scatterpolar(
            r=[r * 100 for r in rates_closed],
            theta=dims_closed,
            fill="toself",
            fillcolor="rgba(108,92,231,0.08)",
            line=dict(color="#6c5ce7", width=2),
            marker=dict(
                size=7, color="#a29bfe",
                line=dict(color="#6c5ce7", width=2),
            ),
            name="拦截率",
            hovertemplate="<b>%{theta}</b><br>拦截率: %{r:.1f}%<extra></extra>",
        ))

        # 基准线（当前值 * 0.85）
        baseline = [r * 0.85 for r in rates]
        baseline_closed = [*baseline, baseline[0]]
        fig.add_trace(go.Scatterpolar(
            r=[r * 100 for r in baseline_closed],
            theta=dims_closed,
            fill="toself",
            fillcolor="rgba(0,206,201,0.04)",
            line=dict(color="#00cec9", width=1.5, dash="dot"),
            marker=dict(size=4, color="#81ecec"),
            name="基准线",
        ))

        apply_layout(
            fig,
            height=420,
            polar=dict(
                bgcolor="rgba(0,0,0,0)",
                radialaxis=dict(
                    visible=True, range=[0, 100], gridcolor=GRID,
                    tickfont=dict(size=9, color="rgba(255,255,255,0.2)"),
                    ticksuffix="%",
                ),
                angularaxis=dict(
                    gridcolor="rgba(255,255,255,0.04)",
                    tickfont=dict(
                        family="Inter", size=11,
                        color="rgba(255,255,255,0.5)",
                    ),
                ),
            ),
            legend=dict(
                bgcolor="rgba(0,0,0,0)",
                font=dict(size=10, color="rgba(255,255,255,0.4)"),
            ),
        )
        st.plotly_chart(fig, width="stretch")

    # 右侧维度明细进度条
    with cr2:
        st.markdown(
            '<div style="font-family:Noto Sans SC,sans-serif;font-size:.85rem;'
            'font-weight:600;margin-bottom:16px">维度明细</div>',
            unsafe_allow_html=True,
        )
        for dim, rate, clr in zip(dims, rates, _DIM_COLORS, strict=False):
            pct = int(rate * 100)
            st.markdown(f"""
            <div style="margin-bottom:14px">
                <div style="display:flex;justify-content:space-between;margin-bottom:5px">
                    <span style="font-size:.76rem;color:var(--t2);font-weight:500">{dim}</span>
                    <span style="font-family:'JetBrains Mono',monospace;font-size:.72rem;color:{clr};font-weight:600">{pct}%</span>
                </div>
                <div class="pt"><div class="pf" style="width:{pct}%;background:linear-gradient(90deg,{clr},{clr}88);box-shadow:0 0 8px {clr}30"></div></div>
            </div>""", unsafe_allow_html=True)
