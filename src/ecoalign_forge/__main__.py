"""CLI entry point: python -m ecoalign_forge"""

import argparse
import asyncio
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ecoalign-forge",
        description="Multi-Agent DPO Data Synthesis Factory",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode with pre-recorded data (no API key needed)",
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=5,
        help="Number of samples to generate (default: 5)",
    )
    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from ecoalign_forge.engine.orchestrator import AgentOrchestrator
    from ecoalign_forge.schemas.policy import PolicyDimension, PolicyInput

    # 默认策略：与 guidelines.md 的两策略 ontology 对齐
    policy = PolicyInput(
        policy_id="default-v1",
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

    if args.demo:
        print("\n" + "=" * 60)
        print("  EcoAlign-Forge  DEMO MODE")
        print("  No API key needed — using pre-recorded agent responses")
        print("=" * 60 + "\n")

    orchestrator = AgentOrchestrator(demo=args.demo)

    try:
        result = asyncio.run(
            orchestrator.run(policy=policy, num_samples=args.num_samples)
        )
    except Exception as e:
        print(f"\n Pipeline failed: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    # 结果摘要
    print("\n" + "=" * 60)
    print("  Pipeline Complete!")
    print("=" * 60)
    print(f"  Total cases:      {result.total_cases}")
    print(f"  Evaluations:      {result.total_evaluations}")
    print(f"  DPO pairs:        {result.total_dpo_pairs}")
    print(f"  Avg quality:      {result.avg_quality_score:.2f}")
    print(f"  Interception rate: {result.interception_rate:.1%}")
    print(f"  Output:           {result.output_path}")

    if result.dpo_pairs:
        pair = result.dpo_pairs[0]
        print("\n  Sample DPO pair:")
        print(f"    Prompt:   {pair.prompt[:70]}...")
        print(f"    Chosen:   {pair.chosen[:70]}...")
        print(f"    Rejected: {pair.rejected[:70]}...")
        print(f"    Gap:      {pair.preference_gap:.2f}")
        if pair.lineage:
            print(f"    Lineage:  policy={pair.lineage.source_policy_id}, "
                  f"judge={pair.lineage.judge_model}")

    print()


if __name__ == "__main__":
    main()
