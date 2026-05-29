"""Core data models for the benchmark framework.

Domain-agnostic types used by all domains: task definitions, trajectories,
scoring structures, and state diffs. Domain-specific record types (Flight,
Booking, etc.) live in their respective domain-specific schemas modules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Mixin for standard dataclass serialization
# ---------------------------------------------------------------------------


class DictMixin:
    """Mixin providing standard to_dict/from_dict for flat dataclasses.

    Classes with nested dataclass fields (e.g. EnvironmentData) should
    override these methods to handle recursive serialization.
    """

    def to_dict(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]):  # noqa: ANN206
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# State diff — structured before/after comparison for LLM judge
# ---------------------------------------------------------------------------


@dataclass
class StateDiff:
    """Structured diff between before and after environment snapshots.

    Provided to the LLM judge as evidence of what the agent actually did.
    """

    created: dict[str, dict[str, Any]] = field(default_factory=dict)  # entity_type -> {id: full record}
    modified: dict[str, dict[str, Any]] = field(default_factory=dict)  # entity_type -> {id: {field: {old, new}}}
    deleted: dict[str, dict[str, Any]] = field(default_factory=dict)  # entity_type -> {id: record before deletion}

    def to_dict(self) -> dict[str, Any]:
        return {"created": self.created, "modified": self.modified, "deleted": self.deleted}

    def is_empty(self) -> bool:
        return not self.created and not self.modified and not self.deleted

    @classmethod
    def compute(cls, before: dict, after: dict) -> StateDiff:
        """Compare before/after snapshots and return a structured StateDiff."""
        diff = cls()
        all_entity_types = set(before) | set(after)
        for entity_type in all_entity_types:
            before_entities = before.get(entity_type, {})
            after_entities = after.get(entity_type, {})

            # Deleted: in before but not in after
            for eid, record in before_entities.items():
                if eid not in after_entities:
                    diff.deleted.setdefault(entity_type, {})[eid] = record

            # Created or modified
            for eid, record in after_entities.items():
                if eid not in before_entities:
                    diff.created.setdefault(entity_type, {})[eid] = record
                else:
                    old_record = before_entities[eid]
                    changes = {}
                    for k in set(list(old_record.keys()) + list(record.keys())):
                        old_val = old_record.get(k)
                        new_val = record.get(k)
                        if old_val != new_val:
                            changes[k] = {"old": old_val, "new": new_val}
                    if changes:
                        diff.modified.setdefault(entity_type, {})[eid] = changes

        return diff


# ---------------------------------------------------------------------------
# Task definition (loaded from JSON)
# ---------------------------------------------------------------------------


@dataclass
class UserSimulatorConfig:
    """Configuration for the user simulator in a task."""

    personality: str  # Tone and information-sharing style
    user_sim_context: str
    known_info: list[str] = field(default_factory=list)  # Facts the user knows
    unknown_info: list[str] = field(default_factory=list)  # Things the user doesn't know
    task_rules: list[str] = field(default_factory=list)  # Task-specific IF/THEN rules

    def __post_init__(self) -> None:
        if not self.user_sim_context or not self.user_sim_context.strip():
            raise ValueError("user_simulator.user_sim_context is required and must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "personality": self.personality,
            "user_sim_context": self.user_sim_context,
            "known_info": self.known_info,
            "unknown_info": self.unknown_info,
            "task_rules": self.task_rules,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserSimulatorConfig:
        if "user_sim_context" not in data:
            raise ValueError("user_simulator.user_sim_context is required")
        return cls(
            personality=data["personality"],
            user_sim_context=data["user_sim_context"],
            known_info=data.get("known_info", []),
            unknown_info=data.get("unknown_info", []),
            task_rules=data.get("task_rules", []),
        )


@dataclass
class TaskDefinition:
    """A benchmark task definition loaded from JSON."""

    task_id: str
    task_summary: str

    user_id: str
    opening_message: str
    user_simulator: UserSimulatorConfig

    task_type: str | None = None

    # Supports two requirement shapes:
    # 1. direct field assertion: {entity_type, record_key, field, expected_value}
    # 2. created-record matcher: {entity_type, match_fields, expected_fields}
    state_requirements: list[dict[str, Any]] = field(default_factory=list)
    task_env_path: str | None = None
    task_requirements: list[dict[str, Any]] = field(default_factory=list)
    now: str = "2026-06-15T10:00:00"

    def __post_init__(self) -> None:
        if not self.task_summary or not self.task_summary.strip():
            raise ValueError("task_summary is required and must be non-empty")
        if self.state_requirements is None:
            self.state_requirements = []
        if self.task_requirements is None:
            self.task_requirements = []

    def to_dict(self) -> dict[str, Any]:
        d = {
            "task_id": self.task_id,
            "task_summary": self.task_summary,
            "task_requirements": self.task_requirements,
            "user_id": self.user_id,
            "now": self.now,
            "opening_message": self.opening_message,
            "user_simulator": self.user_simulator.to_dict(),
        }
        if self.task_type is not None:
            d["task_type"] = self.task_type
        d["state_requirements"] = self.state_requirements
        if self.task_env_path is not None:
            d["task_env_path"] = self.task_env_path
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskDefinition:
        if "task_info" in data:
            raise ValueError("task_info is no longer supported; use task_summary and user_simulator.user_sim_context")
        if "task_summary" not in data:
            raise ValueError("task_summary is required")
        # Fail fast on duplicate task_requirements[].id. The task-judge gate uses
        # set(required_ids) to compute pass/fail; collisions silently make the task
        # unpassable because len(details) can never equal the de-duplicated set size.
        task_requirements = data.get("task_requirements", []) or []
        seen_ids: set[str] = set()
        for req in task_requirements:
            rid = req.get("id") if isinstance(req, dict) else None
            if rid is None:
                continue
            rid_str = str(rid)
            if rid_str in seen_ids:
                raise ValueError(
                    f"Task {data.get('task_id', '?')} has duplicate task_requirement id "
                    f"{rid_str!r}. Each requirement id must be unique within a task."
                )
            seen_ids.add(rid_str)
        return cls(
            task_id=data["task_id"],
            task_summary=data["task_summary"],
            task_type=data.get("task_type"),
            state_requirements=data.get("state_requirements", []),
            task_env_path=data.get("task_env_path"),
            task_requirements=task_requirements,
            user_id=data["user_id"],
            now=data.get("now", "2026-06-15T10:00:00"),
            opening_message=data["opening_message"],
            user_simulator=UserSimulatorConfig.from_dict(data["user_simulator"]),
        )

    @classmethod
    def load(cls, path: Path) -> TaskDefinition:
        with open(path) as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# Trajectory — output of a single task run
# ---------------------------------------------------------------------------


@dataclass
class EfficiencyMetrics:
    """Deterministic efficiency metrics computed from trajectory data."""

    turns: int
    tool_calls: int
    tool_errors: int
    redundant_calls: int  # duplicate tool calls with identical parameters

    def to_dict(self) -> dict[str, Any]:
        return {
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "redundant_calls": self.redundant_calls,
        }


@dataclass
class TokenUsage:
    """Agent-side non-judge cost ledger aggregated across one trajectory."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    input_cost_usd: float = 0.0
    cached_input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    agent_turn_cost_usd: float = 0.0
    memory_ingestion_cost_usd: float = 0.0
    memory_retrieval_cost_usd: float = 0.0
    other_llm_cost_usd: float = 0.0
    total_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost_usd": self.input_cost_usd,
            "cached_input_cost_usd": self.cached_input_cost_usd,
            "output_cost_usd": self.output_cost_usd,
            "agent_turn_cost_usd": self.agent_turn_cost_usd,
            "memory_ingestion_cost_usd": self.memory_ingestion_cost_usd,
            "memory_retrieval_cost_usd": self.memory_retrieval_cost_usd,
            "other_llm_cost_usd": self.other_llm_cost_usd,
            "total_cost_usd": self.total_cost_usd,
        }


@dataclass
class BinaryScore:
    """Binary score for deterministic component evaluation."""

    score: int  # 0 or 1
    reasoning: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"score": self.score, "reasoning": self.reasoning}
        if self.details is not None:
            result["details"] = self.details
        return result


@dataclass
class TaskRequirementsScore:
    """Binary score derived from per-requirement details for non-state task checks."""

    score: int  # 0 or 1
    details: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "details": self.details, "reasoning": self.reasoning}


@dataclass
class UXQualityResult:
    """Result from the UX quality judge."""

    user_control: int
    friction: int
    situational_awareness: int
    communication_quality: int
    intent_alignment: int
    reasoning: str
    score: float | None = None

    @property
    def ux_score(self) -> float:
        if self.score is not None:
            return self.score
        return (
            self.user_control
            + self.friction
            + self.situational_awareness
            + self.communication_quality
            + self.intent_alignment
        ) / 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "ux_user_control": self.user_control,
            "ux_friction": self.friction,
            "ux_situational_awareness": self.situational_awareness,
            "ux_communication_quality": self.communication_quality,
            "ux_intent_alignment": self.intent_alignment,
            "ux_score": round(self.ux_score, 2),
            "ux_reasoning": self.reasoning,
        }


@dataclass
class Trajectory:
    """Full output of a single task run."""

    task_id: str
    user_id: str
    task_summary: str

    # Conversation and tool calls
    conversation: list[dict[str, Any]]

    # State diff (before/after DB snapshot)
    state_diff: StateDiff | None = None

    # Scores
    state_requirements_score: BinaryScore | None = None
    task_requirements_score: TaskRequirementsScore | None = None
    task_completion_pass: int | None = None
    ux_quality: UXQualityResult | None = None
    efficiency: EfficiencyMetrics | None = None
    token_usage: TokenUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "task_summary": self.task_summary,
            "state_requirements_met": self.state_requirements_score.score if self.state_requirements_score else None,
            "state_requirements_reasoning": self.state_requirements_score.reasoning
            if self.state_requirements_score
            else None,
            "state_requirements_details": self.state_requirements_score.details
            if self.state_requirements_score
            else None,
            "task_requirements_met": self.task_requirements_score.score if self.task_requirements_score else None,
            "task_requirements_reasoning": self.task_requirements_score.reasoning
            if self.task_requirements_score
            else None,
            "task_requirements_details": self.task_requirements_score.details if self.task_requirements_score else None,
            "task_completion_pass": self.task_completion_pass,
            "ux_user_control": self.ux_quality.user_control if self.ux_quality else None,
            "ux_friction": self.ux_quality.friction if self.ux_quality else None,
            "ux_situational_awareness": self.ux_quality.situational_awareness if self.ux_quality else None,
            "ux_communication_quality": self.ux_quality.communication_quality if self.ux_quality else None,
            "ux_intent_alignment": self.ux_quality.intent_alignment if self.ux_quality else None,
            "ux_score": round(self.ux_quality.ux_score, 2) if self.ux_quality else None,
            "ux_reasoning": self.ux_quality.reasoning if self.ux_quality else None,
            "turns": self.efficiency.turns if self.efficiency else 0,
            "tool_calls": self.efficiency.tool_calls if self.efficiency else 0,
            "tool_errors": self.efficiency.tool_errors if self.efficiency else 0,
            "redundant_calls": self.efficiency.redundant_calls if self.efficiency else 0,
            "conversation": self.conversation,
        }
        result.update(self.metadata)
        if self.token_usage:
            result["token_usage"] = self.token_usage.to_dict()
            result["input_tokens"] = self.token_usage.input_tokens
            result["cached_input_tokens"] = self.token_usage.cached_input_tokens
            result["output_tokens"] = self.token_usage.output_tokens
            result["reasoning_output_tokens"] = self.token_usage.reasoning_output_tokens
            result["total_tokens"] = self.token_usage.total_tokens
            result["cost_usd"] = self.token_usage.total_cost_usd
        if self.state_diff:
            result["state_diff"] = self.state_diff.to_dict()
        if self.error:
            result["error"] = self.error
        return result

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
