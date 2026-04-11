<div align="center">

# EcoAlign-Forge

### The DPO Training Data Factory That Never Sleeps

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/dengxianghua888-ops/ecoalign-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/dengxianghua888-ops/ecoalign-forge/actions)
[![Dataset](https://img.shields.io/badge/🤗_Dataset-ecoalign--forge--dpo--zh-yellow)](https://huggingface.co/datasets/dengxianghua888-ops/ecoalign-forge-dpo-zh)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Feed it a safety policy. Get back thousands of high-quality DPO preference pairs.**
**No human annotators. No manual labeling. Just agents arguing with each other.**

[**中文文档**](README_zh.md) | [**Live Report Demo**](docs/demo_report.html)

**Try it now — no API key needed:**
```bash
pip install -e ".[all]" && python -m ecoalign_forge --demo
```

</div>

<details>
<summary><b>See demo output</b> (click to expand)</summary>

```
============================================================
  EcoAlign-Forge  DEMO MODE
  No API key needed — using pre-recorded agent responses
============================================================

16:14:28 INFO  orchestrator: Starting pipeline run — 5 samples in batches of 10
16:14:28 INFO  [ChaosCreator] (DEMO) Generating 5 adversarial cases...
16:14:29 INFO  [Moderator] (DEMO) Reviewing 5 cases as naive junior reviewer...
16:14:30 INFO  [SupremeJudge] (DEMO) Judging 5 cases with guidelines...
16:14:30 INFO  Batch 0 done: 5/5 cases, 3 DPO pairs
16:14:30 INFO  IAA: kappa=0.444, alpha=0.494

============================================================
  Pipeline Complete!
============================================================
  Total cases:       5
  Evaluations:       5
  DPO pairs:         3
  Avg quality:       0.40
  Interception rate: 40.0%
  Output:            data/datasets/dpo_pairs_28eb5d03.jsonl

  Sample DPO pair:
    Chosen:   {"has_stealth_marketing":true, "reasoning_trace":"命中 A-001 + A-002..."}
    Rejected: {"has_stealth_marketing":false, "reasoning_trace":"看起来正常..."}
    Gap:      0.40
    Lineage:  policy=default-v1, judge=openai/gpt-5.4
```

</details>

---

## The Problem

Training a content moderation model requires thousands of **preference pairs** — examples of "good judgment vs. bad judgment" on the same content. Today, this means:

- Hiring annotators at **$0.5–5 per label**
- Waiting **weeks** for a batch of 1,000 pairs
- Getting **inconsistent labels** across annotators
- Having **no idea** why an annotator chose "block" over "pass"

What if you could spin up a **factory** that produces labeled preference data 24/7, with full traceability, for **< $0.01 per pair**?

## The Solution

EcoAlign-Forge runs a **courtroom drama** inside your terminal:

```
  🔴 Red Team (ChaosCreator)        "I crafted this sneaky ad disguised as a review."
       │
       ▼
  🟡 Junior Reviewer (Moderator)    "Hmm, looks fine to me... T2_Normal."
       │
       ▼
  🟢 Supreme Judge                  "Nope. Rule A-002: homophone evasion for WeChat ID.
       │                              This is stealth marketing. T1_Shadowban."
       │
       ▼
  ⚖️  Constitutional Reviewer       "Let me double-check against the handbook...
       │                              Yes, the Judge got it right."
       │
       ▼
  📦 DPO Pair                       chosen = Judge's ruling (with rule citations)
                                     rejected = Moderator's naive guess
                                     preference_gap = 0.7
```

The **disagreement** between Judge and Moderator becomes your training signal. The Judge's rule-cited reasoning becomes `chosen`. The Moderator's gut feeling becomes `rejected`. Rinse and repeat — thousands of times.

---

## Who Is This For?

| You are... | You want to... | EcoAlign-Forge helps by... |
|------------|---------------|---------------------------|
| **ML Engineer** | Train a content moderation model via DPO/RLHF | Generating training data that plugs directly into TRL / LLaMA-Factory |
| **Trust & Safety Lead** | Scale content review without scaling headcount | Producing labeled edge cases your human reviewers would miss |
| **AI Researcher** | Study red-teaming and adversarial robustness | Providing a structured framework for generating + evaluating attacks |
| **Data Scientist** | Build a data quality flywheel | Offering IAA metrics, quality scores, and adaptive sampling out of the box |

---

## See It in Action

### 1. One command to start

```bash
pip install -e ".[all]"
cp .env.example .env          # Add your LLM API key
python -m ecoalign_forge       # Watch the factory run
```

### 2. What you get

```
data/
├── datasets/
│   └── dpo_pairs_a1b2c3d4_20260410_120000.jsonl   # Your DPO training data
├── metrics.json                                     # Quality metrics
├── runs.jsonl                                       # Pipeline run history
├── flywheel_state.json                              # Iteration tracking
└── report.html                                      # Visual quality report
```

### 3. Feed it to your trainer

```python
from ecoalign_forge.export import export_trl

# Option A: Classic TRL format
export_trl(pairs, "train.jsonl")

# Option B: TRL >= 0.8 conversational format
export_trl(pairs, "train.jsonl", conversational=True)

# Option C: LLaMA-Factory ShareGPT format
from ecoalign_forge.export import export_sharegpt
export_sharegpt(pairs, "train_sharegpt.json")
```

### 4. Monitor quality in real-time

```bash
make dashboard    # Opens Streamlit at localhost:8501
```

---

## How It Works

### The Pipeline: 4 Stages + Post-Processing

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AgentOrchestrator.run()                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─ AdaptiveSampler ──────────────────────────────────────────────┐     │
│  │ "ai_slop is undersampled → boost T0/T1 ratio this batch"      │     │
│  └────────────────────────────────────────┬───────────────────────┘     │
│                                           ▼                             │
│  Stage 1  ┌──────────────┐  ChaosCase[]                                │
│           │ ChaosCreator │  "Here are 10 sneaky posts                  │
│           │   (T=0.9)    │   targeting your policy gaps"               │
│           └──────┬───────┘                                              │
│                  ▼                                                       │
│  Stage 2  ┌──────────────┐  JudgeEvaluation[]                          │
│           │  Moderator   │  "I'm a naive reviewer,                     │
│           │   (T=0.5)    │   most of these look fine"                  │
│           │  4 personas  │                                              │
│           └──────┬───────┘                                              │
│                  ▼                                                       │
│  Stage 3  ┌──────────────┐  JudgeEvaluation[] + DPO_Pair[]             │
│           │ SupremeJudge │  "Rule A-002 triggered.                     │
│           │   (T=0.2)    │   T1_Shadowban. Here's why."               │
│           └──────┬───────┘                                              │
│                  ▼                                                       │
│  Stage 4  ┌──────────────┐  Corrected evaluations                      │
│           │Constitutional│  "Double-checked against the handbook.       │
│           │  Reviewer    │   2 out of 10 judgments corrected."          │
│           └──────┬───────┘                                              │
│                  ▼                                                       │
│  Post     DataLineage injection → QualityScorer → IAA → FlyWheel       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### The Secret Sauce: Intentional Disagreement

The Moderator **deliberately doesn't read the rule book**. Each of its 4 personas makes different types of mistakes:

| Persona | Behavior | What it generates |
|---------|----------|-------------------|
| `naive` | Goes with gut feeling | Balanced false positives/negatives |
| `strict_paranoid` | Blocks everything suspicious | Over-moderation training signal |
| `lax_overlooker` | Lets most things through | Under-moderation training signal |
| `keyword_matcher` | Only catches obvious keywords | Evasion-blind training signal |

The Judge, armed with the full guidelines handbook, catches these mistakes. The **gap** between them is your DPO signal.

### Two Types of Training Signal

| Signal Type | When | Strength | Example |
|-------------|------|----------|---------|
| **Direct Disagreement** | Judge and Moderator pick different tiers | Strong (gap = severity difference) | Judge: T0_Block, Moderator: T2_Normal |
| **Reasoning Quality** | Same tier, but Judge cites 2+ rules, Moderator cites 0 | Soft (gap = 0.3) | Both say T1, but Judge explains *why* |

---

## Real-World Scenarios

### Scenario 1: Cold-Start a Content Moderation Model

> "We're launching a new social platform and need a moderation model, but we have zero labeled data."

```python
from ecoalign_forge.engine.orchestrator import AgentOrchestrator
from ecoalign_forge.schemas.policy import PolicyInput, PolicyDimension

policy = PolicyInput(
    policy_id="my-platform-v1",
    name="My Social Platform",
    dimensions=[
        PolicyDimension(name="stealth_marketing", description="Hidden ads and traffic diversion"),
        PolicyDimension(name="ai_slop", description="Low-effort AI-generated content"),
    ],
)

orch = AgentOrchestrator()
result = await orch.run(policy=policy, num_samples=1000)
# → 1000 cases processed, ~400 DPO pairs generated
# → Exported to data/datasets/*.jsonl
```

### Scenario 2: Iterate with the Data Flywheel

> "We trained v1 of our model. How do we make v2 better with targeted data?"

```python
from ecoalign_forge.engine.flywheel import FlyWheelOrchestrator

fw = FlyWheelOrchestrator(convergence_threshold=0.02)

# Round 1: baseline model as Moderator
result_r1 = await orch.run(policy, num_samples=500)
# → avg_quality=0.55, kappa=0.42

# Train your model with Round 1 data...
# Then swap the trained model in as the new Moderator

# Round 2: trained model catches more nuance
result_r2 = await orch.run(policy, num_samples=500)
# → avg_quality=0.72, kappa=0.61

fw.state.quality_improvement  # +30.9% — the flywheel is spinning
```

### Scenario 3: Audit Your Policy Coverage

> "We updated our guidelines. Which rules aren't being triggered by any test cases?"

```python
print(orch.metrics.uncovered_rules)
# → ['A-005', 'B-006']  ← These rules have zero test coverage

coverage = orch.sampler.analyze_coverage(orch._all_cases)
print(coverage.undersampled_combinations)
# → [('ai_slop', 'extreme')]  ← No extreme-difficulty AI slop cases yet
```

### Scenario 4: Generate a Quality Report for Stakeholders

```python
from ecoalign_forge.reports import generate_html_report

generate_html_report(
    dataset_name="Q2 2026 Moderation Training Set",
    total_pairs=len(result.dpo_pairs),
    avg_quality=result.avg_quality_score,
    interception_rate=result.interception_rate,
    quality_distribution=[s.overall for s in quality_reports],
    output_path="q2_report.html",
)
# → Self-contained HTML with KPI cards, charts, and coverage analysis
```

---

## Quality Assurance: Trust but Verify

EcoAlign-Forge doesn't just generate data — it tells you **how good** the data is:

| Metric | What it measures | Where to find it |
|--------|-----------------|------------------|
| **Cohen's Kappa** | Agreement between Judge and each Moderator persona | `compute_batch_iaa()` |
| **Krippendorff's Alpha** | Multi-rater agreement (handles missing values) | `compute_batch_iaa()` |
| **5-Dimension Quality Score** | Reasoning depth, info density, preference clarity, decision consistency, completeness | `QualityScorer.score()` |
| **Constitutional Correction Rate** | How often the self-review catches errors | `constitutional.stats.correction_rate` |
| **Rule Coverage** | Which policy rules have been triggered | `metrics.rule_coverage` |
| **Data Lineage** | Full provenance: which model, persona, policy version, guidelines hash | `DPO_Pair.lineage` |

---

## Taxonomy: Standing on Giants' Shoulders

The attack classification system is not invented from scratch — it aligns with established frameworks:

| Framework | What we borrowed | Where it lives |
|-----------|-----------------|----------------|
| [HarmBench](https://arxiv.org/abs/2402.04249) | 4 functional categories, 7 semantic domains | `taxonomy/harm_categories.py` |
| [OWASP LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/) | Vulnerability-to-category mapping | `HarmCategory.owasp_mapping` |
| [Evol-Instruct](https://arxiv.org/abs/2304.12244) | Depth evolution (add constraints) + Breadth evolution (topic mutation) | `taxonomy/evol_strategies.py` |
| [PyRIT](https://github.com/Azure/PyRIT) | Orchestrator → Converter → Scorer pipeline pattern | `engine/orchestrator.py` |
| [Constitutional AI](https://arxiv.org/abs/2212.08073) | Self-critique → correction loop | `agents/constitutional.py` |

---

## Project Structure

```
ecoalign-forge/
├── src/ecoalign_forge/
│   ├── agents/               # The cast of characters
│   │   ├── chaos_creator.py  #   The attacker (red team)
│   │   ├── moderator.py      #   The naive reviewer (4 personas)
│   │   ├── supreme_judge.py  #   The expert judge (cites rules)
│   │   └── constitutional.py #   The quality auditor (self-review)
│   ├── engine/               # The machinery
│   │   ├── orchestrator.py   #   Runs the full pipeline
│   │   ├── flywheel.py       #   Manages multi-round iteration
│   │   └── adaptive_sampler.py # Adjusts sampling strategy
│   ├── schemas/              # The contracts (Pydantic v2)
│   ├── llm/                  # LLM client (LiteLLM, 100+ providers)
│   ├── storage/              # JSONL storage + metrics + IAA
│   ├── export/               # TRL / ShareGPT / HF Dataset Card
│   ├── quality/              # 5-dimension quality scorer
│   ├── taxonomy/             # HarmBench + OWASP attack taxonomy
│   └── reports/              # Self-contained HTML reports
├── dashboard/                # Streamlit real-time monitoring
├── tests/                    # 199 tests (pytest + asyncio)
├── guidelines.md             # The "constitution" (judgment handbook)
└── examples/                 # Quick-start scripts + policy templates
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **LLM** | LiteLLM | One interface for 100+ providers (OpenAI, Anthropic, local models) |
| **Data Validation** | Pydantic v2 | Rule ID hard-validation prevents LLM hallucinated citations |
| **Async** | asyncio + Tenacity | Concurrent LLM calls with exponential backoff retry |
| **Monitoring** | Streamlit + Plotly | Real-time dashboard with 5-second auto-refresh |
| **Testing** | pytest + asyncio | 199 tests covering all public APIs |
| **CI** | GitHub Actions | Lint (ruff) + test on Python 3.11 & 3.12 |

---

## Development

```bash
make install     # Install dev dependencies
make test        # Run 199 tests with coverage
make lint        # Lint with ruff
make format      # Format with black + isort
make dashboard   # Launch Streamlit dashboard
```

---

## Acknowledgments

Built on ideas from: [TRL](https://github.com/huggingface/trl) | [UltraFeedback](https://github.com/OpenBMB/UltraFeedback) | [PyRIT](https://github.com/Azure/PyRIT) | [HarmBench](https://arxiv.org/abs/2402.04249) | [Constitutional AI](https://arxiv.org/abs/2212.08073) | [Arena Learning](https://arxiv.org/abs/2407.10627) | [Garak](https://github.com/NVIDIA/garak) | [Evol-Instruct](https://arxiv.org/abs/2304.12244)

---

## License

[Apache License 2.0](LICENSE)
