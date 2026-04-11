"""流水线监控表格组件 — 展示流水线运行记录"""

from __future__ import annotations

import datetime
import random
from html import escape
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from dashboard.data_loader import DashboardSnapshot

# 状态 → 徽章 CSS 类映射
_BADGE_MAP: dict[str, str] = {
    "running": "b-run",
    "completed": "b-done",
    "failed": "b-fail",
    "pending": "b-wait",
}

# 状态 → 中文显示文本
_STATUS_ZH: dict[str, str] = {
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "pending": "等待中",
}

# 阶段颜色映射
_STAGE_COLORS: dict[str, str] = {
    "混沌生成": "#ff7675",
    "策略审核": "#ffeaa7",
    "终审裁决": "#55efc4",
    "完成": "#6c5ce7",
    "异常": "#ff7675",
    "已完成": "#6c5ce7",
    "—": "rgba(255,255,255,0.2)",
}


def _generate_demo_runs() -> list[dict]:
    """生成 Demo 模式的流水线运行记录。"""
    statuses = ["running", "running", "running", "completed", "completed",
                "completed", "completed", "failed", "pending"]
    stage_opts = ["混沌生成", "策略审核", "终审裁决", "已完成"]
    mdl_opts = ["gpt-5.4-mini", "gpt-5.4", "claude-4-sonnet", "qwen-3-72b"]
    pol_opts = ["安全标准 v2", "内容合规 v1", "反歧视策略", "隐私保护 v3"]

    now = datetime.datetime.now()
    runs: list[dict] = []
    for _ in range(10):
        s = random.choice(statuses)
        prog = (
            100.0 if s == "completed"
            else 0.0 if s == "pending"
            else random.randint(15, 92) if s == "running"
            else random.randint(20, 60)
        )
        runs.append({
            "run_id": f"run-{random.randint(1000, 9999)}",
            "status": s,
            "policy": random.choice(pol_opts),
            "stage": random.choice(stage_opts) if s == "running" else (
                "—" if s == "pending" else "完成" if s == "completed" else "异常"
            ),
            "model": random.choice(mdl_opts),
            "total": random.randint(50, 500),
            "dpo_pairs_generated": random.randint(20, 350),
            "progress_pct": prog,
            "started_at": (now - datetime.timedelta(hours=random.randint(0, 48))).strftime("%m-%d %H:%M"),
        })
    return runs


def _resolve_stage(run: dict) -> str:
    """根据运行记录推断阶段显示文本。"""
    # 如果记录已提供 stage 字段，直接使用
    if "stage" in run:
        return run["stage"]
    # 否则根据 status 推断
    status = run.get("status", "pending")
    if status == "completed":
        return "完成"
    if status == "pending":
        return "—"
    if status == "failed":
        return "异常"
    return "运行中"


def render_pipeline_monitor(snap: DashboardSnapshot) -> None:
    """渲染流水线实时监控表格。"""
    st.markdown(
        '<div class="sh">流水线实时监控</div>',
        unsafe_allow_html=True,
    )

    # 优先使用真实数据，为空回退到 Demo
    runs = snap.pipeline_runs if snap.pipeline_runs else _generate_demo_runs()

    # 表头
    headers = ["运行 ID", "策略", "阶段", "模型", "用例数", "DPO", "进度", "状态", "启动时间"]
    html = (
        '<div class="gp" style="overflow-x:auto">'
        '<table style="width:100%;border-collapse:separate;border-spacing:0;'
        'font-family:Inter,sans-serif;font-size:.78rem"><thead><tr>'
    )
    for h in headers:
        html += (
            f'<th style="padding:12px 8px;text-align:left;color:rgba(255,255,255,.35);'
            f'font-family:JetBrains Mono,monospace;font-size:.65rem;letter-spacing:1.2px;'
            f'text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,.04);'
            f'font-weight:500">{h}</th>'
        )
    html += "</tr></thead><tbody>"

    td_style = "padding:12px 8px;border-bottom:1px solid rgba(255,255,255,.02)"

    for r in runs:
        html += (
            '<tr style="transition:background .2s" '
            "onmouseover=\"this.style.background='rgba(108,92,231,.03)'\" "
            "onmouseout=\"this.style.background='transparent'\">"
        )

        # 提取并对所有动态字段进行 HTML 转义，防止 XSS
        run_id = escape(str(r.get("run_id", "—")))
        policy = escape(str(r.get("policy", "—")))
        stage = escape(_resolve_stage(r))
        model = escape(str(r.get("model", "—")))
        total = escape(str(r.get("total", 0)))
        dpo = escape(str(r.get("dpo_pairs_generated", 0)))
        prog = r.get("progress_pct", 0)
        status = r.get("status", "pending")
        started = escape(str(r.get("started_at", "—")))
        status_zh = escape(_STATUS_ZH.get(status, status))

        # 运行 ID
        html += (
            f'<td style="{td_style}"><span style="color:#6c5ce7;'
            f'font-family:JetBrains Mono,monospace;font-size:.73rem">'
            f"{run_id}</span></td>"
        )
        # 策略
        html += f'<td style="{td_style}"><span style="color:rgba(255,255,255,.6)">{policy}</span></td>'
        # 阶段（stage 来自映射表，颜色用原始未转义键查找）
        stage_clr = _STAGE_COLORS.get(_resolve_stage(r), "rgba(255,255,255,.3)")
        html += (
            f'<td style="{td_style}"><span style="color:{stage_clr};'
            f'font-family:JetBrains Mono,monospace;font-size:.73rem">'
            f"{stage}</span></td>"
        )
        # 模型
        html += (
            f'<td style="{td_style}"><span style="color:rgba(255,255,255,.45);'
            f'font-family:JetBrains Mono,monospace;font-size:.7rem">'
            f"{model}</span></td>"
        )
        # 用例数
        html += f'<td style="{td_style}"><span style="color:rgba(255,255,255,.6)">{total}</span></td>'
        # DPO
        html += f'<td style="{td_style}"><span style="color:rgba(255,255,255,.6)">{dpo}</span></td>'
        # 进度条（progress 是 float，无需转义）
        prog_val = float(prog)
        pc = (
            "#55efc4" if prog_val == 100
            else "#6c5ce7" if prog_val > 50
            else "#ffeaa7" if prog_val > 0
            else "rgba(255,255,255,.08)"
        )
        html += (
            f'<td style="{td_style}"><div style="display:flex;align-items:center;gap:6px">'
            f'<div class="pt" style="width:90px">'
            f'<div class="pf" style="width:{prog_val}%;background:{pc};'
            f'box-shadow:0 0 6px {pc}20"></div></div>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:.6rem;'
            f'color:rgba(255,255,255,.3)">{prog_val:.0f}%</span></div></td>'
        )
        # 状态徽章（badge_cls 来自映射表，安全；status_zh 已转义）
        badge_cls = _BADGE_MAP.get(status, "b-wait")
        html += f'<td style="{td_style}"><span class="badge {badge_cls}">{status_zh}</span></td>'
        # 启动时间
        html += (
            f'<td style="{td_style}"><span style="color:rgba(255,255,255,.4);'
            f'font-family:JetBrains Mono,monospace;font-size:.7rem">'
            f"{started}</span></td>"
        )
        html += "</tr>"

    html += "</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)
