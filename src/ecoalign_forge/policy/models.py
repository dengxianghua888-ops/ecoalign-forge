"""Finite declarative language for policy packages."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ecoalign_forge.schemas.kernel import Contract


class Condition(Contract):
    op: Literal["rule", "label", "score", "all", "any", "not"]
    ref: str | None = None
    value: str | int | None = None
    compare: Literal["eq", "ge", "gt", "le", "lt"] = "eq"
    children: tuple[Condition, ...] = ()

    @model_validator(mode="after")
    def shape(self):
        composite = self.op in {"all", "any", "not"}
        if composite:
            if not self.children or self.ref is not None or self.value is not None:
                raise ValueError("Composite conditions require only children")
            if self.op == "not" and len(self.children) != 1:
                raise ValueError("not requires one child")
        else:
            if not self.ref or self.children:
                raise ValueError("Leaf conditions require ref and no children")
            if self.op == "rule" and self.value is not None:
                raise ValueError("rule conditions test hit and take no value")
            if self.op == "label" and not isinstance(self.value, str):
                raise ValueError("label conditions require a string value")
            if self.op == "score" and type(self.value) is not int:
                raise ValueError("score conditions require an integer value")
            if self.op != "score" and self.compare != "eq":
                raise ValueError("Only score supports ordered comparison")
        return self


class LabelRow(Contract):
    label: str
    when: Condition


class Dimension(Contract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    labels: tuple[str, ...] = Field(min_length=1)
    rows: tuple[LabelRow, ...] = ()
    default: str


class Rule(Contract):
    id: str = Field(min_length=1)
    dimension: str
    text: str = Field(min_length=1)
    points: int = Field(default=0, ge=0)
    evidence: Literal["text_span", "document_scope", "external"] = "text_span"


class ExceptionRule(Contract):
    id: str
    when: Condition
    suppress: tuple[str, ...] = Field(min_length=1)


class DecisionRow(Contract):
    id: str
    action: str
    when: Condition | None = None


class PolicyPack(Contract):
    schema_version: Literal[1] = 1
    policy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    language: str = Field(min_length=1, pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    context: str = ""
    dimensions: tuple[Dimension, ...] = Field(min_length=1)
    actions: tuple[str, ...] = Field(min_length=1)
    rules: tuple[Rule, ...] = Field(min_length=1)
    exceptions: tuple[ExceptionRule, ...] = ()
    decisions: tuple[DecisionRow, ...] = Field(min_length=1)
    severity: dict[str, float] | None = None
    data_license: str | None = None
