"""quality — 多维度数据质量评分体系。

对 DPO_Pair 进行 6 个维度的自动化质量评估：
- reasoning_depth: 推理深度（规则引用数量）
- information_density: 信息密度（token 去重比）
- preference_clarity: 偏好清晰度（chosen-rejected gap）
- decision_consistency: 决策一致性（chosen/rejected 与 final_decision 映射）
- annotation_confidence: 标注置信度（来自 IAA 模块）
- overall: 综合质量分
"""

from ecoalign_forge.quality.scorer import QualityReport, QualityScorer

__all__ = ["QualityReport", "QualityScorer"]
