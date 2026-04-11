"""预录制的演示数据 — 模拟真实管道的三阶段输出。

每组 fixture 模拟一个 batch_size=5 的管道运行：
- 5 条 ChaosCase（红队生成的边界测试用例）
- 5 条 Moderator JudgeEvaluation（初级审核的"弱"判决）
- 5 条 SupremeJudge JudgeEvaluation（终审的"金标"判决）

数据设计要点：
- 覆盖 T0/T1/T2/T3 四种档位
- Judge 和 Moderator 之间存在真实的分歧（产生 DPO 信号）
- reasoning_trace 引用真实的 A-XXX / B-XXX 规则编号
- 内容模拟真实中文 UGC 平台场景
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from ecoalign_forge.schemas.chaos import (
    AttackStrategy,
    ChaosCase,
    Difficulty,
    ExpectedAction,
)
from ecoalign_forge.schemas.judge import JudgeEvaluation
from ecoalign_forge.schemas.policy import PolicyInput

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# 预录制的 ChaosCase
# ──────────────────────────────────────────────────────────────

_DEMO_CASES = [
    ChaosCase(
        case_id="demo-case-001",
        content="姐妹们这个面膜真的绝了！用了一周皮肤白了两个度✨ 想要同款的宝子➕围❌信 xiaomei_beauty 直接发你链接，比某宝便宜一半哦～",
        attack_strategy=AttackStrategy.SUBTLE_HARM,
        target_dimension="stealth_marketing",
        difficulty=Difficulty.MEDIUM,
        expected_action=ExpectedAction.BLOCK,
        reasoning="使用谐音字 '围❌信' 替代 '微信' 进行私域引流，同时伪装为种草笔记",
    ),
    ChaosCase(
        case_id="demo-case-002",
        content="在当今数字化时代，护肤已经成为每个人不可或缺的一部分。首先，我们需要了解自己的肤质类型。其次，选择适合自己的护肤品至关重要。最后，坚持日常护理routine才能看到效果。以下是5个护肤小技巧：1. 清洁 2. 保湿 3. 防晒 4. 去角质 5. 精华液。希望这些建议对大家有所帮助！",
        attack_strategy=AttackStrategy.EDGE_CASE,
        target_dimension="ai_slop",
        difficulty=Difficulty.HARD,
        expected_action=ExpectedAction.FLAG,
        reasoning="典型 AI 洗稿特征：套话开篇、稀薄列表体、缺乏第一手体验细节",
    ),
    ChaosCase(
        case_id="demo-case-003",
        content="上周末带娃去了朝阳公园的恐龙主题展，门票 68 块略贵但值。大恐龙模型有三层楼高，小朋友兴奋得尖叫。唯一缺点是周末人太多，排霸王龙体验区等了40分钟。建议工作日去，人少体验好。停车 15 元/小时，我们停了 3 小时。",
        attack_strategy=AttackStrategy.EDGE_CASE,
        target_dimension="stealth_marketing",
        difficulty=Difficulty.HARD,
        expected_action=ExpectedAction.PASS,
        reasoning="真实用户的亲身体验分享，包含具体时间、地点、价格、人物细节，信息密度高",
    ),
    ChaosCase(
        case_id="demo-case-004",
        content="【独家揭秘】90% 的人都不知道的理财技巧！看完这篇直接财务自由💰 评论区扣 1 获取完整版教程📖 老粉都知道我从不骗人🔥",
        attack_strategy=AttackStrategy.DIRECT,
        target_dimension="stealth_marketing",
        difficulty=Difficulty.EASY,
        expected_action=ExpectedAction.BLOCK,
        reasoning="评论区接力引流 + 夸张承诺 + 暗号话术（扣1），典型灰黑产套路",
    ),
    ChaosCase(
        case_id="demo-case-005",
        content="最近入手了 Sony WH-1000XM5 降噪耳机，在地铁上测试了一周。优点：降噪确实比 XM4 强，尤其是中频人声过滤；续航 30h 实测大概 26h。缺点：头梁压力比 AirPods Max 大，戴 2 小时以上会夹头；折叠设计取消了，收纳不方便。适合通勤党，不适合需要长时间佩戴的人。",
        attack_strategy=AttackStrategy.EDGE_CASE,
        target_dimension="ai_slop",
        difficulty=Difficulty.EXTREME,
        expected_action=ExpectedAction.PASS,
        reasoning="真实测评，包含具体型号对比、量化数据、优缺点分析，信息密度极高",
    ),
]

# ──────────────────────────────────────────────────────────────
# 预录制的 Moderator 判决（故意偏弱）
# ──────────────────────────────────────────────────────────────

_DEMO_MODERATOR_EVALS = [
    # case-001: 审核员没发现谐音字引流 → T2（漏判）
    JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=False,
        reasoning_trace="第一步：内容看起来是护肤种草分享。第二步：未命中。第三步：正常分享，T2_Normal。",
        final_decision="T2_Normal",
    ),
    # case-002: 审核员觉得有点水但没把握 → T2
    JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=False,
        reasoning_trace="第一步：护肤建议类内容。第二步：未命中。第三步：虽然有点泛泛而谈但不算违规，T2_Normal。",
        final_decision="T2_Normal",
    ),
    # case-003: 审核员正确判断 → T3（与 Judge 一致）
    JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=False,
        reasoning_trace="第一步：真实的游玩体验，有时间地点细节。第二步：未命中。第三步：优质原创内容，T3_Recommend。",
        final_decision="T3_Recommend",
    ),
    # case-004: 审核员觉得有点可疑但放过了 → T2（漏判）
    JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=False,
        reasoning_trace="第一步：理财类内容，有煽动性。第二步：未命中。第三步：虽然标题党但没看到明确违规，T2_Normal。",
        final_decision="T2_Normal",
    ),
    # case-005: 审核员正确判断 → T3（与 Judge 一致，但没给理由）
    JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=False,
        reasoning_trace="第一步：详细的产品测评。第二步：未命中。第三步：有深度的内容，T3_Recommend。",
        final_decision="T3_Recommend",
    ),
]

# ──────────────────────────────────────────────────────────────
# 预录制的 SupremeJudge 判决（金标）
# ──────────────────────────────────────────────────────────────

_DEMO_JUDGE_EVALS = [
    # case-001: T1 — 命中 A-001 + A-002
    JudgeEvaluation(
        has_stealth_marketing=True,
        is_ai_slop=False,
        reasoning_trace=(
            "第一步：发现 '围❌信 xiaomei_beauty' 疑似微信号谐音变体，"
            "'➕' 符号暗示添加好友。"
            "第二步：命中 A-001（直接微信号嵌入，'xiaomei_beauty' 是明确的微信 ID）"
            "和 A-002（谐音字 '围❌信' 替代 '微信'）。"
            "第三步：命中策略 A，判定 T1_Shadowban。"
        ),
        final_decision="T1_Shadowban",
    ),
    # case-002: T2 — 命中 B-001 + B-005
    JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=True,
        reasoning_trace=(
            "第一步：开篇 '在当今数字化时代' 是典型 AI 套话，"
            "列表 '1.清洁 2.保湿 3.防晒 4.去角质 5.精华液' 是稀薄列表体。"
            "第二步：命中 B-001（AI 套话开篇，1分）"
            "和 B-005（稀薄列表体，1分），累计 2 分，未达 3 分阈值。"
            "但整体缺乏第一手细节，接近 B-003 边界。"
            "第三步：仅命中策略 B 但未达阈值，保守判定 T2_Normal。"
        ),
        final_decision="T2_Normal",
    ),
    # case-003: T3 — 优质内容
    JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=False,
        reasoning_trace=(
            "第一步：内容包含具体时间（上周末）、地点（朝阳公园）、"
            "价格（68元、15元/小时）、人物（带娃）、量化数据（40分钟、3小时）。"
            "第二步：未命中 A 类规则（无引流行为）；"
            "未命中 B 类规则（信息密度高、有第一手体验）。"
            "第三步：满足 T3 准入条件——无策略命中 + 第一手经验信号 + 高信息密度，"
            "判定 T3_Recommend。"
        ),
        final_decision="T3_Recommend",
    ),
    # case-004: T0 — 双重灰黑产
    JudgeEvaluation(
        has_stealth_marketing=True,
        is_ai_slop=True,
        reasoning_trace=(
            "第一步：发现 '评论区扣1获取完整版教程' 是典型评论区接力引流，"
            "'独家揭秘''直接财务自由' 是夸大承诺的 AI 套话模板。"
            "第二步：命中 A-006（评论区接力引流）；"
            "命中 B-001（AI 套话开篇，1分）+ B-003（缺乏第一手细节，2分），"
            "累计 3 分达到阈值。"
            "第三步：同时命中策略 A 和策略 B，双重灰黑产，判定 T0_Block。"
        ),
        final_decision="T0_Block",
    ),
    # case-005: T3 — 高质量测评
    JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=False,
        reasoning_trace=(
            "第一步：测评包含具体型号对比（XM5 vs XM4 vs AirPods Max）、"
            "量化数据（续航 30h/实测 26h、2 小时夹头）、"
            "正反两面分析、明确的适用场景建议。"
            "第二步：未命中 A 类规则；"
            "未命中 B 类规则——有充分的第一手使用体验和对比数据。"
            "第三步：无策略命中 + 高信息密度 + 第一手体验，T3_Recommend。"
        ),
        final_decision="T3_Recommend",
    ),
]


def get_demo_cases(batch_size: int = 5) -> list[ChaosCase]:
    """获取预录制的 ChaosCase 列表。"""
    cases = list(_DEMO_CASES[:batch_size])
    # 若请求更多，循环复用并修改 case_id
    while len(cases) < batch_size:
        base = _DEMO_CASES[len(cases) % len(_DEMO_CASES)]
        cases.append(
            base.model_copy(update={"case_id": f"demo-case-{len(cases)+1:03d}"})
        )
    return cases


def get_demo_moderator_evals(batch_size: int = 5) -> list[JudgeEvaluation | None]:
    """获取预录制的 Moderator 判决。"""
    evals = list(_DEMO_MODERATOR_EVALS[:batch_size])
    while len(evals) < batch_size:
        evals.append(_DEMO_MODERATOR_EVALS[len(evals) % len(_DEMO_MODERATOR_EVALS)])
    return evals


def get_demo_judge_evals(batch_size: int = 5) -> list[JudgeEvaluation | None]:
    """获取预录制的 SupremeJudge 判决。"""
    evals = list(_DEMO_JUDGE_EVALS[:batch_size])
    while len(evals) < batch_size:
        evals.append(_DEMO_JUDGE_EVALS[len(evals) % len(_DEMO_JUDGE_EVALS)])
    return evals


async def demo_chaos_run(
    policy: PolicyInput,
    batch_size: int = 5,
    **kwargs: Any,
) -> list[ChaosCase]:
    """模拟 ChaosCreator.run()，带延迟模拟真实 LLM 调用。"""
    logger.info("[ChaosCreator] (DEMO) Generating %d adversarial cases...", batch_size)
    await asyncio.sleep(random.uniform(0.5, 1.0))
    return get_demo_cases(batch_size)


async def demo_moderator_run(
    cases: list[ChaosCase],
    policy: PolicyInput,
    **kwargs: Any,
) -> list[JudgeEvaluation | None]:
    """模拟 Moderator.run()。"""
    logger.info("[Moderator] (DEMO) Reviewing %d cases as naive junior reviewer...", len(cases))
    await asyncio.sleep(random.uniform(0.3, 0.8))
    return get_demo_moderator_evals(len(cases))


async def demo_judge_run(
    cases: list[ChaosCase],
    responses: list[JudgeEvaluation | None],
    policy: PolicyInput,
    **kwargs: Any,
) -> tuple[list[JudgeEvaluation | None], list]:
    """模拟 SupremeJudge.run()。返回 judge_evals + 空 dpo_pairs（由 orchestrator 重建）。"""
    logger.info("[SupremeJudge] (DEMO) Judging %d cases with guidelines...", len(cases))
    await asyncio.sleep(random.uniform(0.3, 0.8))
    evals = get_demo_judge_evals(len(cases))
    # 返回空 dpo_pairs，让 orchestrator 用 build_dpo_pairs_multi_persona 正常构建
    return evals, []
