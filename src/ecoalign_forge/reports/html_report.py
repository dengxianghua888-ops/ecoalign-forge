"""HTML 合成数据诊断报告生成器。

生成包含以下内容的自包含 HTML 报告（无外部依赖）：
- 数据集概览 KPI 卡片
- 判决严重度和偏好对启发式分布（内联 SVG）
- 策略覆盖率表格
- IAA 指标展示
- 合成轮次记录，训练效果和收敛状态保持未评估
- 攻击策略分布

参考：Garak HTML Report 风格
"""

from __future__ import annotations

import html as html_mod
import warnings
from datetime import UTC, datetime
from pathlib import Path

from ecoalign_forge.schemas.execution import ExecutionMode


def _esc(text: str) -> str:
    """HTML 转义，防止 XSS 注入。"""
    return html_mod.escape(str(text))


def generate_html_report(
    *,
    dataset_name: str = "EcoAlign-Forge DPO Dataset",
    total_pairs: int = 0,
    avg_decision_severity: float | None = None,
    avg_pair_quality_heuristic: float | None = None,
    avg_quality: float | None = None,
    avg_preference_gap: float = 0.0,
    interception_rate: float = 0.0,
    decision_counts: dict[str, int] | None = None,
    dimension_stats: dict[str, dict] | None = None,
    rule_coverage: dict[str, int] | None = None,
    iaa_metrics: dict | None = None,
    flywheel_summary: dict | None = None,
    quality_distribution: list[float] | None = None,
    severity_distribution: list[float] | None = None,
    pair_quality_heuristic_distribution: list[float] | None = None,
    execution_mode: ExecutionMode | str = ExecutionMode.UNKNOWN,
    run_id: str | None = None,
    fixture_version: str | None = None,
    output_path: str | Path = "./data/report.html",
) -> Path:
    """Generate a descriptive report, never a claim of model correctness.

    ``avg_quality`` and ``quality_distribution`` are deprecated names for
    severity data. Canonical arguments take precedence when both are supplied.
    Absent pair-quality data stays unknown, including in historical reports.
    """
    if avg_quality is not None:
        warnings.warn(
            "avg_quality is deprecated; it describes decision severity, not quality",
            DeprecationWarning,
            stacklevel=2,
        )
    if avg_decision_severity is None:
        avg_decision_severity = avg_quality if avg_quality is not None else 0.0
    if quality_distribution is not None:
        warnings.warn(
            "quality_distribution is deprecated; use severity_distribution",
            DeprecationWarning,
            stacklevel=2,
        )
        if severity_distribution is None:
            severity_distribution = quality_distribution
    mode = ExecutionMode(execution_mode)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    decision_counts = decision_counts or {}
    dimension_stats = dimension_stats or {}
    rule_coverage = rule_coverage or {}
    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    # KPI 卡片
    kpi_cards = _render_kpi_cards(
        total_pairs,
        avg_decision_severity,
        avg_pair_quality_heuristic,
        avg_preference_gap,
        interception_rate,
    )

    # 决策分布表
    decision_table = _render_decision_table(decision_counts)

    # 维度统计表
    dimension_table = _render_dimension_table(dimension_stats)

    # 规则覆盖率表
    rule_table = _render_rule_coverage(rule_coverage)

    # IAA 指标
    iaa_section = _render_iaa_section(iaa_metrics) if iaa_metrics else ""

    # Legacy quality trends and improvement values never become model evidence.
    flywheel_section = _render_flywheel_section(flywheel_summary or {})
    severity_chart = _render_quality_histogram(severity_distribution or [], label="判决严重度分布")
    heuristic_chart = _render_quality_histogram(
        pair_quality_heuristic_distribution or [], label="偏好对启发式分布"
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(dataset_name)} — 合成数据诊断</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #1f2329; line-height: 1.6; padding: 24px; }}
.container {{ max-width: 1100px; margin: 0 auto; }}
h1 {{ font-size: 28px; margin-bottom: 8px; }}
.subtitle {{ color: #646a73; font-size: 14px; margin-bottom: 32px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
.kpi-card {{ background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.kpi-value {{ font-size: 32px; font-weight: 700; color: #5178c6; }}
.kpi-label {{ font-size: 13px; color: #646a73; margin-top: 4px; }}
.section {{ background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.section h2 {{ font-size: 18px; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #f0f4fc; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th {{ background: #f0f4fc; text-align: left; padding: 10px 12px; font-weight: 600; }}
td {{ padding: 10px 12px; border-bottom: 1px solid #f0f0f0; }}
tr:hover td {{ background: #fafbfc; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
.badge-green {{ background: #dff5e5; color: #509863; }}
.badge-yellow {{ background: #fef1ce; color: #d4b45b; }}
.badge-red {{ background: #fee3e2; color: #d25d5a; }}
.badge-blue {{ background: #f0f4fc; color: #5178c6; }}
.progress-bar {{ width: 100%; height: 8px; background: #f0f0f0; border-radius: 4px; overflow: hidden; }}
.progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
.chart-container {{ text-align: center; padding: 16px 0; }}
.footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 32px; }}
</style>
</head>
<body>
<div class="container">
<h1>{_esc(dataset_name)}</h1>
<p class="subtitle">合成数据诊断 · 生成时间 {_esc(timestamp)} · by EcoAlign-Forge</p>
<div class="section">
<p>来源模式：<strong>{_esc(mode.value)}</strong> · run_id：{_esc(run_id or "未提供")} · fixture：{_esc(fixture_version or "未提供")}</p>
<p>{"预录演示数据，不代表真实模型执行。" if mode == ExecutionMode.DEMO else "模拟执行数据，不代表真实模型执行。" if mode == ExecutionMode.MOCK else "历史来源未知，不并入 live 证据。" if mode == ExecutionMode.UNKNOWN else "live 表示执行来源，不代表标签已经人工验证。"}</p>
<p>严重度表示判决档位；启发式分数和模型间一致性均不代表标签正确率。下游模型效果尚未评估。</p>
</div>

{kpi_cards}

<div class="section">
<h2>决策分布</h2>
{decision_table}
</div>

{severity_chart}
{heuristic_chart}

<div class="section">
<h2>维度拦截率</h2>
{dimension_table}
</div>

<div class="section">
<h2>规则覆盖率</h2>
{rule_table}
</div>

{iaa_section}
{flywheel_section}

<p class="footer">Generated by EcoAlign-Forge · Experimental preference-data pipeline</p>
</div>
</body>
</html>"""

    path.write_text(html, encoding="utf-8")
    return path


def _render_kpi_cards(
    total: int, severity: float, heuristic: float | None, gap: float, intercept: float
) -> str:
    heuristic_text = "未计算" if heuristic is None else f"{heuristic:.2f}"
    return f"""<div class="kpi-grid">
<div class="kpi-card"><div class="kpi-value">{total}</div><div class="kpi-label">DPO 偏好对总数</div></div>
<div class="kpi-card"><div class="kpi-value">{severity:.2f}</div><div class="kpi-label">平均判决严重度</div></div>
<div class="kpi-card"><div class="kpi-value">{heuristic_text}</div><div class="kpi-label">平均偏好对启发式分数</div></div>
<div class="kpi-card"><div class="kpi-value">{gap:.2f}</div><div class="kpi-label">平均偏好差距</div></div>
<div class="kpi-card"><div class="kpi-value">{intercept:.1%}</div><div class="kpi-label">拦截率 (T0+T1)</div></div>
</div>"""


def _render_decision_table(counts: dict[str, int]) -> str:
    total = sum(counts.values()) or 1
    rows = ""
    colors = {
        "T0_Block": "red",
        "T1_Shadowban": "yellow",
        "T2_Normal": "blue",
        "T3_Recommend": "green",
    }
    for dec in ("T0_Block", "T1_Shadowban", "T2_Normal", "T3_Recommend"):
        n = counts.get(dec, 0)
        pct = n / total * 100
        color = colors.get(dec, "blue")
        rows += f"""<tr>
<td><span class="badge badge-{color}">{_esc(dec)}</span></td>
<td>{n}</td>
<td>{pct:.1f}%</td>
<td><div class="progress-bar"><div class="progress-fill" style="width:{pct}%;background:{"#d25d5a" if color == "red" else "#d4b45b" if color == "yellow" else "#5178c6" if color == "blue" else "#509863"}"></div></div></td>
</tr>"""
    return f"<table><tr><th>档位</th><th>数量</th><th>占比</th><th>分布</th></tr>{rows}</table>"


def _render_dimension_table(stats: dict[str, dict]) -> str:
    if not stats:
        return "<p>暂无维度数据</p>"
    rows = ""
    for dim, s in stats.items():
        rate = s.get("interception_rate", 0)
        color = "red" if rate > 0.6 else "yellow" if rate > 0.3 else "green"
        rows += f"""<tr>
<td>{_esc(dim)}</td>
<td>{s.get("total", 0)}</td>
<td>{s.get("intercepted", 0)}</td>
<td><span class="badge badge-{color}">{rate:.1%}</span></td>
</tr>"""
    return f"<table><tr><th>维度</th><th>总数</th><th>拦截数</th><th>拦截率</th></tr>{rows}</table>"


def _render_rule_coverage(coverage: dict[str, int]) -> str:
    if not coverage:
        return "<p>暂无规则覆盖数据</p>"
    rows = ""
    for rule_id in sorted(coverage.keys()):
        hits = coverage[rule_id]
        color = "green" if hits > 0 else "red"
        rows += f'<tr><td>{_esc(rule_id)}</td><td>{hits}</td><td><span class="badge badge-{color}">{"已覆盖" if hits > 0 else "未覆盖"}</span></td></tr>'
    covered = sum(1 for h in coverage.values() if h > 0)
    total = len(coverage)
    rate = covered / total if total > 0 else 0
    return f"""<p>覆盖率: <strong>{covered}/{total} ({rate:.0%})</strong></p>
<table><tr><th>规则编号</th><th>命中次数</th><th>状态</th></tr>{rows}</table>"""


def _render_iaa_section(metrics: dict) -> str:
    def display(key):
        value = metrics.get(key)
        return f"{value:.3f}" if value is not None else "不可估计"

    return f"""<div class="section"><h2>候选分歧诊断</h2>
<p>Cohen's Kappa: {display("avg_cohens_kappa")} · Krippendorff's Alpha: {display("krippendorffs_alpha")}</p>
<p>故意偏置的候选不是独立标注者；一致性不代表判决正确，不用于质量筛选。</p></div>"""


def _render_flywheel_section(summary: dict) -> str:
    total_rounds = summary.get("total_rounds", 0)
    total_pairs = summary.get("cumulative_dpo_pairs", 0)

    return f"""<div class="section">
<h2>飞轮合成记录</h2>
<div class="kpi-grid">
<div class="kpi-card"><div class="kpi-value">{_esc(str(total_rounds))}</div><div class="kpi-label">记录轮次</div></div>
<div class="kpi-card"><div class="kpi-value">{_esc(str(total_pairs))}</div><div class="kpi-label">累计 DPO 对</div></div>
<div class="kpi-card"><div class="kpi-value">未评估</div><div class="kpi-label">模型质量提升</div></div>
<div class="kpi-card"><div class="kpi-value">未评估</div><div class="kpi-label">训练收敛</div></div>
</div>
<p>合成轮次、严重度变化或启发式分数变化不能证明模型效果改善；历史提升与收敛字段不用于评估。</p>
</div>"""


def _render_quality_histogram(scores: list[float], *, label: str) -> str:
    if not scores:
        return ""
    # 分桶：0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0
    bins = [0, 0, 0, 0, 0]
    for s in scores:
        idx = min(int(s * 5), 4)
        bins[idx] += 1

    max_count = max(bins) or 1
    w, h = 400, 180
    bar_w = 60
    labels = ["0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    colors = ["#5178c6"] * 5

    bars = ""
    for i, (count, bin_label, color) in enumerate(zip(bins, labels, colors, strict=True)):
        bar_h = (count / max_count) * (h - 50)
        x = 30 + i * (bar_w + 12)
        y = h - 30 - bar_h
        bars += f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="{color}" rx="4"/>'
        bars += f'<text x="{x + bar_w / 2}" y="{y - 5}" text-anchor="middle" font-size="12" fill="#333">{count}</text>'
        bars += f'<text x="{x + bar_w / 2}" y="{h - 10}" text-anchor="middle" font-size="11" fill="#999">{bin_label}</text>'

    return f"""<div class="section">
<h2>{_esc(label)}</h2>
<p>本图包含 {len(scores)} 个观测值；与偏好对总数的分母可能不同。此分布不是正确率。</p>
<div class="chart-container">
<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">{bars}</svg>
</div>
</div>"""
