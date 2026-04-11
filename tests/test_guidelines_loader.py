"""guidelines.md 加载器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ecoalign_forge import _guidelines as gl
from ecoalign_forge._guidelines import (
    GUIDELINES_PATH,
    GUIDELINES_TEXT,
    KNOWN_RULE_IDS,
)
from ecoalign_forge.exceptions import EcoAlignError


class TestGuidelinesLoader:
    """加载器在导入期完成；这里验证常量值与 fail-fast 行为。"""

    def test_guidelines_text_loaded_at_import(self) -> None:
        """模块导入后 GUIDELINES_TEXT 应非空且包含关键规则编号"""
        assert isinstance(GUIDELINES_TEXT, str)
        assert len(GUIDELINES_TEXT) > 100
        assert "A-001" in GUIDELINES_TEXT
        assert "A-002" in GUIDELINES_TEXT
        assert "B-001" in GUIDELINES_TEXT
        assert "B-002" in GUIDELINES_TEXT

    def test_guidelines_path_resolves_to_project_root(self) -> None:
        """路径解析应指向项目根目录的 guidelines.md"""
        assert isinstance(GUIDELINES_PATH, Path)
        assert GUIDELINES_PATH.name == "guidelines.md"
        assert GUIDELINES_PATH.exists()

    def test_loader_raises_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """文件不存在应抛 EcoAlignError（fail-fast 而非静默返回空字符串）"""
        fake_path = tmp_path / "nonexistent_guidelines.md"
        monkeypatch.setattr(gl, "GUIDELINES_PATH", fake_path)
        with pytest.raises(EcoAlignError, match=r"找不到 guidelines\.md"):
            gl._load_guidelines()

    def test_loader_raises_when_file_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空文件应抛 EcoAlignError（空手册等同于配置错误）"""
        empty_path = tmp_path / "empty.md"
        empty_path.write_text("   \n  \n", encoding="utf-8")
        monkeypatch.setattr(gl, "GUIDELINES_PATH", empty_path)
        with pytest.raises(EcoAlignError, match="空文件"):
            gl._load_guidelines()

    def test_known_rule_ids_extracted_from_guidelines(self) -> None:
        """KNOWN_RULE_IDS 应包含 SOP 中所有 A-XXX / B-XXX 编号"""
        assert isinstance(KNOWN_RULE_IDS, frozenset)
        # 当前 SOP 至少应该有 A-001~A-006 + B-001~B-006 共 12 条
        assert "A-001" in KNOWN_RULE_IDS
        assert "A-006" in KNOWN_RULE_IDS
        assert "B-001" in KNOWN_RULE_IDS
        assert "B-006" in KNOWN_RULE_IDS
        assert len(KNOWN_RULE_IDS) >= 12

    def test_extract_rule_ids_recognizes_format(self) -> None:
        """正则应只匹配 A-XXX / B-XXX 格式，不误匹配其他"""
        text = "Hits A-001 and B-002 but not C-003 or AAB-001 or A-1234"
        ids = gl._extract_rule_ids(text)
        assert ids == frozenset({"A-001", "B-002"})
