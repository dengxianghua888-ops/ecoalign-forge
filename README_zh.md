# EcoAlign-Forge

面向中文内容审核的实验性偏好数据合成工具：通过多角色判决生成带规则引用与来源记录的候选训练样本。

[English](README.md) · [迁移说明](docs/iteration-a-migration.md) · [验收状态](docs/iteration-a-acceptance.md) · [变更记录](CHANGELOG.md)

**Alpha — 0.2.1a1。** 当前流程包含边界内容生成、审核员判决、按规则判决、可选复核，以及根据最终判决构建候选偏好对。现有规则聚焦隐蔽引流与低信息量内容。生成目标、模型判决和启发式分数都不是经验证标签；人工复核有效率和下游训练收益尚未建立。

## 先运行预录 Demo

需要 Python 3.11 或更新版本：

```bash
git clone https://github.com/dengxianghua888-ops/ecoalign-forge.git
cd ecoalign-forge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m ecoalign_forge --demo --num-samples 5
```

Demo 使用固定预录响应，不调用 LLM API。终端显示执行模式、最终状态、阶段计数、判决严重度、偏好对启发式分数与输出路径。它用于体验预录数据流程，不能证明真实模型能力。当前版本实际做了哪些验证，以[验收记录](docs/iteration-a-acceptance.md)为准。

如需运行 Python 示例并生成本地 HTML 诊断报告：

```bash
python examples/quickstart.py
```

示例同样默认 `demo=True`。用浏览器打开它打印的报告路径。报告来自该次运行；严重度与启发式分数不代表正确率。

## 流程与运行状态

```text
内置规则 + 生成目标
  → 带 request_item_id 的合成内容
  → 审核员判决 → 按规则判决
  → 对照规则进行可选判决复核
  → 最终判决 → 候选偏好对 + 来源记录 + 诊断
```

每次生成必须完整且唯一地返回所有请求 ID。程序按 ID 恢复顺序，并从本地请求写入 `metadata.generation_target`，它记录生成意图，不能充当 ground truth。复核失败保留失败状态，不会变成“确认一致”。复核器当前只接收判决与规则，没有输入原文；核验原文证据仍属于 F09 后续工作。

`completed` 表示处理完成，包含判决有效但没有偏好信号的情况。它不表示每条内容都产出训练对，也不表示标签正确。最终计数满足：

```text
completed + failed + unattempted = requested
```

CLI 退出码：**0** 完成、**3** 部分失败、**1** 失败、**130** 取消、**2** 参数错误。自动化脚本应检查退出码和 `status`，不能仅凭数据文件存在认定成功。

## 模式隔离与数据位置

默认新输出按执行来源分开保存：

```text
data/
├── demo/                     # 预录演示
│   ├── metrics.json
│   ├── runs.jsonl
│   ├── flywheel_state.json
│   └── diagnostics_<run-id>.json
├── live/                     # 真实模型调用
├── mock/                     # 显式测试执行
└── datasets/
    ├── demo/dpo_pairs_*.jsonl
    ├── live/dpo_pairs_*.jsonl
    └── mock/dpo_pairs_*.jsonl
```

运行记录和样本血缘包含 `execution_mode`，Demo 还标明 fixture 版本。历史文件缺少来源时记为 `unknown`，不会自动并入真实模型证据。可通过 `DATA_DIR` 和 `DATASETS_DIR` 修改基础目录。按阶段恢复、断点续跑仍是后续工作。

## 运行少量真实模型样本

在仓库根目录复制配置，填写实际可用的服务地址、凭据与模型 ID：

```bash
cp .env.example .env
# 编辑服务商凭据/API base，以及三个 Agent 的模型配置。
python -m ecoalign_forge --num-samples 5
```

不加 `--demo` 会调用真实模型，内容与规则会发送到配置的模型服务商，并可能产生费用。当前没有经过验证的单对成本，也没有自动预算上限。先用小批量查看失败原因与输出。

执行仅支持 `zh`/`zh-CN`；维度必须是 `stealth_marketing`、`ai_slop` 的非空、无重复子集，严重度元数据保持默认。唯一规则正文是[包内 A/B 手册](src/ecoalign_forge/resources/guidelines.md)。维度 description、examples 和平台 context 只是描述性元数据，不会替换手册或定义新策略；选择单一维度不会改变 A/B 分级矩阵。

**配置边界：** `PipelineConfig.num_samples` 与 `batch_size` 控制运行数量。`DEFAULT_*` 合成环境字段，以及 `PipelineConfig.max_concurrent`、`temperature`、`min_preference_gap` 尚未完整接入执行，不能当作已生效的并发、温度或过滤控制。`PARSE_*` 控制有限次数的解析重试。全局限流、预算账本和配置统一另行迭代。

## 打开 Dashboard

Dashboard 当前通过源码目录启动；仅安装 wheel 不包含 `dashboard/` 应用目录。激活虚拟环境后，**在已克隆的仓库根目录**运行：

```bash
python -m pip install -e '.[dashboard]'
python -m streamlit run dashboard/app.py --server.port 8501
```

打开 Streamlit 打印的本地地址，并明确选择数据来源。没有数据就显示空态，读取失败就显示错误，不以合成成功数据兜底。尚无实际连接探测的组件显示“未检测”。界面可见不等于模型质量验收。

## 导出候选数据

先用普通文本格式检查现有导出结构：

```python
from ecoalign_forge.export import export_trl
from ecoalign_forge.storage.store import DataStore

pairs = DataStore().load_dpo_pairs("PATH_PRINTED_BY_YOUR_RUN")
export_trl(pairs, "train.jsonl", include_metadata=True)
```

记录包含 `prompt`、`chosen`、`rejected`，`include_metadata=True` 在该格式中保留来源信息。仓库也有 ShareGPT 和 conversational 导出器，但锁定版本的训练消费端验证尚未完成；尤其不能宣称当前 conversational 格式已兼容最新 TRL 聊天模板。JSON 可导出不等于训练通过或模型改善，见[任务台账 F10](docs/review-findings.csv)。

## 如何理解指标

| 指标 | 含义 |
|---|---|
| `avg_decision_severity` | T0–T3 映射后的平均严重度，越高表示判决越严格 |
| `avg_pair_quality_heuristic` | 候选偏好对的结构与启发式特征；未计算时为 `null` |
| `interception_rate` | T0/T1 占比，不是识别准确率 |
| 规则覆盖 | 判决中观察到的规则引用，不代表引用语义正确 |
| IAA | 模型判决之间的一致性，不能证明哪一方正确 |
| 飞轮记录 | 合成轮次记录；模型质量提升、训练收敛始终为**未评估** |

历史 `avg_quality_score`/`avg_quality` 实际描述严重度。兼容读取会告警，不能把旧值继续画成正确率或训练提升，详见[迁移说明](docs/iteration-a-migration.md)。

## 当前边界与开发

本版本聚焦中文文本的 A/B 内容分发规则，尚不提供通用安全策略执行、AI 作者识别、生产审核服务或自动训练闭环。代码中有四种审核员 persona，默认编排每次运行只使用一种。项目不承诺替代人工标注、固定低成本或下游模型收益。

```bash
python -m pip install -e '.[dev]'
python -m pytest tests/
python -m ruff check src/ tests/
```

提交问题时请附版本/commit、执行模式、命令、脱敏配置、最终状态和诊断；不要提交凭据与私密内容。规则贡献应包含正反例及预期分发档位。原评审编号保存在[迭代台账](docs/review-findings.csv)，实现状态与验收状态分开记录。

参考了 [Constitutional AI](https://arxiv.org/abs/2212.08073)、[HarmBench](https://arxiv.org/abs/2402.04249)、[PyRIT](https://github.com/Azure/PyRIT) 和 [TRL](https://github.com/huggingface/trl) 的相关思路。引用不代表具备相同覆盖范围或已经复现其效果。

软件采用 [Apache License 2.0](LICENSE)。输入数据权利与模型服务商条款需另行核对。
