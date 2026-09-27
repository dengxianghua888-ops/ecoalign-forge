"""Recorded-data quickstart; no LLM API calls or credentials are required."""

import asyncio

from ecoalign_forge.config import settings
from ecoalign_forge.engine.orchestrator import AgentOrchestrator
from ecoalign_forge.reports import generate_html_report
from ecoalign_forge.schemas.pipeline import PipelineConfig
from ecoalign_forge.schemas.policy import PolicyDimension, PolicyInput


async def main() -> int:
    policy = PolicyInput(
        policy_id="quickstart-v1",
        name="内容分发分级平台",
        dimensions=[
            PolicyDimension(name="stealth_marketing", description="高隐蔽性私域引流"),
            PolicyDimension(name="ai_slop", description="低信息量、重复、缺少第一手细节"),
        ],
    )
    config = PipelineConfig(num_samples=5, batch_size=5)
    orchestrator = AgentOrchestrator(config=config, demo=True)
    result = await orchestrator.run(policy=policy)

    print(f"状态: {result.status.value}")
    print(f"执行模式: {result.execution_mode.value}（预录数据，不代表真实模型执行）")
    print(f"Fixture: {result.fixture_version}")
    print(f"阶段计数: {result.counts.model_dump()}")
    print(f"平均判决严重度: {result.avg_decision_severity:.2f}（不是正确率）")
    print(f"偏好对启发式分数: {result.avg_pair_quality_heuristic}")
    print(f"候选偏好对: {result.total_dpo_pairs}")
    print(f"输出文件: {result.output_path}")
    print(f"诊断文件: {result.diagnostics_path}")
    if result.error:
        print(f"错误: {result.error}")

    heuristic_scores = [
        pair.lineage.quality_scores["overall"]
        for pair in result.dpo_pairs
        if pair.lineage is not None and "overall" in pair.lineage.quality_scores
    ]
    report_path = generate_html_report(
        dataset_name="EcoAlign-Forge recorded demo",
        execution_mode=result.execution_mode,
        run_id=result.run_id,
        fixture_version=result.fixture_version,
        total_pairs=result.total_dpo_pairs,
        avg_decision_severity=result.avg_decision_severity,
        avg_pair_quality_heuristic=result.avg_pair_quality_heuristic,
        avg_preference_gap=(
            sum(pair.preference_gap for pair in result.dpo_pairs) / result.total_dpo_pairs
            if result.total_dpo_pairs
            else 0.0
        ),
        interception_rate=result.interception_rate,
        decision_counts=orchestrator.metrics.decision_counts,
        dimension_stats=result.dimension_stats,
        severity_distribution=orchestrator.metrics.severity_scores,
        pair_quality_heuristic_distribution=heuristic_scores,
        flywheel_summary=orchestrator.flywheel.get_summary() if orchestrator.flywheel else None,
        output_path=settings.data_dir
        / result.execution_mode.value
        / f"report_{result.run_id}.html",
    )
    print(f"HTML 诊断报告: {report_path.resolve()}")
    print("模型质量提升与训练收敛：未评估。")
    return result.status.exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
