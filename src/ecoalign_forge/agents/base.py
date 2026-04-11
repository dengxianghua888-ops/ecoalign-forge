"""BaseAgent — abstract base class for all pipeline agents."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from ecoalign_forge.llm.client import LLMClient

logger = logging.getLogger(__name__)

# 完整匹配 markdown 代码块：```lang\n...\n```
_MD_CODE_BLOCK = re.compile(r"^```[^\n]*\n(.*?)\n?```\s*$", re.DOTALL)


class BaseAgent(ABC):
    """Abstract base for ChaosCreator, Moderator, and SupremeJudge."""

    name: str = "BaseAgent"

    def __init__(self, llm: LLMClient, model: str | None = None) -> None:
        self.llm = llm
        self.model = model

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the agent's core logic. Subclasses must implement."""
        ...

    def _log(self, msg: str) -> None:
        logger.info(f"[{self.name}] {msg}")

    @staticmethod
    def _extract_json(raw: str, mode: str = "object") -> str:
        """从 LLM 原始响应中提取 JSON 字符串。

        支持以下场景：
        - 纯 JSON 字符串
        - 被 markdown 代码块（```json ... ```）包裹的 JSON
        - JSON 前后混杂自然语言说明文字

        参数:
            raw: LLM 原始响应
            mode: "object" 提取 {...}，"array" 提取 [...]

        返回:
            提取出的 JSON 子字符串（未解析）
        """
        text = raw.strip()
        # 用正则完整剥离 ```lang\n...\n``` 外壳，避免嵌套反引号误截断
        m = _MD_CODE_BLOCK.match(text)
        text = m.group(1).strip() if m else text.strip()

        # 根据模式定位 JSON 边界字符
        if mode == "array":
            start_char, end_char = "[", "]"
        else:
            start_char, end_char = "{", "}"

        start = text.find(start_char)
        end = text.rfind(end_char) + 1
        if start >= 0 and end > start:
            return text[start:end]
        return text
