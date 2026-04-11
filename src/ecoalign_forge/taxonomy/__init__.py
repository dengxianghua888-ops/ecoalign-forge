"""taxonomy — 标准化红队攻击分类体系。

对齐 HarmBench 功能分类 + OWASP LLM Top 10 标准，
提供可扩展的攻击策略注册表和 Evol-Instruct 进化策略。

核心概念：
- HarmCategory: HarmBench 对齐的顶级危害分类
- AttackTechnique: 具体攻击技术（含成功率基线）
- EvolStrategy: 红队 prompt 进化策略（深度 + 广度）
"""

from ecoalign_forge.taxonomy.attack_registry import ATTACK_REGISTRY, AttackTechnique
from ecoalign_forge.taxonomy.evol_strategies import EVOL_STRATEGIES, EvolStrategy
from ecoalign_forge.taxonomy.harm_categories import HARM_TAXONOMY, HarmCategory

__all__ = [
    "ATTACK_REGISTRY",
    "EVOL_STRATEGIES",
    "HARM_TAXONOMY",
    "AttackTechnique",
    "EvolStrategy",
    "HarmCategory",
]
