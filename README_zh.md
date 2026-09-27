# EcoAlign-Forge

可恢复的规则驱动合成内核，用于生成带证据与血缘的机器偏好数据。

[English](README.md) · [迁移与接口](docs/iteration-b-migration.md) · [验收记录](docs/iteration-b-acceptance.md) · [原任务 F01–F14](docs/review-findings.csv)

**0.3.0a1 Alpha。** 支持声明式 PolicyPack、自定义语言与标签、原文复核、证据和规则一致性门槛、SQLite 检查点、共享限流及费用账本。门槛通过不代表人工金标，真实模型准确率、跨语言效果及训练收益仍未验证。

## 无密钥演示

Python 3.11/3.12，macOS/Linux，在仓库根目录运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m ecoalign_forge run --demo --num-samples 5
python examples/quickstart.py
```

5 条预录案例完成，产生 3 对 DPO，无外部模型调用。兼容 `--demo --num-samples 5`，默认模式现在为 demo。wheel 可从 GitHub Alpha 附件下载并安装；本轮不发布 PyPI。

## 新流程

规则快照 → 持久化采样计划 → 生成 → 弱候选审核 → Judge 候选 → 原文复核 → 最终门槛 → 偏好对 → 不可变导出。

内置中文 A/B 是第一个规则包；[英文规则示例](examples/contact_policy.en.json)使用独立标签。语言结构和流程开放，不表示所有语言效果已验证。规则包只支持固定操作，不运行代码。证据使用原文 SHA-256、来源 ID、Unicode 字符偏移和精确引用。

```bash
python -m ecoalign_forge inspect data/demo/runs/RUN_ID
python -m ecoalign_forge resume data/demo/runs/RUN_ID
python -m ecoalign_forge export data/demo/runs/RUN_ID
```

每轮保存在 `DATA_DIR/<mode>/runs/<run_id>/run.sqlite3`。完整响应已经保存时先本地重放；远端处理情况未知时默认暂停。只有明确指定 `--resolve 'ATTEMPT_ID=retry'` 或 `=skip` 才处理未知请求，旧费用预留仍保留。恢复只允许提高预算和延长期限，不能更换规则、模型、提示词或代码。

计数恒等式：`completed + failed + unattempted + in_progress = requested`；`accepted_cases + excluded_cases = completed`。正常排除的候选不会进入 chosen，复核失败或弃权计为失败。退出码 0 完成、1 失败、2 参数错误、3 部分失败、4 暂停、130 取消。

## 实时调用与费用

必须显式选择 live，并在配置文件提供金额上限和所有模型的价格快照：

```bash
python -m ecoalign_forge run --mode live --config /path/to/verified-live-config.json --policy examples/contact_policy.en.json
```

密钥仅放在供应商环境变量中。配置优先级为显式参数、配置文件、`ECOALIGN_*` 环境、内置默认值。默认并发 5、每请求总尝试 3 次、请求 120 秒、流空闲 30 秒、运行 3600 秒。请求前预留金额，返回后按 usage 与冻结价格估算；无 usage 继续占用预留，不伪造实际账单。共享限流只约束本工具参与进程。

## 导出与监控

每个不可变数据集版本含原始 pair、TRL 两种格式、ShareGPT、规则快照、数据卡和文件哈希。数据许可未声明时为“未指定”，不继承代码 Apache-2.0。TRL 1.14.0 与 LLaMA-Factory 0.9.5 使用独立锁定环境，验收覆盖真实加载、模板、tokenize 和 collator，不训练。

```bash
python -m pip install -e '.[dashboard]'
python -m streamlit run dashboard/app.py --server.port 8501
```

选择实际模式和 run，再切换维度标签、最终动作或计数诊断。暂停原因、未知请求和预算单独显示；旧 A/unknown 数据只读，坏文件和空数据不回退随机演示。无严重度映射时指标为 null；不展示未经验证的模型质量提升。

详细接口、兼容影响和旧断言调整见[迁移说明](docs/iteration-b-migration.md)。F12–F14 继续追踪工作台、新用户验收、真实模型与训练效果。旧 Alpha 的证据保留原版本绑定，不冒充本轮验收。
