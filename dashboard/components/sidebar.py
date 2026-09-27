"""Source and capability boundaries for the dashboard."""

import streamlit as st

from ecoalign_forge import __version__


def render_sidebar(snap) -> None:
    with st.sidebar:
        st.markdown(f"### EcoAlign-Forge {__version__}")
        st.caption(f"数据来源：{snap.execution_mode.value}")
        st.markdown("**连接状态**")
        for name in ("混沌生成器", "审核官", "终审法官", "LiteLLM 引擎"):
            st.text(f"{name}：未检测")
        st.markdown("**执行规则**")
        st.caption("内置中文 A/B 手册；维度仅限制生成关注范围。")
        st.markdown("**快照维度**")
        st.text("、".join(snap.dimension_rates) or "暂无数据")
        st.caption("模型调用来源见各条 DPO 的 lineage。Demo 不调用模型。")
