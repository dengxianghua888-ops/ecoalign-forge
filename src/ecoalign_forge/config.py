"""Pydantic Settings — centralized configuration."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# 在 Settings 实例化前加载 .env 到 os.environ，让 litellm 等第三方库
# 能直接从环境变量读取 OPENAI_API_BASE / OPENAI_API_KEY 等配置。
# pydantic-settings 自己也会读 .env，但它只填 Settings 字段，不污染 os.environ。
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM Models (GPT-5.4 priority) ---
    chaos_creator_model: str = "openai/gpt-5.4-mini"
    moderator_model: str = "openai/gpt-5.4-mini"
    judge_model: str = "openai/gpt-5.4"

    # --- LLM 重试 ---
    llm_max_retries: int = 3
    llm_retry_wait_max: int = 30

    # --- LLM 推理强度（reasoning_effort）---
    # 适用于 gpt-5.x / o1 / o3 等支持 reasoning 的模型。设为 "high" / "medium" / "low"
    # 或 None（不传该参数）。LLMClient 会在每次调用时自动透传。
    llm_reasoning_effort: str | None = None

    # --- 解析校验重试（覆盖 JSON 解析失败 / Pydantic 校验失败的整次 LLM 调用）---
    parse_max_retries: int = 3
    parse_retry_wait_min: int = 1
    parse_retry_wait_max: int = 10

    # --- Synthesis ---
    default_batch_size: int = 10
    default_max_concurrent: int = 5
    default_temperature: float = 0.7

    # --- Storage ---
    data_dir: Path = Path("./data")
    datasets_dir: Path = Path("./data/datasets")

    # --- Dashboard ---
    dashboard_refresh_interval: int = 5000

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.datasets_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
