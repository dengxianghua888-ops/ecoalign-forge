"""时间线图表组件 — 24 小时合成吞吐量趋势"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.theme import GRID, TICK, apply_layout

if TYPE_CHECKING:
    from dashboard.data_loader import DashboardSnapshot


def _build_demo_timeline() -> pd.DataFrame:
    """当 timeline_data 为空时，生成 Demo 趋势数据。"""
    hours = pd.date_range(
        end=datetime.datetime.now(), periods=48, freq="30min",
    )
    chaos_d = np.abs(np.cumsum(np.random.randn(48)) * 15 + 200)
    dpo_d = np.abs(np.cumsum(np.random.randn(48)) * 10 + 120)
    return pd.DataFrame({
        "timestamp": hours,
        "cases": chaos_d,
        "dpo_pairs": dpo_d,
    })


def render_timeline(snap: DashboardSnapshot) -> None:
    """渲染 24 小时合成吞吐量双线趋势图。"""
    st.markdown(
        '<div class="sh">24小时合成吞吐量</div>',
        unsafe_allow_html=True,
    )

    # 从快照构建 DataFrame，为空则回退到 Demo
    if snap.timeline_data:
        df = pd.DataFrame(snap.timeline_data)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    else:
        df = _build_demo_timeline()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["cases"],
        name="混沌用例", mode="lines",
        line=dict(color="#a29bfe", width=2.5, shape="spline"),
        fill="tozeroy", fillcolor="rgba(162,155,254,0.06)",
    ))
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["dpo_pairs"],
        name="DPO 训练对", mode="lines",
        line=dict(color="#00cec9", width=2.5, shape="spline"),
        fill="tozeroy", fillcolor="rgba(0,206,201,0.05)",
    ))
    apply_layout(
        fig,
        height=400, hovermode="x unified",
        xaxis=dict(gridcolor=GRID, tickfont=TICK),
        yaxis=dict(gridcolor=GRID, tickfont=TICK),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=10, color="rgba(255,255,255,0.4)"),
        ),
    )
    st.plotly_chart(fig, width="stretch")
