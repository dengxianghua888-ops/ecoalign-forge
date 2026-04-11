"""EcoAlign-Forge 快速入门示例"""

import asyncio
import sys
from pathlib import Path

# 确保可以导入项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoalign_forge.engine.orchestrator import AgentOrchestrator
from ecoalign_forge.schemas.pipeline import PipelineConfig
from ecoalign_forge.schemas.policy import PolicyDimension, PolicyInput


async def main():
    # 1. 定义内容审核策略（与 guidelines.md 的两策略 ontology 对齐）
    policy = PolicyInput(
        policy_id="quickstart-v1",
        name="内容分发分级平台",
        dimensions=[
            PolicyDimension(
                name="stealth_marketing",
                description="高隐蔽性私域引流：微信号、谐音字、emoji 夹带、暗号话术、二维码、评论区接力",
            ),
            PolicyDimension(
                name="ai_slop",
                description="低信息熵 AI 洗稿：套话开篇、语义重复、缺第一手细节、高度雷同、稀薄列表",
            ),
        ],
    )

    # 2. 配置管道参数
    config = PipelineConfig(
        num_samples=5,       # 快速测试：仅生成 5 个样本
        batch_size=5,        # 单批次处理
        max_concurrent=3,    # 最大并发 LLM 调用
    )

    # 3. 运行管道
    print("启动 EcoAlign-Forge 数据合成管道...")
    orchestrator = AgentOrchestrator(config=config)
    result = await orchestrator.run(policy=policy, num_samples=5)

    # 4. 输出结果
    print(f"\n合成完成！")
    print(f"   总用例数: {result.total_cases}")
    print(f"   评估数量: {result.total_evaluations}")
    print(f"   DPO 训练对: {result.total_dpo_pairs}")
    print(f"   平均质量分: {result.avg_quality_score:.2f}")
    print(f"   拦截率: {result.interception_rate:.1%}")
    print(f"   输出文件: {result.output_path}")

    # 5. 查看 DPO 对示例
    if result.dpo_pairs:
        print(f"\nDPO 训练对示例:")
        pair = result.dpo_pairs[0]
        print(f"   Prompt: {pair.prompt[:80]}...")
        print(f"   Chosen: {pair.chosen[:80]}...")
        print(f"   Rejected: {pair.rejected[:80]}...")
        print(f"   偏好差距: {pair.preference_gap:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
