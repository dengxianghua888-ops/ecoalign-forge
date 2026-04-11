"""Supreme Judge Agent 输出契约 — 内容分发分级模型.

`JudgeEvaluation` 是审核机器人对一条用户内容做出最终判决的强制结构化输出，
包含：策略 A/B 的命中标签、完整的三步思考链（CoT）、最终的 T0–T3 分发档位。

策略 A / 策略 B 的具体规则定义在项目根目录的 `guidelines.md`。
`reasoning_trace` 字段强制要求引用 guidelines.md 中已注册的规则编号
（A-XXX / B-XXX），编造的规则编号会被 Pydantic 拒绝并触发上层重试。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ecoalign_forge._guidelines import KNOWN_RULE_IDS

# reasoning_trace 中识别规则编号的正则（与 _guidelines.py 保持一致）
_RULE_ID_PATTERN = re.compile(r"\b([AB]-\d{3})\b")

# "未命中任何规则" 的合法显式声明短语，允许 reasoning_trace 不引用任何规则编号。
# Judge 在判定 T2/T3 且确实没有命中 A/B 时使用。
_NO_RULE_PHRASES = ("未命中", "无命中", "no rules", "未触发", "未匹配")

# 最终分发分级的离散字面量，按"严厉 → 宽松"排列：
#   T0_Block      直接屏蔽，最严厉
#   T1_Shadowban  限流/影子封禁，仅作者本人可见
#   T2_Normal     常规分发，无加权也无降权
#   T3_Recommend  加权推荐，最宽松
FinalDecision = Literal[
    "T0_Block",
    "T1_Shadowban",
    "T2_Normal",
    "T3_Recommend",
]


# Supreme Judge 与 Moderator 协作时的"严重度"映射，用于计算 DPO 偏好差距。
# 数值仅作 chosen/rejected_score 的内部排序使用，不暴露为 JSON 字段。
DECISION_SEVERITY: dict[FinalDecision, float] = {
    "T0_Block": 1.0,
    "T1_Shadowban": 0.7,
    "T2_Normal": 0.3,
    "T3_Recommend": 0.0,
}


class JudgeEvaluation(BaseModel):
    """Supreme Judge Agent 的强制结构化输出契约。

    一条用户生成内容经审核机器人后，必须返回符合本契约的 JSON。所有字段
    均为必填，任何缺失或类型不符都应触发上层 `SchemaValidationError` →
    指数退避重试（由 `LLMClient.generate_validated` 自动接管）。
    """

    has_stealth_marketing: bool = Field(
        ...,
        description=(
            "是否命中 guidelines.md 中【策略 A：高隐蔽性私域引流】。"
            "判断要点：文本/图片/评论里是否藏有微信号、个人 QQ、群口令、"
            "'+v 私聊'、'扣 1 发资料'、'主页简介有惊喜' 等私域导流暗号；"
            "是否使用谐音字、emoji、繁简混排、零宽字符等方式绕过关键词过滤。"
            "命中返回 true，未命中返回 false；**不允许返回 null 或省略**。"
        ),
    )

    is_ai_slop: bool = Field(
        ...,
        description=(
            "是否命中 guidelines.md 中【策略 B：低信息熵 AI 洗稿】。"
            "判断要点：内容是否表现出典型 AI 生成的低信息熵特征——"
            "套话堆砌、逻辑空转、缺乏第一手细节、段落间语义重复，"
            "或与已知爆款文本高度雷同、疑似批量改写。"
            "命中返回 true，未命中返回 false；**不允许返回 null 或省略**。"
        ),
    )

    reasoning_trace: str = Field(
        ...,
        min_length=1,
        description=(
            "完整的深度思考链（Chain-of-Thought），强制三步结构，"
            "每一步必须以固定前缀分段输出，便于下游正则解析：\n"
            "\n"
            "【第一步：特征提取】 列出从原文中识别出的所有可疑特征，"
            "包括具体的关键词、句式、emoji、外链格式、标点风格等，"
            "**必须引用原文片段**作为证据。\n"
            "\n"
            "【第二步：规则比对】 把第一步的每个可疑特征与 guidelines.md "
            "中的具体条款编号一一对应，明确说明命中或未命中哪条规则。"
            "若未命中任何规则也必须显式声明。\n"
            "\n"
            "【第三步:判决理由】 基于前两步推导出 final_decision 的取值，"
            "**必须解释为什么是 T0/T1/T2/T3 中的某一个而不是其他档位**，"
            "包括边界情况的取舍逻辑（例如同时疑似 A、B 但证据不足时降级处理）。\n"
            "\n"
            "三步前缀必须严格使用 '第一步：'、'第二步：'、'第三步：'，"
            "不允许英文或其他变体。"
        ),
    )

    final_decision: FinalDecision = Field(
        ...,
        description=(
            "最终分发分级，必须严格四选一，**不允许任何其他取值**：\n"
            "- 'T0_Block'：内容严重违规（例如同时命中策略 A 和 B、"
            "或包含其他不可接受内容），直接屏蔽，所有人不可见。\n"
            "- 'T1_Shadowban'：内容存在显著风险（例如单独命中策略 A 或 B），"
            "限流/影子封禁，仅作者本人可见，不进入任何推荐流。\n"
            "- 'T2_Normal'：内容合规，未命中任何策略，进入常规分发池，"
            "无加权也无降权。\n"
            "- 'T3_Recommend'：内容优质且合规（高信息熵、第一手内容、"
            "无任何私域导流痕迹），纳入推荐加权流量池。"
        ),
    )

    @field_validator("reasoning_trace")
    @classmethod
    def must_cite_known_rules_or_explicitly_opt_out(cls, v: str) -> str:
        """强校验：reasoning_trace 必须引用 KNOWN_RULE_IDS 中已注册的规则编号，
        或显式声明"未命中任何规则"。

        语义约束：
        - 若引用了 A-XXX/B-XXX 但 ID 不在 KNOWN_RULE_IDS（LLM 编造）→ 拒绝
        - 若没引用任何规则编号、也没有"未命中"类显式声明 → 拒绝
        - 引用合法规则、或合法显式声明"未命中" → 通过

        被拒绝时抛 ValueError，由 Pydantic 包装为 ValidationError，
        最终在 SupremeJudge._parse_evaluation 里转成 SchemaValidationError，
        触发 generate_validated 的指数退避重试机制。
        """
        cited = set(_RULE_ID_PATTERN.findall(v))
        unknown = cited - KNOWN_RULE_IDS
        if unknown:
            raise ValueError(
                f"reasoning_trace 引用了未注册的规则编号 {sorted(unknown)}，"
                f"guidelines.md 中只有 {sorted(KNOWN_RULE_IDS)}。"
                f"严禁编造规则编号。"
            )
        # 没引用规则时必须显式声明未命中
        if not cited and not any(phrase in v for phrase in _NO_RULE_PHRASES):
            raise ValueError(
                "reasoning_trace 既未引用任何 A-XXX/B-XXX 规则编号，"
                "也未显式声明'未命中'/'无命中'等。"
                "判定必须可追溯到具体规则或明确说明无规则触发。"
            )
        return v
