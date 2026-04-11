"""TRL 标准 DPO 格式导出。

输出格式兼容 HuggingFace TRL DPOTrainer：
  {"prompt": str, "chosen": str, "rejected": str}

同时支持扩展字段（chosen_rating / rejected_rating），
兼容 UltraFeedback 风格的偏好数据集。
"""

from __future__ import annotations

import json
from pathlib import Path

from ecoalign_forge.schemas.dpo import DPO_Pair


def to_trl_dict(
    pair: DPO_Pair,
    *,
    include_metadata: bool = False,
    conversational: bool = False,
) -> dict:
    """将单条 DPO_Pair 转换为 TRL 标准字典。

    Args:
        pair: DPO 偏好对
        include_metadata: 是否包含扩展元数据字段
        conversational: 是否使用 TRL >=0.8 的对话格式
            False → {"prompt": str, "chosen": str, "rejected": str}
            True  → {"prompt": str, "chosen": [{"role":"assistant","content":...}], ...}

    Returns:
        TRL 兼容的字典
    """
    if conversational:
        record = {
            "prompt": pair.prompt,
            "chosen": [{"role": "assistant", "content": pair.chosen}],
            "rejected": [{"role": "assistant", "content": pair.rejected}],
        }
    else:
        record = {
            "prompt": pair.prompt,
            "chosen": pair.chosen,
            "rejected": pair.rejected,
        }
    if include_metadata:
        record["chosen_rating"] = pair.chosen_score
        record["rejected_rating"] = pair.rejected_score
        record["preference_gap"] = pair.preference_gap
        record["dimension"] = pair.dimension
        record["difficulty"] = pair.difficulty
        record["source_case_id"] = pair.source_case_id
        record["pair_id"] = pair.pair_id
        if pair.lineage is not None:
            record["lineage"] = pair.lineage.model_dump(mode="json")
    return record


def export_trl(
    pairs: list[DPO_Pair],
    output_path: str | Path,
    *,
    include_metadata: bool = False,
    conversational: bool = False,
) -> Path:
    """将 DPO 数据集导出为 TRL 标准 JSONL 格式。

    Args:
        pairs: DPO 偏好对列表
        output_path: 输出文件路径
        include_metadata: 是否包含扩展元数据

    Returns:
        实际写入的文件路径
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        for pair in pairs:
            record = to_trl_dict(pair, include_metadata=include_metadata, conversational=conversational)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return path


def export_trl_dataset_card(
    pairs: list[DPO_Pair],
    output_dir: str | Path,
    *,
    dataset_name: str = "ecoalign-forge-dpo",
    description: str = "",
) -> Path:
    """生成 HuggingFace Dataset Card (README.md)。

    Args:
        pairs: 用于统计的 DPO 数据
        output_dir: 输出目录
        dataset_name: 数据集名称
        description: 数据集描述

    Returns:
        Dataset Card 文件路径
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    n = len(pairs)
    avg_gap = sum(p.preference_gap for p in pairs) / n if n > 0 else 0.0

    # 统计维度分布
    dim_counts: dict[str, int] = {}
    for p in pairs:
        dim_counts[p.dimension] = dim_counts.get(p.dimension, 0) + 1

    dim_table = "\n".join(
        f"| {dim} | {count} | {count / n * 100:.1f}% |"
        for dim, count in sorted(dim_counts.items())
    )

    card = f"""---
dataset_info:
  features:
    - name: prompt
      dtype: string
    - name: chosen
      dtype: string
    - name: rejected
      dtype: string
  splits:
    - name: train
      num_examples: {n}
tags:
  - dpo
  - preference
  - content-moderation
  - synthetic
license: apache-2.0
task_categories:
  - text-classification
language:
  - zh
---

# {dataset_name}

{description or '由 EcoAlign-Forge 多智能体管道自动合成的 DPO 偏好训练数据集。'}

## 数据集统计

| 指标 | 值 |
|------|-----|
| 总样本数 | {n} |
| 平均偏好差距 | {avg_gap:.3f} |

## 维度分布

| 维度 | 样本数 | 占比 |
|------|--------|------|
{dim_table}

## 使用方式

```python
from datasets import load_dataset
from trl import DPOTrainer

dataset = load_dataset("json", data_files="train.jsonl")
# 直接用于 DPOTrainer
```

## 生成方式

数据通过 [EcoAlign-Forge](https://github.com/dengxianghua888-ops/ecoalign-forge) 的三阶段对抗管道生成：
1. **ChaosCreator** — 红队攻击 Agent 反向构造边界用例
2. **Moderator** — 多 persona 初级审核（故意不参考手册）
3. **SupremeJudge** — 终审 Agent 按 guidelines.md 金标判决

偏好对构建策略：
- 直接分歧：Judge 与 Moderator 的 final_decision 不同
- 推理质量：同档位但 Judge 引用规则 ≥2 条、Moderator 0 条
"""

    card_path = output_dir / "README.md"
    card_path.write_text(card, encoding="utf-8")
    return card_path
