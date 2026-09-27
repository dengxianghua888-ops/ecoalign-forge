"""Read-only inspection of committed portable runs."""

import pandas as pd
import streamlit as st

from dashboard.data_loader import list_runs, read_run


def render_kernel(mode):
    st.title("EcoAlign-Forge")
    st.caption("规则驱动的合成运行 · 连接状态：未检测 · 模型质量与训练收益：未评估")
    runs = list_runs(mode)
    if not runs:
        st.info(f"{mode} 暂无新内核运行记录。")
        return
    selected = st.sidebar.selectbox("运行记录", runs, format_func=lambda p: p.parent.name)
    try:
        run = read_run(selected)
    except Exception as exc:
        st.error(f"读取运行失败：{type(exc).__name__}。没有替换为演示数据。")
        return
    st.caption(f"{run['execution_mode']} · {run['language']} · {run['run_id']}")
    st.code(run["policy_hash"], language=None)
    st.subheader(f"状态：{run['status']}")
    if run["pause_reason"]:
        st.warning(f"暂停原因：{run['pause_reason']}")
    if run["error"]:
        st.error(run["error"])
    if run["unknown_attempts"]:
        st.write("未决请求：", run["unknown_attempts"])
    counts = run["counts"]
    columns = st.columns(4)
    for col, key, label in zip(
        columns,
        ["completed", "accepted_cases", "excluded_cases", "dpo_pairs"],
        ["已完成", "门槛接受", "语义排除", "DPO 对"],
        strict=True,
    ):
        col.metric(label, counts[key])
    labels, actions, status = st.tabs(["维度标签", "最终动作", "计数与诊断"])
    with labels:
        dimension = st.selectbox("维度", list(run["label_distribution"]))
        values = run["label_distribution"][dimension]
        st.bar_chart(
            pd.DataFrame({"标签": values.keys(), "数量": values.values()}).set_index("标签")
        )
    with actions:
        values = run["action_distribution"]
        st.bar_chart(
            pd.DataFrame({"动作": values.keys(), "数量": values.values()}).set_index("动作")
        )
    with status:
        st.json(counts)
        st.dataframe(run["cases"], hide_index=True, width="stretch")
    st.subheader("费用与未决预留（USD）")
    st.json(run["budget"])
    st.caption(
        "价格表估算与供应商 usage 分开展示；没有账单时实际金额保持未知。共享配额仅协调本工具的参与进程。"
    )
    st.subheader("复核状态")
    st.json(run["review_stats"])
    st.caption("接受仅表示结构、引用和规则内部一致，不是人工金标。历史数据保持只读。")
