"""EcoAlign-Forge · 内容对齐数据合成监控大屏"""

import streamlit as st

# ━━ Page Config (必须是第一个 Streamlit 调用) ━━
st.set_page_config(
    page_title="EcoAlign-Forge · 内容对齐数据合成工厂",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ━━ Autorefresh ━━
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=5000, limit=None, key="dashboard_autorefresh")

# ━━ Theme ━━
from dashboard.components.theme import inject_css

inject_css()

# ━━ Data ━━
from dashboard.data_loader import load_snapshot

snap = load_snapshot()

# ━━ Sidebar ━━
from dashboard.components.sidebar import render_sidebar

render_sidebar()

# ━━ Hero ━━
st.markdown('''
<div class="hero"><h1>EcoAlign-Forge</h1><div class="tag">内容对齐数据合成 · 实时监控大屏</div></div>
<div class="accent"></div>
''', unsafe_allow_html=True)

# ━━ KPI Cards ━━
from dashboard.components.kpi_cards import render_kpi_cards

render_kpi_cards(snap)

st.markdown('<div class="accent"></div>', unsafe_allow_html=True)

# ━━ Chart Tabs ━━
from dashboard.components.attack_chart import render_attack_distribution
from dashboard.components.quality_chart import render_quality_analysis
from dashboard.components.radar_chart import render_radar
from dashboard.components.timeline_chart import render_timeline

tab_radar, tab_tl, tab_atk, tab_ql = st.tabs([
    "◎ 拦截率雷达", "◸ 合成趋势", "⚔ 攻击策略分布", "◈ 质量分析",
])

with tab_radar:
    render_radar(snap)
with tab_tl:
    render_timeline(snap)
with tab_atk:
    render_attack_distribution(snap)
with tab_ql:
    render_quality_analysis(snap)

st.markdown('<div class="accent"></div>', unsafe_allow_html=True)

# ━━ Pipeline Monitor ━━
from dashboard.components.pipeline_table import render_pipeline_monitor

render_pipeline_monitor(snap)

# ━━ Footer ━━
st.markdown('''
<div style="text-align:center;padding:30px 0 12px">
    <div class="divider"></div>
    <div style="font-family:'Noto Sans SC','JetBrains Mono',monospace;color:rgba(255,255,255,.12);font-size:.6rem;letter-spacing:2px;line-height:1.8">
        EcoAlign-Forge v0.1.0 · 多智能体对齐数据合成工厂<br/>
        混沌生成器 → 审核官 → 终审法官 → DPO 训练对 · GPT-5.4<br/>
        © 2026 Apache 2.0
    </div>
</div>
''', unsafe_allow_html=True)
