"""包内默认手册加载器与规则编号注册表。

首次读取时加载包内唯一手册，后续缓存。资源访问不依赖源码布局或当前工作
目录，也支持从 wheel/zip 读取。兼容的 ``GUIDELINES_TEXT`` / ``KNOWN_RULE_IDS``
属性在访问时加载，因此调用方使用 ``from ... import`` 时仍可能立即读取手册。
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable

from ecoalign_forge.exceptions import EcoAlignError

# 保留旧属性名；其类型是包资源 Traversable，不保证是本地文件系统 Path。
GUIDELINES_PATH: Traversable = files("ecoalign_forge").joinpath("resources", "guidelines.md")

# 规则编号格式：A-001, A-002, ..., B-001, B-002, ...
_RULE_ID_PATTERN = re.compile(r"\b([AB]-\d{3})\b")


def _load_guidelines() -> str:
    """加载并校验 guidelines.md。失败抛 EcoAlignError，不静默降级。"""
    if not GUIDELINES_PATH.is_file():
        raise EcoAlignError(
            f"找不到 guidelines.md（{GUIDELINES_PATH}）。"
            "Supreme Judge 必须依据手册做判决，请检查安装包是否完整。"
        )
    try:
        text = GUIDELINES_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EcoAlignError(f"无法读取 guidelines.md（{GUIDELINES_PATH}）: {exc}") from exc
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
