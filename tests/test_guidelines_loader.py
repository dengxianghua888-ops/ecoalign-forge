"""guidelines.md 加载器测试。"""

from __future__ import annotations

from importlib.resources import files
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
    """验证包内规则资源、兼容属性与 fail-fast 行为。"""

    @pytest.fixture(autouse=True)
    def clear_caches(self):
        gl.get_guidelines_text.cache_clear()
        gl.get_known_rule_ids.cache_clear()
        yield
        gl.get_guidelines_text.cache_clear()
        gl.get_known_rule_ids.cache_clear()

    def test_guidelines_text_loaded_at_import(self) -> None:
        """模块导入后 GUIDELINES_TEXT 应非空且包含关键规则编号"""
        assert isinstance(GUIDELINES_TEXT, str)
        assert len(GUIDELINES_TEXT) > 100
        assert "A-001" in GUIDELINES_TEXT
        assert "A-002" in GUIDELINES_TEXT
        assert "B-001" in GUIDELINES_TEXT
        assert "B-002" in GUIDELINES_TEXT

    def test_guidelines_are_package_resource(self) -> None:
        """默认规则来自包资源，而不是仓库根目录的入口说明。"""
        resource = files("ecoalign_forge").joinpath("resources", "guidelines.md")
        assert GUIDELINES_PATH.name == "guidelines.md"
        assert GUIDELINES_PATH.is_file()
        assert gl.get_guidelines_text() == resource.read_text(encoding="utf-8")

    def test_working_directory_cannot_override_guidelines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """安装后从任意目录运行；当前目录的同名文件不能覆盖默认规则。"""
        (tmp_path / "guidelines.md").write_text("Untrusted local A-999", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert gl.get_guidelines_text() == GUIDELINES_TEXT
        assert "A-999" not in gl.get_known_rule_ids()

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

    def test_loader_rejects_missing_rule_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        no_rules = tmp_path / "guidelines.md"
        no_rules.write_text("This manual has no rule identifiers.", encoding="utf-8")
        monkeypatch.setattr(gl, "GUIDELINES_PATH", no_rules)
        with pytest.raises(EcoAlignError, match="未发现任何"):
            gl.get_guidelines_text()

    def test_loader_rejects_invalid_encoding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invalid = tmp_path / "guidelines.md"
        invalid.write_bytes(b"\xff")
        monkeypatch.setattr(gl, "GUIDELINES_PATH", invalid)
        with pytest.raises(EcoAlignError, match="无法读取"):
            gl._load_guidelines()

    def test_extract_rule_ids_recognizes_format(self) -> None:
        """正则应只匹配 A-XXX / B-XXX 格式，不误匹配其他"""
        text = "Hits A-001 and B-002 but not C-003 or AAB-001 or A-1234"
        ids = gl._extract_rule_ids(text)
        assert ids == frozenset({"A-001", "B-002"})
