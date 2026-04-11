"""guidelines.md 加载器 + 规则编号注册表（延迟初始化单例）.

通过 `functools.lru_cache` 实现延迟加载：首次调用 `get_guidelines_text()`
或 `get_known_rule_ids()` 时才从磁盘读取 `guidelines.md`。这避免了模块
导入期的文件 I/O 副作用——CI 环境或单元测试中无需真实文件也能正常 import。

同时保留 `GUIDELINES_TEXT` / `KNOWN_RULE_IDS` 作为模块级别名以兼容现有代码。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ecoalign_forge.exceptions import EcoAlignError

# 项目根目录 = src/ecoalign_forge/_guidelines.py 的上三级
# /<project>/src/ecoalign_forge/_guidelines.py
#  └─ parents[0]=ecoalign_forge, [1]=src, [2]=<project>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUIDELINES_PATH = PROJECT_ROOT / "guidelines.md"

# 规则编号格式：A-001, A-002, ..., B-001, B-002, ...
_RULE_ID_PATTERN = re.compile(r"\b([AB]-\d{3})\b")


def _load_guidelines() -> str:
    """加载并校验 guidelines.md。失败抛 EcoAlignError，不静默降级。"""
    if not GUIDELINES_PATH.exists():
        raise EcoAlignError(
            f"找不到 guidelines.md（{GUIDELINES_PATH}）。"
            f"Supreme Judge 必须依据手册做判决，请确认文件存在。"
        )
    text = GUIDELINES_PATH.read_text(encoding="utf-8")
    if not text.strip():
        raise EcoAlignError(
            f"guidelines.md 是空文件（{GUIDELINES_PATH}）。"
            f"Supreme Judge 无法在没有规则的情况下工作。"
        )
    return text


def _extract_rule_ids(text: str) -> frozenset[str]:
    """从 SOP 文本中正则提取所有 A-XXX / B-XXX 形式的规则编号。"""
    return frozenset(_RULE_ID_PATTERN.findall(text))


@lru_cache(maxsize=1)
def get_guidelines_text() -> str:
    """延迟加载 guidelines.md 文本（首次调用时读盘，后续缓存）。"""
    text = _load_guidelines()
    rule_ids = _extract_rule_ids(text)
    if not rule_ids:
        raise EcoAlignError(
            f"guidelines.md 中未发现任何 A-XXX / B-XXX 规则编号"
            f"（{GUIDELINES_PATH}）。请检查规则手册格式。"
        )
    return text


@lru_cache(maxsize=1)
def get_known_rule_ids() -> frozenset[str]:
    """延迟加载规则编号集合（依赖 get_guidelines_text 的缓存）。"""
    return _extract_rule_ids(get_guidelines_text())


# 兼容现有代码的模块级属性访问（通过 __getattr__ 延迟求值）
def __getattr__(name: str):
    if name == "GUIDELINES_TEXT":
        return get_guidelines_text()
    if name == "KNOWN_RULE_IDS":
        return get_known_rule_ids()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
