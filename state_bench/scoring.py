"""Scoring utilities for task trajectories.

Domain-agnostic scoring helpers:
1. Task requirements — LLM-evaluated non-state requirements
2. State requirements — deterministic final-state verification
3. UX quality — LLM-evaluated interaction quality
4. Efficiency — deterministic metrics (turns, tool_calls, tool_errors, redundant_calls)
"""

import json
import logging
from collections import Counter
from copy import deepcopy
from pathlib import Path
from string import Template
from typing import Any

from state_bench.env_loader import resolve_task_env_path
from state_bench.schemas import (
    BinaryScore,
    EfficiencyMetrics,
    StateDiff,
    TaskDefinition,
    TaskRequirementsScore,
    UXQualityResult,
)

logger = logging.getLogger(__name__)


def combine_task_completion(
    state_requirements_score: BinaryScore | None,
    task_requirements_score: TaskRequirementsScore | None,
) -> int | None:
    """Combine state and task requirement surfaces into a single task completion bit."""
    if task_requirements_score is None or state_requirements_score is None:
        return None
    return int(state_requirements_score.score == 1 and task_requirements_score.score == 1)


def build_task_requirements_prompt(
    task: TaskDefinition,
    conversation: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    prompts_dir: Path,
    judge_prompt: str = "judge_task_requirements.md",
) -> str:
    """Build the prompt for the non-state task requirements judge."""
    conversation_text = _format_conversation(conversation, tool_calls)
    requirements = task.task_requirements or []
    requirements_text = json.dumps(requirements, indent=2, ensure_ascii=False)

    task_summary_text = task.task_summary

    template = Template((prompts_dir / judge_prompt).read_text())
    return template.substitute(
        task_summary=task_summary_text,
        task_requirements=requirements_text,
        conversation=conversation_text,
    )


def build_ux_prompt(
    task: TaskDefinition,
    conversation: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    prompts_dir: Path,
    judge_prompt: str = "judge_ux_quality_user.md",
) -> str:
    """Build the user-message prompt for the UX quality judge."""
    conversation_text = _format_conversation(conversation, tool_calls)
    template = Template((prompts_dir / judge_prompt).read_text())
    return template.substitute(
        conversation=conversation_text,
        task_summary=task.task_summary,
    )


# ---------------------------------------------------------------------------
# 2. Deterministic State Requirements
# ---------------------------------------------------------------------------


def evaluate_state_requirements(task: TaskDefinition, state_diff: StateDiff) -> BinaryScore | None:
    """Evaluate structured state requirements against reconstructed final state plus saved StateDiff."""
    requirements = task.state_requirements
    if not requirements:
        if state_diff.is_empty():
            return BinaryScore(
                score=1, reasoning="Task defines no required state changes and the saved state_diff is empty."
            )
        return BinaryScore(
            score=0, reasoning="Task defines no required state changes but the saved state_diff is not empty."
        )

    final_snapshot = _reconstruct_final_snapshot(task, state_diff)
    expected_assertions, unresolved_requirements = _normalize_state_requirements(requirements, final_snapshot)
    observed_assertions = _normalize_snapshot_assertions(final_snapshot, requirements)
    strict_expected_assertions = _normalize_strict_state_requirements(requirements)
    strict_observed_assertions = _normalize_strict_state_diff(state_diff, _strict_created_record_keys(requirements))
    strict_observed_assertions = _ignore_semantically_covered_cart_item_ids(
        strict_observed_assertions,
        requirements,
        final_snapshot,
    )

    missing = expected_assertions - observed_assertions
    unexpected = strict_observed_assertions - strict_expected_assertions

    details: dict[str, Any] = {}
    failures: list[str] = []
    if unresolved_requirements:
        details["unresolved_match_requirements"] = unresolved_requirements
        failures.append(f"unresolved_match_requirements={len(unresolved_requirements)}")
    if missing:
        details["missing_assertions"] = [_assertion_to_detail(item) for item in sorted(missing)]
        failures.append(f"missing_assertions={len(missing)}")
    if unexpected:
        details["unexpected_assertions"] = [_assertion_to_detail(item) for item in sorted(unexpected)]
        failures.append(f"unexpected_assertions={len(unexpected)}")

    if failures:
        return BinaryScore(score=0, reasoning="State requirements failed: " + "; ".join(failures), details=details)
    return BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")


def _assertion_to_detail(assertion: tuple[str, str, str, str]) -> dict[str, Any]:
    entity_type, record_key, field, value = assertion
    try:
        decoded_value = json.loads(value)
    except json.JSONDecodeError:
        decoded_value = value
    return {
        "entity_type": entity_type,
        "record_key": record_key,
        "field": field,
        "value": decoded_value,
    }


def _normalize_state_requirements(
    requirements: list[dict[str, Any]],
    final_snapshot: dict[str, dict[str, dict[str, Any]]],
) -> tuple[set[tuple[str, str, str, str]], list[dict[str, Any]]]:
    assertions: set[tuple[str, str, str, str]] = set()
    unresolved: list[dict[str, Any]] = []
    for req in requirements:
        entity_type = req.get("entity_type")
        if not entity_type:
            unresolved.append({"requirement": deepcopy(req), "error": "missing entity_type"})
            continue

        record_key = req.get("record_key")
        field = req.get("field")
        match_fields = req.get("match_fields")
        expected_fields = req.get("expected_fields")

        if record_key is not None or field is not None:
            if not record_key or not field:
                unresolved.append({"requirement": deepcopy(req), "error": "record_key and field are required together"})
                continue
            assertions.add((entity_type, record_key, field, _canonicalize_value(req.get("expected_value"))))
            continue

        if match_fields is not None or expected_fields is not None:
            if not isinstance(match_fields, dict) or not match_fields:
                unresolved.append({"requirement": deepcopy(req), "error": "match_fields must be a non-empty object"})
                continue
            if expected_fields is None:
                expected_fields = {}
            if not isinstance(expected_fields, dict):
                unresolved.append({"requirement": deepcopy(req), "error": "expected_fields must be an object"})
                continue

            matches = _find_matching_records(entity_type, match_fields, final_snapshot)
            if len(matches) != 1:
                unresolved.append(
                    {
                        "requirement": deepcopy(req),
                        "error": "match_fields resolved to zero or multiple records",
                        "match_count": len(matches),
                        "matched_record_keys": sorted(matches),
                    }
                )
                continue

            matched_key = matches[0]
            for match_field, match_value in match_fields.items():
                assertions.add((entity_type, matched_key, match_field, _canonicalize_value(match_value)))
            for expected_field, expected_value in expected_fields.items():
                assertions.add((entity_type, matched_key, expected_field, _canonicalize_value(expected_value)))
            continue

        unresolved.append({"requirement": deepcopy(req), "error": "unsupported state requirement shape"})
    return assertions, unresolved


def _lookup_snapshot_record(
    final_snapshot: dict[str, dict[str, dict[str, Any]]],
    entity_type: str,
    record_key: str,
) -> dict[str, Any] | None:
    return _as_record_mapping(final_snapshot.get(entity_type, {})).get(str(record_key))


def _record_identity(record: dict[str, Any], fallback_index: int | None = None) -> str | None:
    for key in (
        "cart_item_id",
        "cart_id",
        "customer_id",
        "order_id",
        "item_id",
        "booking_id",
        "reservation_id",
        "rental_id",
        "id",
        "product_id",
    ):
        value = record.get(key)
        if value is not None:
            return str(value)
    if fallback_index is not None:
        return str(fallback_index)
    return None


def _as_record_mapping(records: Any) -> dict[str, dict[str, Any]]:
    if isinstance(records, dict):
        return {str(key): value for key, value in records.items() if isinstance(value, dict)}
    if isinstance(records, list):
        mapping: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            record_key = _record_identity(record, fallback_index=index)
            if record_key is None:
                continue
            mapping[record_key] = record
        return mapping
    return {}


def _normalize_snapshot_structure(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for entity_type, records in snapshot.items():
        if isinstance(records, (dict, list)):
            normalized[entity_type] = _as_record_mapping(records)
        else:
            normalized[entity_type] = records
    return normalized


def _find_matching_records(
    entity_type: str,
    match_fields: dict[str, Any],
    final_snapshot: dict[str, dict[str, dict[str, Any]]],
) -> list[str]:
    matches: list[str] = []
    items = _as_record_mapping(final_snapshot.get(entity_type, {})).items()
    for record_key, record in items:
        if all(record.get(field) == expected_value for field, expected_value in match_fields.items()):
            matches.append(record_key)
    return matches


def _normalize_snapshot_assertions(
    final_snapshot: dict[str, dict[str, dict[str, Any]]],
    requirements: list[dict[str, Any]],
) -> set[tuple[str, str, str, str]]:
    assertions: set[tuple[str, str, str, str]] = set()
    for req in requirements:
        entity_type = req.get("entity_type")
        if not entity_type:
            continue

        record_key = req.get("record_key")
        field = req.get("field")
        if record_key is not None and field is not None:
            record = _lookup_snapshot_record(final_snapshot, entity_type, record_key)
            if isinstance(record, dict) and field in record:
                assertions.add((entity_type, record_key, field, _canonicalize_value(record.get(field))))
            continue

        match_fields = req.get("match_fields")
        expected_fields = req.get("expected_fields")
        if not isinstance(match_fields, dict) or expected_fields is None or not isinstance(expected_fields, dict):
            continue

        matches = _find_matching_records(entity_type, match_fields, final_snapshot)
        if len(matches) != 1:
            continue
        matched_key = matches[0]
        record = _lookup_snapshot_record(final_snapshot, entity_type, matched_key)
        if not isinstance(record, dict):
            continue
        for match_field in match_fields:
            if match_field in record:
                assertions.add((entity_type, matched_key, match_field, _canonicalize_value(record.get(match_field))))
        for expected_field in expected_fields:
            if expected_field in record:
                assertions.add(
                    (entity_type, matched_key, expected_field, _canonicalize_value(record.get(expected_field)))
                )
    return assertions


def _reconstruct_final_snapshot(
    task: TaskDefinition,
    state_diff: StateDiff,
) -> dict[str, dict[str, dict[str, Any]]]:
    if not task.task_env_path:
        return _snapshot_from_state_diff(state_diff)

    try:
        base_snapshot = _normalize_snapshot_structure(json.loads(resolve_task_env_path(task).read_text()))
    except FileNotFoundError:
        return _snapshot_from_state_diff(state_diff)

    snapshot = deepcopy(base_snapshot)
    for entity_type, records in state_diff.deleted.items():
        entity_records = snapshot.get(entity_type)
        if not isinstance(entity_records, dict):
            entity_records = {}
            snapshot[entity_type] = entity_records
        for record_key in records:
            entity_records.pop(record_key, None)
    for entity_type, records in state_diff.modified.items():
        entity_records = snapshot.get(entity_type)
        if not isinstance(entity_records, dict):
            entity_records = {}
            snapshot[entity_type] = entity_records
        for record_key, changes in records.items():
            record = entity_records.setdefault(record_key, {})
            for field, values in changes.items():
                record[field] = values.get("new")
    for entity_type, records in state_diff.created.items():
        entity_records = snapshot.get(entity_type)
        if not isinstance(entity_records, dict):
            entity_records = {}
            snapshot[entity_type] = entity_records
        for record_key, record in records.items():
            entity_records[record_key] = deepcopy(record)
    return snapshot


def _snapshot_from_state_diff(state_diff: StateDiff) -> dict[str, dict[str, dict[str, Any]]]:
    snapshot: dict[str, dict[str, dict[str, Any]]] = {}
    for entity_type, records in state_diff.created.items():
        snapshot.setdefault(entity_type, {}).update(deepcopy(records))
    for entity_type, records in state_diff.modified.items():
        entity_records = snapshot.setdefault(entity_type, {})
        for record_key, changes in records.items():
            entity_records.setdefault(record_key, {})
            for field, values in changes.items():
                entity_records[record_key][field] = values.get("new")
    return snapshot


def _normalize_strict_state_requirements(requirements: list[dict[str, Any]]) -> set[tuple[str, str, str, str]]:
    assertions: set[tuple[str, str, str, str]] = set()
    for req in requirements:
        entity_type = req.get("entity_type")
        record_key = req.get("record_key")
        field = req.get("field")
        if entity_type and record_key is not None and field is not None:
            assertions.add((entity_type, record_key, field, _canonicalize_value(req.get("expected_value"))))
    return assertions


def _strict_created_record_keys(requirements: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (req["entity_type"], req["record_key"])
        for req in requirements
        if req.get("entity_type") and req.get("record_key") is not None and req.get("field") is not None
    }


def _normalize_strict_state_diff(
    state_diff: StateDiff,
    strict_created_record_keys: set[tuple[str, str]],
) -> set[tuple[str, str, str, str]]:
    assertions: set[tuple[str, str, str, str]] = set()
    for entity_type, entities in state_diff.modified.items():
        for record_key, changes in entities.items():
            for field, values in changes.items():
                assertions.add((entity_type, record_key, field, _canonicalize_value(values.get("new"))))
    for entity_type, entities in state_diff.created.items():
        for record_key, record in entities.items():
            if (entity_type, record_key) not in strict_created_record_keys:
                continue
            for field, value in record.items():
                assertions.add((entity_type, record_key, field, _canonicalize_value(value)))
    return assertions


def _cart_item_ids_requirements(requirements: list[dict[str, Any]]) -> set[str]:
    expected_ids: set[str] = set()
    for req in requirements:
        if req.get("entity_type") != "carts" or req.get("field") != "item_ids":
            continue
        expected_value = req.get("expected_value")
        if isinstance(expected_value, list):
            expected_ids.update(str(item_id) for item_id in expected_value)
    return expected_ids


def _semantically_matched_cart_item_ids(
    requirements: list[dict[str, Any]],
    final_snapshot: dict[str, dict[str, dict[str, Any]]],
) -> set[str]:
    matched_ids: set[str] = set()
    for req in requirements:
        if req.get("entity_type") != "cart_items" or not isinstance(req.get("match_fields"), dict):
            continue
        matches = _find_matching_records("cart_items", req["match_fields"], final_snapshot)
        if len(matches) == 1:
            matched_ids.add(str(matches[0]))
    return matched_ids


def _ignore_semantically_covered_cart_item_ids(
    assertions: set[tuple[str, str, str, str]],
    requirements: list[dict[str, Any]],
    final_snapshot: dict[str, dict[str, dict[str, Any]]],
) -> set[tuple[str, str, str, str]]:
    semantic_item_ids = _semantically_matched_cart_item_ids(requirements, final_snapshot)
    if not semantic_item_ids:
        return assertions

    exact_item_ids = _cart_item_ids_requirements(requirements)
    filtered: set[tuple[str, str, str, str]] = set()
    for assertion in assertions:
        entity_type, _record_key, field, value = assertion
        if entity_type == "carts" and field == "item_ids":
            try:
                observed_ids = {str(item_id) for item_id in json.loads(value)}
            except (json.JSONDecodeError, TypeError):
                observed_ids = set()
            path_dependent_ids = observed_ids - exact_item_ids
            if path_dependent_ids and path_dependent_ids <= semantic_item_ids:
                continue
        filtered.add(assertion)
    return filtered


def _canonicalize_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _format_assertions(assertions: list[tuple[str, str, str, str]]) -> str:
    return "; ".join(
        f"{entity_type}.{record_key}.{field}={value}" for entity_type, record_key, field, value in assertions
    )


def _summarize_task_requirements_details(
    details: list[Any],
    required_ids: set[str],
    passed_ids: set[str],
) -> str:
    """Aggregate per-requirement reasoning into a single summary string for the
    task-judge slot. Distinguishes failed requirements (with their reasoning) from
    structural failures (missing IDs, dup IDs, malformed details).
    """
    if not required_ids:
        return "Task defines no task_requirements; trivially satisfied."
    failed_lines = []
    seen_ids: set[str] = set()
    for item in details:
        if not isinstance(item, dict):
            continue
        rid = item.get("id")
        if rid is None:
            continue
        rid_str = str(rid)
        seen_ids.add(rid_str)
        if item.get("passed") is True:
            continue
        reasoning = str(item.get("reasoning", "")).strip()
        failed_lines.append(f"{rid_str}: {reasoning}" if reasoning else f"{rid_str}: (no reasoning provided)")
    missing = required_ids - seen_ids
    if missing:
        failed_lines.append(f"missing judgments for required ids: {sorted(missing)}")
    extra = seen_ids - required_ids
    if extra:
        failed_lines.append(f"unexpected judgments for ids not in task_requirements: {sorted(extra)}")
    if not failed_lines and required_ids == passed_ids:
        return "All task_requirements satisfied."
    return "; ".join(failed_lines) if failed_lines else "Task-judge produced no per-requirement reasoning."


def evaluate_task_requirements_empty(task: TaskDefinition) -> TaskRequirementsScore | None:
    """Return the automatic result for tasks with no authored task requirements."""
    requirements = task.task_requirements
    if requirements is None:
        return None
    if requirements:
        return None
    return TaskRequirementsScore(
        score=1, details=[], reasoning="Task defines no task_requirements; trivially satisfied."
    )


# ---------------------------------------------------------------------------
# 3. Efficiency Metrics (deterministic)
# ---------------------------------------------------------------------------


def compute_efficiency(
    conversation: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> EfficiencyMetrics:
    """Compute deterministic efficiency metrics from trajectory data."""
    # Count turns (assistant messages)
    turns = sum(1 for msg in conversation if msg.get("role") == "assistant")

    # Count tool calls and errors
    total_calls = len(tool_calls)
    errors = sum(1 for tc in tool_calls if "error" in tc.get("result", {}))

    # Count redundant calls (same tool name + identical arguments)
    call_signatures = [(tc.get("name", ""), json.dumps(tc.get("arguments", {}), sort_keys=True)) for tc in tool_calls]
    signature_counts = Counter(call_signatures)
    redundant = sum(count - 1 for count in signature_counts.values() if count > 1)

    return EfficiencyMetrics(
        turns=turns,
        tool_calls=total_calls,
        tool_errors=errors,
        redundant_calls=redundant,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_conversation(conversation: list[dict[str, Any]], tool_calls: list[dict[str, Any]]) -> str:
    """Format conversation with tool call summaries for judge prompts."""
    lines = []
    tc_index = 0

    for msg in conversation:
        role = msg["role"].upper()
        content = msg.get("content", "")
        msg_tool_calls = msg.get("tool_calls") or []

        if role == "ASSISTANT" and msg_tool_calls:
            # Summarize tool calls
            tc_summaries = []
            for tc in msg_tool_calls:
                name = tc.get("name", "unknown")
                args = tc.get("arguments", {})
                # Find matching result
                result_summary = ""
                if tc_index < len(tool_calls):
                    result = tool_calls[tc_index].get("result", {})
                    if "error" in result:
                        result_summary = f" → ERROR: {result['error']}"
                    else:
                        result_summary = " → OK"
                    tc_index += 1
                tc_summaries.append(f"  [{name}({_abbreviate_args(args)}){result_summary}]")
            tool_text = "\n".join(tc_summaries)
            if content:
                lines.append(f"AGENT: {content}\n{tool_text}")
            else:
                lines.append(f"AGENT:\n{tool_text}")
        elif content:
            label = "AGENT" if role == "ASSISTANT" else "USER"
            lines.append(f"{label}: {content}")

    return "\n\n".join(lines)


def _format_state_diff(diff: StateDiff) -> str:
    """Format a StateDiff for judge prompts."""
    if diff.is_empty():
        return "No database changes were made."

    lines = []
    if diff.created:
        lines.append("### Created")
        for entity_type, entities in diff.created.items():
            for eid, record in entities.items():
                lines.append(f"- {entity_type} {eid}: {json.dumps(record, default=str)}")

    if diff.modified:
        lines.append("### Modified")
        for entity_type, entities in diff.modified.items():
            for eid, changes in entities.items():
                change_strs = [f"{k}: {v['old']} → {v['new']}" for k, v in changes.items()]
                lines.append(f"- {entity_type} {eid}: {', '.join(change_strs)}")

    if diff.deleted:
        lines.append("### Deleted")
        for entity_type, entities in diff.deleted.items():
            for eid, record in entities.items():
                lines.append(f"- {entity_type} {eid}")

    return "\n".join(lines)


def _abbreviate_args(args: dict) -> str:
    """Abbreviate tool call arguments for readability."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        sv = str(v)
        if len(sv) > 30:
            sv = sv[:27] + "..."
        parts.append(f"{k}={sv}")
    return ", ".join(parts)


class TaskRequirementsJudge:
    """LLM-powered binary evaluator for structured non-state task requirements."""

    def __init__(
        self,
        client: Any,
        prompts_dir: Path,
        system_prompt: str,
        reasoning_effort: str | None = None,
        judge_prompt: str = "judge_task_requirements.md",
    ):
        self.client = client
        self.prompts_dir = prompts_dir
        self.system_prompt = system_prompt
        self.reasoning_effort = reasoning_effort
        self.judge_prompt = judge_prompt

    def evaluate(
        self,
        task: TaskDefinition,
        conversation: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        state_diff: StateDiff,
    ) -> TaskRequirementsScore | None:
        empty_result = evaluate_task_requirements_empty(task)
        if empty_result is not None:
            return empty_result
        try:
            prompt = build_task_requirements_prompt(
                task=task,
                conversation=conversation,
                tool_calls=tool_calls,
                prompts_dir=self.prompts_dir,
                judge_prompt=self.judge_prompt,
            )
            response = self.client.complete_json(
                prompt=prompt,
                system_prompt=self.system_prompt,
                reasoning_effort=self.reasoning_effort,
                max_tokens=2 * 8192,
            )
            details = response.get("details")
            if not isinstance(details, list):
                details = []
            required_ids = {str(req.get("id")) for req in task.task_requirements or [] if req.get("id") is not None}
            passed_ids = {
                str(item.get("id"))
                for item in details
                if isinstance(item, dict) and item.get("passed") is True and item.get("id") is not None
            }
            score = 1 if required_ids and required_ids == passed_ids and len(details) == len(required_ids) else 0
            reasoning = _summarize_task_requirements_details(details, required_ids, passed_ids)
            return TaskRequirementsScore(score=score, details=details, reasoning=reasoning)
        except Exception as e:
            logger.warning("Task-requirements judge failed: %s", e)
            return None


class UXQualityJudge:
    """LLM-powered evaluator for user experience quality."""

    def __init__(
        self,
        client: Any,
        prompts_dir: Path,
        system_prompt: str,
        reasoning_effort: str | None = None,
        judge_prompt: str = "judge_ux_quality_user.md",
        system_prompt_file: str | None = "judge_ux_quality.md",
    ):
        self.client = client
        self.prompts_dir = prompts_dir
        if system_prompt_file:
            self.system_prompt = (prompts_dir / system_prompt_file).read_text()
        else:
            self.system_prompt = system_prompt
        self.reasoning_effort = reasoning_effort
        self.judge_prompt = judge_prompt

    def evaluate(
        self,
        task: TaskDefinition,
        conversation: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
    ) -> UXQualityResult | None:
        try:
            prompt = build_ux_prompt(
                task=task,
                conversation=conversation,
                tool_calls=tool_calls,
                prompts_dir=self.prompts_dir,
                judge_prompt=self.judge_prompt,
            )
            response = self.client.complete_json(
                prompt=prompt,
                system_prompt=self.system_prompt,
                reasoning_effort=self.reasoning_effort,
                max_tokens=16384,
            )
            score = response.get("ux_score")
            return UXQualityResult(
                user_control=int(response.get("user_control", 3)),
                friction=int(response.get("friction", 3)),
                situational_awareness=int(response.get("situational_awareness", 3)),
                communication_quality=int(response.get("communication_quality", 3)),
                intent_alignment=int(response.get("intent_alignment", 3)),
                reasoning=str(response.get("reasoning", "")),
                score=float(score) if isinstance(score, int | float) else None,
            )
        except Exception as e:
            logger.warning("UX quality judge failed: %s", e)
            return None
