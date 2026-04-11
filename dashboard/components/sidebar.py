"""侧边栏组件 — Agent 状态、策略信息、模型配置"""

from __future__ import annotations

import streamlit as st


def render_sidebar() -> None:
    """渲染侧边栏：包含 Agent 状态面板、当前策略、模型配置。"""
    with st.sidebar:
        # ── 品牌标识 ──
        st.markdown("""
        <div style="text-align:center;padding:16px 0">
            <div style="font-family:'Space Grotesk',sans-serif;font-size:1.35rem;font-weight:800;
                        background:linear-gradient(135deg,#6c5ce7,#a29bfe);
                        -webkit-background-clip:text;-webkit-text-fill-color:transparent">🛡️ EcoAlign</div>
            <div style="font-family:'JetBrains Mono',monospace;color:rgba(255,255,255,.2);font-size:.6rem;letter-spacing:3px;margin-top:2px">
                Forge v0.1.0 · 对齐数据工厂</div>
        </div>
        <div class="divider"></div>
        """, unsafe_allow_html=True)

        # ── 智能体状态 ──
        st.markdown("""
        <div style="padding:4px 0">
            <div style="font-family:'JetBrains Mono',monospace;font-size:.65rem;color:rgba(255,255,255,.28);letter-spacing:2px;margin-bottom:12px">智能体状态</div>
            <div class="ar"><span style="color:var(--t2)"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#ff7675;margin-right:8px"></span>混沌生成器</span><span style="font-family:'JetBrains Mono',monospace;font-size:.68rem;color:#55efc4">● 就绪</span></div>
            <div class="ar"><span style="color:var(--t2)"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#ffeaa7;margin-right:8px"></span>审核官</span><span style="font-family:'JetBrains Mono',monospace;font-size:.68rem;color:#55efc4">● 就绪</span></div>
            <div class="ar"><span style="color:var(--t2)"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#55efc4;margin-right:8px"></span>终审法官</span><span style="font-family:'JetBrains Mono',monospace;font-size:.68rem;color:#55efc4">● 就绪</span></div>
            <div class="ar" style="border:none"><span style="color:var(--t2)"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#6c5ce7;margin-right:8px"></span>LiteLLM 引擎</span><span style="font-family:'JetBrains Mono',monospace;font-size:.68rem;color:#6c5ce7">● 已连接</span></div>
        </div>
        <div class="divider"></div>
        """, unsafe_allow_html=True)

        # ── 当前策略 ──
        st.markdown("""
        <div style="padding:4px 0">
            <div style="font-family:'JetBrains Mono',monospace;font-size:.65rem;color:rgba(255,255,255,.28);letter-spacing:2px;margin-bottom:10px">当前策略</div>
            <div style="font-family:'Noto Sans SC',sans-serif;font-size:.88rem;color:#6c5ce7;font-weight:600;margin-bottom:4px">中国互联网内容安全标准</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:.68rem;color:rgba(255,255,255,.35);line-height:1.8">
                版本: 2.0 &middot; 维度: 6 &middot; 语言: zh-CN</div>
        </div>
        <div class="divider"></div>
        """, unsafe_allow_html=True)

        # ── 模型配置 ──
        st.markdown("""
        <div style="padding:4px 0">
            <div style="font-family:'JetBrains Mono',monospace;font-size:.65rem;color:rgba(255,255,255,.28);letter-spacing:2px;margin-bottom:10px">模型配置</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:.68rem;color:rgba(255,255,255,.35);line-height:2">
                混沌 &middot; <span style="color:#00cec9">gpt-5.4-mini</span><br/>
                审核 &middot; <span style="color:#00cec9">gpt-5.4-mini</span><br/>
                终审 &middot; <span style="color:#6c5ce7">gpt-5.4</span></div>
        </div>
        """, unsafe_allow_html=True)
