"""Execution provenance shared by storage and pipeline schemas."""

from enum import StrEnum


class ExecutionMode(StrEnum):
    LIVE = "live"
    DEMO = "demo"
    MOCK = "mock"
    UNKNOWN = "unknown"  # Historical records only.
