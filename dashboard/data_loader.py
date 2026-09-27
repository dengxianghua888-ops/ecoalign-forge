"""Read only the explicitly selected persisted source; never synthesize fallback data."""

import streamlit as st

from ecoalign_forge.schemas.execution import ExecutionMode
from ecoalign_forge.storage.dashboard_bridge import DashboardBridge, DashboardSnapshot


@st.cache_data(ttl=5)
def load_snapshot(execution_mode: str = "live") -> DashboardSnapshot:
    mode = ExecutionMode(execution_mode)
    try:
        return DashboardBridge(execution_mode=mode).get_latest_snapshot()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return DashboardSnapshot(execution_mode=mode, load_error=f"读取失败：{exc}")
