<div align="center">

# EcoAlign-Forge

### 永不停歇的 DPO 训练数据工厂

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/dengxianghua888-ops/ecoalign-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/dengxianghua888-ops/ecoalign-forge/actions)
[![Dataset](https://img.shields.io/badge/🤗_数据集-ecoalign--forge--dpo--zh-yellow)](https://huggingface.co/datasets/dengxianghua888-ops/ecoalign-forge-dpo-zh)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**给它一份安全策略，它还你成千上万条高质量 DPO 偏好对。**
**不需要人工标注。不需要手动打标。只需要几个 Agent 互相"吵架"。**

[**English**](README.md) | [**在线报告 Demo**](docs/demo_report.html)

**立即体验 — 不需要 API Key：**
```bash
pip install -e ".[all]" && python -m ecoalign_forge --demo
```

</div>

<details>
<summary><b>查看 Demo 输出</b>（点击展开）</summary>

```
============================================================
  EcoAlign-Forge  DEMO MODE
  No API key needed — using pre-recorded agent responses
============================================================

16:14:28 INFO  orchestrator: 启动管道 — 5 个样本，批大小 10
16:14:28 INFO  [ChaosCreator] (DEMO) 生成 5 条对抗用例...
16:14:29 INFO  [Moderator] (DEMO) 以萌新审核员身份审核 5 条用例...
16:14:30 INFO  [SupremeJudge] (DEMO) 按 guidelines 判决 5 条用例...
16:14:30 INFO  批次 0 完成: 5/5 用例, 3 个 DPO 对
16:14:30 INFO  IAA: kappa=0.444, alpha=0.494

============================================================
  Pipeline Complete!
============================================================
  总用例数:      5
  评估数量:      5
  DPO 偏好对:    3
  平均质量分:    0.40
  拦截率:       40.0%

  示例 DPO 对:
    Chosen:   {"has_stealth_marketing":true, "reasoning_trace":"命中 A-001 + A-002..."}
    Rejected: {"has_stealth_marketing":false, "reasoning_trace":"看起来正常..."}
    偏好差距:   0.40
    数据血缘:   policy=default-v1, judge=openai/gpt-5.4
```

</details>

---

## 痛点

训练一个内容审核模型需要大量**偏好对数据** — 针对同一条内容，什么是"好的审核判断"，什么是"差的审核判断"。今天的做法是：

- 雇标注员，**每条 ¥3–30**
- 等**几周**才能交付 1000 条标注
- 不同标注员判断**不一致**，质量参差不齐
- 标注员说"违规"但**说不清为什么**，无法追溯

如果有一座**工厂**，能 7×24 小时不间断生产带详细理由的偏好对数据，每条成本 **< ¥0.1**呢？

---

## 解决方案

EcoAlign-Forge 在你的终端里上演一场**法庭大戏**：

```
  🔴 红队攻击手 (ChaosCreator)      "我伪装了一条隐蔽引流帖，看起来像真实种草。"
       │
       ▼
  🟡 初级审核员 (Moderator)          "嗯...看起来挺正常的，T2_Normal 通过。"
       │
       ▼
  🟢 终审法官 (SupremeJudge)         "不对。规则 A-002：谐音字替换微信号。
       │                               这是隐蔽引流，T1_Shadowban 限流。"
       │
       ▼
  ⚖️ 宪法审查员 (Constitutional)     "让我再核对一下手册...
       │                               没错，法官判得对。"
       │
       ▼
  📦 DPO 偏好对                      chosen = 法官的裁决（引用了规则编号）
                                      rejected = 审核员的直觉判断
                                      preference_gap = 0.7
```

法官和审核员的**分歧**就是你的训练信号。法官引用规则的推理成为 `chosen`，审核员凭直觉的猜测成为 `rejected`。如此反复——成千上万次。

---

## 谁会用到它？

| 你是... | 你想要... | EcoAlign-Forge 怎么帮你 |
|---------|----------|----------------------|
| **算法工程师** | 用 DPO/RLHF 训练内容审核模型 | 直接产出 TRL / LLaMA-Factory 可用的训练数据 |
| **安全运营负责人** | 扩大审核覆盖但不增加人力 | 自动挖掘人工审核员容易漏掉的边界用例 |
| **AI 研究员** | 研究红队攻击和对抗鲁棒性 | 提供结构化的攻击生成 + 评估框架 |
| **数据科学家** | 建立数据质量飞轮 | 内置 IAA 指标、质量评分、自适应采样 |

---

## 实际效果

### 1. 一行命令启动

```bash
pip install -e ".[all]"
cp .env.example .env          # 填入你的 LLM API Key
python -m ecoalign_forge       # 看工厂运转
```

### 2. 你会得到什么

```
data/
├── datasets/
│   └── dpo_pairs_a1b2c3d4_20260410_120000.jsonl   # DPO 训练数据
├── metrics.json                                     # 质量指标
├── runs.jsonl                                       # 运行历史
├── flywheel_state.json                              # 飞轮迭代状态
└── report.html                                      # 可视化质量报告
```

### 3. 直接喂给训练框架

```python
from ecoalign_forge.export import export_trl

# 方式 A：经典 TRL 格式
export_trl(pairs, "train.jsonl")

# 方式 B：TRL >= 0.8 对话格式
export_trl(pairs, "train.jsonl", conversational=True)

# 方式 C：LLaMA-Factory ShareGPT 格式
from ecoalign_forge.export import export_sharegpt
export_sharegpt(pairs, "train_sharegpt.json")
```

### 4. 实时监控质量

```bash
make dashboard    # 打开 Streamlit 大屏 localhost:8501
```

---

## 工作原理

### 管道：4 个阶段 + 后处理

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     AgentOrchestrator.run() 全链路                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─ 自适应采样器 ─────────────────────────────────────────────────┐     │
│  │ "ai_slop 维度欠采样 → 本批次提高 T0/T1 比例"                    │     │
│  └────────────────────────────────────┬───────────────────────────┘     │
│                                       ▼                                 │
│  阶段1  ┌──────────────┐  ChaosCase[]                                  │
│         │ ChaosCreator │  "这里有 10 条瞄准你策略漏洞的帖子"            │
│         │   (T=0.9)    │                                                │
│         └──────┬───────┘                                                │
│                ▼                                                         │
│  阶段2  ┌──────────────┐  JudgeEvaluation[]                            │
│         │  Moderator   │  "我是个萌新审核员，                           │
│         │   (T=0.5)    │   大部分看起来挺正常的"                         │
│         │  4 种人格    │                                                │
│         └──────┬───────┘                                                │
│                ▼                                                         │
│  阶段3  ┌──────────────┐  JudgeEvaluation[] + DPO_Pair[]               │
│         │ SupremeJudge │  "规则 A-002 命中。                            │
│         │   (T=0.2)    │   T1_Shadowban，理由如下。"                    │
│         └──────┬───────┘                                                │
│                ▼                                                         │
│  阶段4  ┌──────────────┐  修正后的评估                                  │
│         │  宪法审查员   │  "对照手册复核了一遍，                          │
│         │              │   10 条判决中修正了 2 条。"                     │
│         └──────┬───────┘                                                │
│                ▼                                                         │
│  后处理  数据血缘注入 → 质量评分 → IAA 计算 → 飞轮记录                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 秘密武器：有意制造分歧

Moderator **故意不看规则手册**。它的 4 种人格各自会犯不同类型的错误：

| 人格 | 行为模式 | 产出的训练信号 |
|------|---------|-------------|
| `naive` 中庸型 | 凭直觉判断 | 均衡的误判/漏判信号 |
| `strict_paranoid` 过敏型 | 看什么都可疑 | 过度审核的训练信号 |
| `lax_overlooker` 佛系型 | 大部分都放过 | 审核不足的训练信号 |
| `keyword_matcher` 机器型 | 只抓明显关键词 | 对规避技巧视而不见的信号 |

法官带着完整的判决手册来捉这些错误。他们之间的**差距**就是 DPO 信号。

### 两种训练信号

| 信号类型 | 触发条件 | 信号强度 | 例子 |
|---------|---------|---------|------|
| **直接分歧** | 法官和审核员选了不同档位 | 强（gap = 严厉度差值） | 法官：T0_Block，审核员：T2_Normal |
| **推理质量** | 同一档位，但法官引用了 ≥2 条规则，审核员 0 条 | 弱（gap = 0.3） | 都说 T1，但法官解释了*为什么* |

---

## 真实使用场景

### 场景 1：冷启动内容审核模型

> "我们要上线一个新平台，需要内容审核模型，但一条标注数据都没有。"

```python
from ecoalign_forge.engine.orchestrator import AgentOrchestrator
from ecoalign_forge.schemas.policy import PolicyInput, PolicyDimension

policy = PolicyInput(
    policy_id="my-platform-v1",
    name="我的社交平台",
    dimensions=[
        PolicyDimension(name="stealth_marketing", description="隐蔽引流：微信号、谐音字、暗号"),
        PolicyDimension(name="ai_slop", description="AI 洗稿：套话、语义重复、缺乏原创"),
    ],
)

orch = AgentOrchestrator()
result = await orch.run(policy=policy, num_samples=1000)
# → 处理 1000 条用例，生成约 400 个 DPO 偏好对
# → 自动导出到 data/datasets/*.jsonl
```

### 场景 2：数据飞轮迭代优化

> "模型 v1 训练完了，怎么用定向数据让 v2 更好？"

```python
from ecoalign_forge.engine.flywheel import FlyWheelOrchestrator

fw = FlyWheelOrchestrator(convergence_threshold=0.02)

# 第 1 轮：用基础模型当审核员
result_r1 = await orch.run(policy, num_samples=500)
# → 平均质量分 0.55，Kappa 0.42

# 用第 1 轮数据训练你的模型...
# 然后把训练好的模型换成新的 Moderator

# 第 2 轮：训练后的模型能发现更多细微问题
result_r2 = await orch.run(policy, num_samples=500)
# → 平均质量分 0.72，Kappa 0.61

fw.state.quality_improvement  # +30.9% — 飞轮转起来了
```

### 场景 3：审计策略覆盖率

> "我们更新了审核手册，哪些规则还没被任何测试用例触发？"

```python
print(orch.metrics.uncovered_rules)
# → ['A-005', 'B-006']  ← 这两条规则的测试覆盖率为零

coverage = orch.sampler.analyze_coverage(orch._all_cases)
print(coverage.undersampled_combinations)
# → [('ai_slop', 'extreme')]  ← 极端难度的 AI 洗稿用例还没有
```

### 场景 4：给老板出质量报告

```python
from ecoalign_forge.reports import generate_html_report

generate_html_report(
    dataset_name="2026 年 Q2 审核训练集",
    total_pairs=len(result.dpo_pairs),
    avg_quality=result.avg_quality_score,
    interception_rate=result.interception_rate,
    flywheel_summary=fw.get_summary(),
    output_path="q2_report.html",
)
# → 自包含 HTML，有 KPI 卡片、SVG 图表、覆盖率分析
```

---

## 质量保障：数据不是越多越好，而是越可靠越好

EcoAlign-Forge 不只是生成数据 — 它告诉你数据**有多可靠**：

| 指标 | 衡量什么 | 在哪里找 |
|------|---------|---------|
| **Cohen's Kappa** | 法官和每个审核员人格之间的一致性 | `compute_batch_iaa()` |
| **Krippendorff's Alpha** | 多评审者一致性（支持缺失值） | `compute_batch_iaa()` |
| **5 维质量评分** | 推理深度、信息密度、偏好清晰度、决策一致性、响应完整性 | `QualityScorer.score()` |
| **宪法修正率** | 自我审查发现了多少错误 | `constitutional.stats.correction_rate` |
| **规则覆盖率** | 哪些策略规则被触发过 | `metrics.rule_coverage` |
| **数据血缘** | 完整溯源：哪个模型、什么人格、策略版本、手册哈希 | `DPO_Pair.lineage` |

---

## 攻击分类：站在巨人的肩膀上

攻击分类体系不是凭空发明的 — 它对齐了业界标准：

| 框架 | 借鉴了什么 | 在哪里 |
|------|----------|--------|
| [HarmBench](https://arxiv.org/abs/2402.04249) | 4 个功能分类 + 7 个语义域 | `taxonomy/harm_categories.py` |
| [OWASP LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/) | 漏洞到分类的映射 | `HarmCategory.owasp_mapping` |
| [Evol-Instruct](https://arxiv.org/abs/2304.12244) | 深度进化（加约束）+ 广度进化（主题变异） | `taxonomy/evol_strategies.py` |
| [PyRIT](https://github.com/Azure/PyRIT) | 编排器 → 转换器 → 评分器管道模式 | `engine/orchestrator.py` |
| [Constitutional AI](https://arxiv.org/abs/2212.08073) | 自我批评 → 修正循环 | `agents/constitutional.py` |

---

## 判决依据手册 (guidelines.md)

这份手册就是整个系统的"宪法"——所有判决都必须能追溯到具体条款：

| 策略 | 规则数 | 阈值 | 判定 |
|------|--------|------|------|
| **A: 高隐蔽性私域引流** | A-001 ~ A-006 | 任一命中 | `has_stealth_marketing = true` |
| **B: 低信息熵 AI 洗稿** | B-001 ~ B-006（分值制） | 累计 ≥3 分 | `is_ai_slop = true` |

**分级矩阵：**

| 引流？ | 洗稿？ | 判决 | 含义 |
|:-----:|:-----:|:-----|:-----|
| ✅ | ✅ | **T0_Block** | 双重灰黑产，直接封禁 |
| ✅ | ❌ | **T1_Shadowban** | 仅引流，限流处理 |
| ❌ | ✅ | **T2_Normal** | 仅洗稿，正常分发 |
| ❌ | ❌ | **T2/T3** | 看内容信息质量 |

---

## 项目结构

```
ecoalign-forge/
├── src/ecoalign_forge/
│   ├── agents/               # 演员表
│   │   ├── chaos_creator.py  #   攻击手（红队）
│   │   ├── moderator.py      #   萌新审核员（4 种人格）
│   │   ├── supreme_judge.py  #   终审法官（引用规则）
│   │   └── constitutional.py #   质量审计员（自我审查）
│   ├── engine/               # 引擎
│   │   ├── orchestrator.py   #   全流程编排器
│   │   ├── flywheel.py       #   数据飞轮（多轮迭代）
│   │   └── adaptive_sampler.py # 自适应采样器
│   ├── schemas/              # 数据契约（Pydantic v2）
│   ├── llm/                  # LLM 客户端（LiteLLM, 100+ 供应商）
│   ├── storage/              # JSONL 存储 + 指标 + IAA
│   ├── export/               # TRL / ShareGPT / HF Dataset Card
│   ├── quality/              # 5 维质量评分器
│   ├── taxonomy/             # HarmBench + OWASP 攻击分类
│   └── reports/              # 自包含 HTML 报告
├── dashboard/                # Streamlit 实时监控大屏
├── tests/                    # 199 项测试（pytest + asyncio）
├── guidelines.md             # "宪法"（判决依据手册）
└── examples/                 # 快速开始脚本 + 策略模板
```

---

## 技术栈

| 层级 | 技术 | 为什么用它 |
|------|------|----------|
| **LLM** | LiteLLM | 一个接口对接 100+ 供应商（OpenAI、Anthropic、本地模型） |
| **数据校验** | Pydantic v2 | 规则编号硬校验防止 LLM 幻觉引用 |
| **异步** | asyncio + Tenacity | 并发 LLM 调用 + 指数退避重试 |
| **监控** | Streamlit + Plotly | 实时大屏，5 秒自动刷新 |
| **测试** | pytest + asyncio | 199 项测试覆盖所有公开 API |
| **CI** | GitHub Actions | ruff 检查 + Python 3.11/3.12 双版本测试 |

---

## 开发

```bash
make install     # 安装开发依赖
make test        # 运行 199 项测试（含覆盖率）
make lint        # ruff 代码检查
make format      # black + isort 格式化
make dashboard   # 启动 Streamlit 大屏
```

---

## 致谢

本项目的设计站在这些巨人的肩膀上：[TRL](https://github.com/huggingface/trl) | [UltraFeedback](https://github.com/OpenBMB/UltraFeedback) | [PyRIT](https://github.com/Azure/PyRIT) | [HarmBench](https://arxiv.org/abs/2402.04249) | [Constitutional AI](https://arxiv.org/abs/2212.08073) | [Arena Learning](https://arxiv.org/abs/2407.10627) | [Garak](https://github.com/NVIDIA/garak) | [Evol-Instruct](https://arxiv.org/abs/2304.12244)

---

## 协议

[Apache License 2.0](LICENSE)
