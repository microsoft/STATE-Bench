"""Compute metrics from existing run results.

Reads trajectory JSONs from outputs/<domain>/run*/ and produces:
  - metrics.json: aggregate metrics only
  - per_task_metrics/{task_id}.json: per-task breakdown with per-run task-completion and UX metrics

Usage:
    uv run python -m state_bench.scripts.compute_metrics --save-filepath outputs/travel/metrics.json
    uv run python -m state_bench.scripts.compute_metrics --domain travel --save-filepath outputs/travel/metrics.json
    uv run python -m state_bench.scripts.compute_metrics --results-dir outputs/travel --save-filepath outputs/travel/metrics.json
    uv run python -m state_bench.scripts.compute_metrics --num-runs 5 --save-filepath outputs/travel/metrics.json
    uv run python -m state_bench.scripts.compute_metrics --domain travel --num-runs 5 --save-filepath outputs/travel/metrics.json
"""

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from state_bench.agents.base import PRICING_CONFIG_PATH, agent_pricing_from_config
from state_bench.protocol import load_default_protocol, load_split_task_ids
from state_bench.version import get_package_version


def _avg(vals: list[float | int]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _stddev(vals: list[float | int]) -> float:
    if not vals:
        return 0.0
    mean = _avg(vals)
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))


def _validate_agent_model(traj: dict, path: Path) -> dict | None:
    model = traj.get("agent_model")
    if model is None:
        pricing = traj.get("agent_pricing")
        if isinstance(pricing, dict) and str(pricing.get("model_name", "")).strip():
            return {"model_name": str(pricing["model_name"]), "reasoning_level": None}
        return None
    if not isinstance(model, dict):
        raise ValueError(f"{path}: agent_model metadata must be an object when present")
    model_name = str(model.get("model_name", "")).strip()
    if not model_name:
        raise ValueError(f"{path}: agent_model.model_name must be non-empty")
    reasoning_level = model.get("reasoning_level")
    if reasoning_level is not None:
        reasoning_level = str(reasoning_level).strip() or None
    return {"model_name": model_name, "reasoning_level": reasoning_level}


def _validate_agent_pricing(traj: dict, path: Path) -> dict | None:
    pricing = traj.get("agent_pricing")
    if pricing is None:
        return None
    if not isinstance(pricing, dict):
        raise ValueError(f"{path}: agent_pricing metadata must be an object when present")

    required = ["model_name", "input_cost_per_1m_tokens", "output_cost_per_1m_tokens", "currency", "source"]
    missing = [field for field in required if field not in pricing]
    if missing:
        raise ValueError(f"{path}: incomplete agent_pricing metadata; missing {', '.join(missing)}")
    if not str(pricing["model_name"]).strip():
        raise ValueError(f"{path}: agent_pricing.model_name must be non-empty")
    for field in ["input_cost_per_1m_tokens", "output_cost_per_1m_tokens"]:
        value = pricing[field]
        if not isinstance(value, int | float) or value < 0:
            raise ValueError(f"{path}: agent_pricing.{field} must be a non-negative number")

    cached_price = pricing.get("cached_input_cost_per_1m_tokens")
    cached_provided = bool(pricing.get("cached_input_pricing_provided", cached_price is not None))
    if cached_price is not None and (not isinstance(cached_price, int | float) or cached_price < 0):
        raise ValueError(f"{path}: agent_pricing.cached_input_cost_per_1m_tokens must be null or a non-negative number")

    return {
        "model_name": pricing["model_name"],
        "input_cost_per_1m_tokens": pricing["input_cost_per_1m_tokens"],
        "output_cost_per_1m_tokens": pricing["output_cost_per_1m_tokens"],
        "cached_input_cost_per_1m_tokens": cached_price,
        "cached_input_pricing_provided": cached_provided,
        "currency": pricing["currency"],
        "source": pricing["source"],
        "cost_accounting_version": pricing.get("cost_accounting_version", "agent-pricing-v1"),
        "cost_includes": pricing.get("cost_includes", []),
    }


def _agent_pricing_from_config(model_name: str) -> dict:
    return agent_pricing_from_config(model_name).to_dict()


def _cost_fields_from_pricing(traj: dict, pricing: dict, path: Path) -> dict[str, float]:
    usage = traj.get("token_usage")
    if not isinstance(usage, dict):
        raise ValueError(f"{path}: missing token_usage; cannot compute cost")

    input_tokens = int(_num(usage.get("input_tokens")))
    cached_input_tokens = int(_num(usage.get("cached_input_tokens")))
    output_tokens = int(_num(usage.get("output_tokens")))
    embedding_cost = _num(usage.get("embedding_cost_usd"))
    embedding_tokens = int(_num(usage.get("embedding_input_tokens")))

    if cached_input_tokens > 0 and not pricing["cached_input_pricing_provided"]:
        raise ValueError(
            f"{path}: trajectory has cached_input_tokens={cached_input_tokens}, but cached input pricing was not provided"
        )
    if embedding_tokens > 0 or embedding_cost > 0:
        raise ValueError(f"{path}: embedding cost accounting is not supported for official public metrics yet")

    non_cached_input_tokens = max(0, input_tokens - cached_input_tokens)
    input_cost = non_cached_input_tokens * pricing["input_cost_per_1m_tokens"] / 1_000_000
    cached_input_cost = 0.0
    if cached_input_tokens:
        cached_input_cost = cached_input_tokens * pricing["cached_input_cost_per_1m_tokens"] / 1_000_000
    output_cost = output_tokens * pricing["output_cost_per_1m_tokens"] / 1_000_000
    total_cost = input_cost + cached_input_cost + output_cost

    return {
        "input_cost_usd": input_cost,
        "cached_input_cost_usd": cached_input_cost,
        "output_cost_usd": output_cost,
        "total_cost_usd": total_cost,
    }


def _num(value: object, *, default: float = 0.0) -> float:
    if value is None:
        return default
    if not isinstance(value, int | float):
        raise ValueError(f"expected numeric cost/token value, got {type(value).__name__}")
    return float(value)


def _task_requirements_reasoning(traj: dict) -> str:
    # Prefer the explicit field written by EvaluationResult.to_dict.
    direct = traj.get("task_requirements_reasoning")
    if direct:
        return str(direct)
    # Fallback: synthesize from per-requirement details (older trajectories without
    # the explicit field).
    details = traj.get("task_requirements_details")
    if not isinstance(details, list):
        return ""
    failed = []
    for item in details:
        if not isinstance(item, dict) or item.get("passed") is True:
            continue
        req_id = item.get("id", "unknown")
        reason = item.get("reasoning", "")
        failed.append(f"{req_id}: {reason}".strip())
    return "; ".join(failed)


def _validate_cost_from_pricing(traj: dict, pricing: dict, path: Path) -> None:
    usage = traj.get("token_usage")
    checks = _cost_fields_from_pricing(traj, pricing, path)

    checks = {
        "input_cost_usd": checks["input_cost_usd"],
        "cached_input_cost_usd": checks["cached_input_cost_usd"],
        "output_cost_usd": checks["output_cost_usd"],
        "total_cost_usd": checks["total_cost_usd"],
    }
    tolerance = 1e-9
    for field, expected in checks.items():
        actual = _num(usage.get(field))
        if abs(actual - expected) > tolerance:
            raise ValueError(
                f"{path}: token_usage.{field}={actual:.12f} does not match declared pricing expected {expected:.12f}"
            )

    top_level_cost = traj.get("cost_usd")
    if top_level_cost is not None and abs(_num(top_level_cost) - checks["total_cost_usd"]) > tolerance:
        raise ValueError(f"{path}: cost_usd does not match declared pricing and token_usage")


def _pricing_key(pricing: dict) -> str:
    return json.dumps(pricing, sort_keys=True, separators=(",", ":"))


UX_DIMENSIONS = {
    "ux_consent": "mean_ux_consent",
    "ux_ease": "mean_ux_ease",
    "ux_discovery": "mean_ux_discovery",
    "ux_information_quality": "mean_ux_information_quality",
    "ux_disambiguation": "mean_ux_disambiguation",
}


def load_run(run_dir: Path, *, fallback_agent_pricing: dict | None = None) -> tuple[dict[str, dict], dict[str, object]]:
    """Load all scored trajectory results from a run directory.

    Unscored trajectories are skipped so the script can report partial metrics while a
    batch is still running. Metadata is returned alongside the scored results so the
    caller can report coverage.
    """
    results: dict[str, dict] = {}
    unscored: list[str] = []

    files = sorted(run_dir.glob("*.json"))
    for f in files:
        traj = json.loads(f.read_text())
        tid = traj["task_id"]

        task_completion = traj.get("task_completion_pass")

        ux_score = traj.get("ux_score")
        if task_completion is None and ux_score is None:
            unscored.append(tid)
            continue

        agent_model = _validate_agent_model(traj, f)
        agent_pricing = _validate_agent_pricing(traj, f)
        if agent_pricing is not None:
            _validate_cost_from_pricing(traj, agent_pricing, f)
            cost_fields = None
        elif fallback_agent_pricing is not None:
            agent_pricing = fallback_agent_pricing
            cost_fields = _cost_fields_from_pricing(traj, agent_pricing, f)
        else:
            cost_fields = None
        eff = traj.get("efficiency", {})
        token_usage = traj.get("token_usage", {})
        results[tid] = {
            "task_id": tid,
            "score": task_completion,
            "task_requirements_reasoning": _task_requirements_reasoning(traj),
            "state_requirements_reasoning": traj.get("state_requirements_reasoning", ""),
            "ux_score": ux_score,
            "ux_reasoning": traj.get("ux_reasoning"),
            "ux_consent": traj.get("ux_consent"),
            "ux_ease": traj.get("ux_ease"),
            "ux_discovery": traj.get("ux_discovery"),
            "ux_information_quality": traj.get("ux_information_quality"),
            "ux_disambiguation": traj.get("ux_disambiguation"),
            "state_requirements_met": traj.get("state_requirements_met"),
            "task_requirements_met": traj.get("task_requirements_met"),
            "task_completion_pass": task_completion,
            "turns": traj.get("turns") or (eff.get("turns", 0) if eff else 0),
            "tool_calls": traj.get("tool_calls")
            if isinstance(traj.get("tool_calls"), int)
            else (eff.get("tool_calls", 0) if eff else 0),
            "input_tokens": traj.get("input_tokens") or traj.get("token_usage", {}).get("input_tokens"),
            "cached_input_tokens": traj.get("cached_input_tokens")
            or traj.get("token_usage", {}).get("cached_input_tokens"),
            "output_tokens": traj.get("output_tokens") or traj.get("token_usage", {}).get("output_tokens"),
            "reasoning_output_tokens": traj.get("reasoning_output_tokens")
            or traj.get("token_usage", {}).get("reasoning_output_tokens"),
            "total_tokens": traj.get("total_tokens") or traj.get("token_usage", {}).get("total_tokens"),
            "embedding_input_tokens": traj.get("embedding_input_tokens")
            or traj.get("token_usage", {}).get("embedding_input_tokens"),
            "cost_usd": (cost_fields or {}).get("total_cost_usd")
            or traj.get("cost_usd")
            or token_usage.get("total_cost_usd"),
            "agent_turn_cost_usd": (cost_fields or {}).get("total_cost_usd") or token_usage.get("agent_turn_cost_usd"),
            "memory_ingestion_cost_usd": traj.get("token_usage", {}).get("memory_ingestion_cost_usd"),
            "memory_retrieval_cost_usd": traj.get("token_usage", {}).get("memory_retrieval_cost_usd"),
            "embedding_cost_usd": traj.get("token_usage", {}).get("embedding_cost_usd"),
            "agent_model": agent_model,
            "agent_pricing": agent_pricing,
        }

    model_records = {
        _pricing_key(result["agent_model"]): result["agent_model"]
        for result in results.values()
        if result.get("agent_model") is not None
    }
    pricing_records = {
        _pricing_key(result["agent_pricing"]): result["agent_pricing"]
        for result in results.values()
        if result.get("agent_pricing") is not None
    }
    meta = {
        "run_dir": str(run_dir),
        "files_seen": len(files),
        "scored": len(results),
        "unscored": len(unscored),
        "unscored_task_ids": unscored,
        "agent_model_records": list(model_records.values()),
        "agent_pricing_records": list(pricing_records.values()),
    }
    return results, meta


def load_all_runs(
    results_dir: Path,
    num_runs: int,
    num_runs_idx_start: int = 1,
    *,
    fallback_agent_pricing: dict | None = None,
) -> tuple[list[dict[str, dict]], list[dict[str, object]]]:
    """Load runs from a results directory, returning run dicts plus coverage metadata."""
    runs: list[dict[str, dict]] = []
    metas: list[dict[str, object]] = []
    for i in range(num_runs_idx_start, num_runs_idx_start + num_runs):
        run_dir = results_dir / f"run{i}"
        if not run_dir.exists():
            print(f"WARNING: {run_dir} not found, skipping")
            continue
        run_data, meta = load_run(run_dir, fallback_agent_pricing=fallback_agent_pricing)
        runs.append(run_data)
        metas.append(meta)
        extra = ""
        if meta["unscored"]:
            extra = f" ({meta['unscored']} unscored skipped)"
        print(f"Loaded run{i}: {meta['scored']} scored / {meta['files_seen']} files{extra}")
    return runs, metas


def filter_runs_to_split(
    runs: list[dict[str, dict]],
    run_meta: list[dict[str, object]],
    *,
    domain: str,
    split: str,
    split_version: str,
    ignore_missing_runs: bool = False,
) -> tuple[list[dict[str, dict]], list[dict[str, object]]]:
    """Filter loaded runs to a manifest split, requiring complete scored coverage."""
    expected_task_ids = load_split_task_ids(domain, split, split_version)
    expected = set(expected_task_ids)
    filtered_runs: list[dict[str, dict]] = []
    filtered_meta: list[dict[str, object]] = []

    for i, run in enumerate(runs):
        scored = set(run)
        missing = sorted(expected - scored)
        if missing:
            run_dir = run_meta[i].get("run_dir", f"run{i + 1}") if i < len(run_meta) else f"run{i + 1}"
            preview = ", ".join(missing[:10])
            if len(missing) > 10:
                preview += f", ... ({len(missing)} total)"
            message = f"{run_dir}: split={split} is incomplete; missing or unscored expected task(s): {preview}"
            if not ignore_missing_runs:
                raise ValueError(message)
            print(f"WARNING: {message}")

        filtered = {tid: run[tid] for tid in expected_task_ids if tid in run}
        ignored = len(scored - expected)
        print(
            f"Filtered run{i + 1} to split={split}: {len(filtered)} expected scored tasks, {ignored} non-split scored task(s) ignored"
        )
        filtered_runs.append(filtered)

        meta = dict(run_meta[i]) if i < len(run_meta) else {}
        meta["scored"] = len(filtered)
        meta["files_seen"] = len(filtered)
        meta["unscored"] = 0
        meta["unscored_task_ids"] = []
        meta["ignored_non_split_scored"] = ignored
        meta["missing_split_scored"] = len(missing)
        meta["split"] = split
        filtered_meta.append(meta)

    return filtered_runs, filtered_meta


def build_matrices(runs: list[dict[str, dict]]) -> dict:
    """Build per-task matrices from runs.

    Missing entries are represented as None rather than being coerced into failures.
    """
    all_tasks = sorted({tid for run in runs for tid in run})
    n = len(all_tasks)
    pn = len(runs)
    matrices = {
        "all_tasks": all_tasks,
        "n": n,
        "pn": pn,
        "pass": {
            tid: [
                run.get(tid, {}).get("task_completion_pass") == 1
                if run.get(tid, {}).get("task_completion_pass") is not None
                else None
                for run in runs
            ]
            for tid in all_tasks
        },
        "score": {tid: [run.get(tid, {}).get("score") if tid in run else None for run in runs] for tid in all_tasks},
        "ux_score": {
            tid: [run.get(tid, {}).get("ux_score") if tid in run else None for run in runs] for tid in all_tasks
        },
        "state": {
            tid: [run.get(tid, {}).get("state_requirements_met") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "task": {
            tid: [run.get(tid, {}).get("task_requirements_met") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "completion": {
            tid: [run.get(tid, {}).get("task_completion_pass") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "turns": {tid: [run.get(tid, {}).get("turns") if tid in run else None for run in runs] for tid in all_tasks},
        "tools": {
            tid: [run.get(tid, {}).get("tool_calls") if tid in run else None for run in runs] for tid in all_tasks
        },
        "input_tokens": {
            tid: [run.get(tid, {}).get("input_tokens") if tid in run else None for run in runs] for tid in all_tasks
        },
        "cached_input_tokens": {
            tid: [run.get(tid, {}).get("cached_input_tokens") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "output_tokens": {
            tid: [run.get(tid, {}).get("output_tokens") if tid in run else None for run in runs] for tid in all_tasks
        },
        "reasoning_output_tokens": {
            tid: [run.get(tid, {}).get("reasoning_output_tokens") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "total_tokens": {
            tid: [run.get(tid, {}).get("total_tokens") if tid in run else None for run in runs] for tid in all_tasks
        },
        "embedding_input_tokens": {
            tid: [run.get(tid, {}).get("embedding_input_tokens") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "cost_usd": {
            tid: [run.get(tid, {}).get("cost_usd") if tid in run else None for run in runs] for tid in all_tasks
        },
        "agent_turn_cost_usd": {
            tid: [run.get(tid, {}).get("agent_turn_cost_usd") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "memory_ingestion_cost_usd": {
            tid: [run.get(tid, {}).get("memory_ingestion_cost_usd") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "memory_retrieval_cost_usd": {
            tid: [run.get(tid, {}).get("memory_retrieval_cost_usd") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "embedding_cost_usd": {
            tid: [run.get(tid, {}).get("embedding_cost_usd") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "reasoning_task_req": {
            tid: [run.get(tid, {}).get("task_requirements_reasoning") if tid in run else None for run in runs]
            for tid in all_tasks
        },
        "reasoning_state_req": {
            tid: [run.get(tid, {}).get("state_requirements_reasoning") if tid in run else None for run in runs]
            for tid in all_tasks
        },
    }
    for ux_field in UX_DIMENSIONS:
        matrices[ux_field] = {
            tid: [run.get(tid, {}).get(ux_field) if tid in run else None for run in runs] for tid in all_tasks
        }
    return matrices


def compute_summary(m: dict, run_meta: list[dict[str, object]] | None = None) -> dict:
    """Compute summary metrics from matrices."""
    all_tasks, n, pn = m["all_tasks"], m["n"], m["pn"]
    (
        pass_m,
        ux_score_m,
        state_m,
        task_m,
        completion_m,
        turns_m,
        tools_m,
        input_tokens_m,
        cached_input_tokens_m,
        output_tokens_m,
        reasoning_output_tokens_m,
        total_tokens_m,
        embedding_input_tokens_m,
        cost_m,
        agent_turn_cost_m,
        memory_ingestion_cost_m,
        memory_retrieval_cost_m,
        embedding_cost_m,
    ) = (
        m["pass"],
        m["ux_score"],
        m["state"],
        m["task"],
        m["completion"],
        m["turns"],
        m["tools"],
        m["input_tokens"],
        m["cached_input_tokens"],
        m["output_tokens"],
        m["reasoning_output_tokens"],
        m["total_tokens"],
        m["embedding_input_tokens"],
        m["cost_usd"],
        m["agent_turn_cost_usd"],
        m["memory_ingestion_cost_usd"],
        m["memory_retrieval_cost_usd"],
        m["embedding_cost_usd"],
    )
    ux_dim_m = {ux_field: m[ux_field] for ux_field in UX_DIMENSIONS}

    comparable_tasks = [tid for tid in all_tasks if all(v is not None for v in pass_m[tid])]
    comparable_n = len(comparable_tasks)
    all_runs_pass_count = sum(1 for tid in comparable_tasks if all(v is True for v in pass_m[tid]))
    all_runs_pass_rate = all_runs_pass_count / comparable_n if comparable_n else 0.0

    per_run_scored_counts: list[int] = []
    per_run_pass_counts: list[int] = []
    per_run_rates: list[float] = []
    per_run_state_counts: list[int] = []
    per_run_state_rates: list[float] = []
    per_run_task_counts: list[int] = []
    per_run_task_rates: list[float] = []
    per_run_completion_counts: list[int] = []
    per_run_completion_rates: list[float] = []
    per_run_ux_scores: list[float] = []
    per_run_ux_dim_scores: dict[str, list[float]] = {ux_field: [] for ux_field in UX_DIMENSIONS}
    for i in range(pn):
        scored_i = sum(1 for tid in all_tasks if pass_m[tid][i] is not None)
        pass_i = sum(1 for tid in all_tasks if pass_m[tid][i] is True)
        state_scored_i = sum(1 for tid in all_tasks if state_m[tid][i] is not None)
        state_pass_i = sum(1 for tid in all_tasks if state_m[tid][i] == 1)
        task_scored_i = sum(1 for tid in all_tasks if task_m[tid][i] is not None)
        task_pass_i = sum(1 for tid in all_tasks if task_m[tid][i] == 1)
        completion_scored_i = sum(1 for tid in all_tasks if completion_m[tid][i] is not None)
        completion_pass_i = sum(1 for tid in all_tasks if completion_m[tid][i] == 1)
        per_run_scored_counts.append(scored_i)
        per_run_pass_counts.append(pass_i)
        per_run_rates.append(pass_i / scored_i if scored_i else 0.0)
        per_run_state_counts.append(state_pass_i)
        per_run_state_rates.append(state_pass_i / state_scored_i if state_scored_i else 0.0)
        per_run_task_counts.append(task_pass_i)
        per_run_task_rates.append(task_pass_i / task_scored_i if task_scored_i else 0.0)
        per_run_completion_counts.append(completion_pass_i)
        per_run_completion_rates.append(completion_pass_i / completion_scored_i if completion_scored_i else 0.0)
        ux_vals_i = [ux_score_m[tid][i] for tid in all_tasks if ux_score_m[tid][i] is not None]
        per_run_ux_scores.append(_avg(ux_vals_i))
        for ux_field in UX_DIMENSIONS:
            ux_dim_vals_i = [ux_dim_m[ux_field][tid][i] for tid in all_tasks if ux_dim_m[ux_field][tid][i] is not None]
            per_run_ux_dim_scores[ux_field].append(_avg(ux_dim_vals_i))
    all_ux_scores = [s for vals in ux_score_m.values() for s in vals if s is not None]
    all_ux_dim_scores = {
        out_field: round(
            _avg([score for vals in ux_dim_m[ux_field].values() for score in vals if score is not None]), 2
        )
        for ux_field, out_field in UX_DIMENSIONS.items()
    }
    all_turns = [t for vals in turns_m.values() for t in vals if t is not None]
    all_tools = [t for vals in tools_m.values() for t in vals if t is not None]
    all_input_tokens = [t for vals in input_tokens_m.values() for t in vals if t is not None]
    all_cached_input_tokens = [t for vals in cached_input_tokens_m.values() for t in vals if t is not None]
    all_output_tokens = [t for vals in output_tokens_m.values() for t in vals if t is not None]
    all_reasoning_output_tokens = [t for vals in reasoning_output_tokens_m.values() for t in vals if t is not None]
    all_total_tokens = [t for vals in total_tokens_m.values() for t in vals if t is not None]
    all_embedding_input_tokens = [t for vals in embedding_input_tokens_m.values() for t in vals if t is not None]
    all_costs = [c for vals in cost_m.values() for c in vals if c is not None]
    all_agent_turn_costs = [c for vals in agent_turn_cost_m.values() for c in vals if c is not None]
    all_memory_ingestion_costs = [c for vals in memory_ingestion_cost_m.values() for c in vals if c is not None]
    all_memory_retrieval_costs = [c for vals in memory_retrieval_cost_m.values() for c in vals if c is not None]
    all_embedding_costs = [c for vals in embedding_cost_m.values() for c in vals if c is not None]

    pass_turns = [
        turns_m[tid][i]
        for tid in all_tasks
        for i in range(pn)
        if pass_m[tid][i] is True and turns_m[tid][i] is not None
    ]
    pass_tools = [
        tools_m[tid][i]
        for tid in all_tasks
        for i in range(pn)
        if pass_m[tid][i] is True and tools_m[tid][i] is not None
    ]
    pass_costs = [
        cost_m[tid][i] for tid in all_tasks for i in range(pn) if pass_m[tid][i] is True and cost_m[tid][i] is not None
    ]

    model_records: dict[str, dict] = {}
    pricing_records: dict[str, dict] = {}
    for meta in run_meta or []:
        for model in meta.get("agent_model_records", []):
            model_records[_pricing_key(model)] = model
        for pricing in meta.get("agent_pricing_records", []):
            pricing_records[_pricing_key(pricing)] = pricing
    if len(model_records) > 1:
        models = ", ".join(sorted(record["model_name"] for record in model_records.values()))
        raise ValueError(f"Multiple agent model declarations found in results: {models}")
    if len(pricing_records) > 1:
        models = ", ".join(sorted(record["model_name"] for record in pricing_records.values()))
        raise ValueError(f"Multiple agent pricing declarations found in results: {models}")
    agent_model = next(iter(model_records.values()), None)
    agent_pricing = next(iter(pricing_records.values()), None)

    return {
        "pn": pn,
        "n": n,
        "state_pass@1": round(_avg(per_run_state_rates), 4),
        "task_requirements_pass@1": round(_avg(per_run_task_rates), 4),
        "task_completion_pass@1": round(_avg(per_run_completion_rates), 4),
        "task_completion_pass@1_std_dev": round(_stddev(per_run_completion_rates), 4),
        "task_completion_pass^N": round(all_runs_pass_rate, 4),
        "task_completion_pass^N_count": all_runs_pass_count,
        "mean_ux_score": round(_avg(all_ux_scores), 2),
        **all_ux_dim_scores,
        "mean_turns": round(_avg(all_turns), 1),
        "mean_turns_pass": round(_avg(pass_turns), 1),
        "mean_tool_calls": round(_avg(all_tools), 1),
        "mean_tool_calls_pass": round(_avg(pass_tools), 1),
        "mean_input_tokens": round(_avg(all_input_tokens), 1),
        "mean_cached_input_tokens": round(_avg(all_cached_input_tokens), 1),
        "mean_output_tokens": round(_avg(all_output_tokens), 1),
        "mean_reasoning_output_tokens": round(_avg(all_reasoning_output_tokens), 1),
        "mean_total_tokens": round(_avg(all_total_tokens), 1),
        "mean_embedding_input_tokens": round(_avg(all_embedding_input_tokens), 1),
        "mean_cost_usd": round(_avg(all_costs), 6),
        "mean_cost_usd_pass": round(_avg(pass_costs), 6),
        "mean_agent_turn_cost_usd": round(_avg(all_agent_turn_costs), 6),
        "mean_memory_ingestion_cost_usd": round(_avg(all_memory_ingestion_costs), 6),
        "mean_memory_retrieval_cost_usd": round(_avg(all_memory_retrieval_costs), 6),
        "mean_embedding_cost_usd": round(_avg(all_embedding_costs), 6),
        "per_run_state_pass_rates": [round(r, 4) for r in per_run_state_rates],
        "per_run_task_requirements_pass_rates": [round(r, 4) for r in per_run_task_rates],
        "per_run_task_completion_pass_rates": [round(r, 4) for r in per_run_completion_rates],
        "per_run_ux_scores": [round(r, 4) for r in per_run_ux_scores],
        "per_run_ux_consent_scores": [round(r, 4) for r in per_run_ux_dim_scores["ux_consent"]],
        "per_run_ux_ease_scores": [round(r, 4) for r in per_run_ux_dim_scores["ux_ease"]],
        "per_run_ux_discovery_scores": [round(r, 4) for r in per_run_ux_dim_scores["ux_discovery"]],
        "per_run_ux_information_quality_scores": [round(r, 4) for r in per_run_ux_dim_scores["ux_information_quality"]],
        "per_run_ux_disambiguation_scores": [round(r, 4) for r in per_run_ux_dim_scores["ux_disambiguation"]],
        "per_run_scored_counts": per_run_scored_counts,
        "per_run_state_pass_counts": per_run_state_counts,
        "per_run_task_requirements_pass_counts": per_run_task_counts,
        "per_run_task_completion_pass_counts": per_run_completion_counts,
        "comparable_task_count": comparable_n,
        "partial": any(count != n for count in per_run_scored_counts),
        "run_meta": run_meta or [],
        "agent_model": agent_model,
        "agent_pricing": agent_pricing,
    }


def print_per_task_table(m: dict) -> None:
    """Print the per-task results table."""
    all_tasks, pn = m["all_tasks"], m["pn"]
    pass_m, score_m, turns_m, tools_m = m["pass"], m["score"], m["turns"], m["tools"]

    run_hdrs = " ".join(f"R{i}" for i in range(1, pn + 1))
    print(f"\n| {'Task':<44} | {run_hdrs} | ^{pn} | Score | Turns | Tools |")
    print(f"|{'-' * 46}|{'-' * (pn * 3 + 1)}|{'-' * 4}|{'-' * 7}|{'-' * 7}|{'-' * 7}|")

    for tid in all_tasks:
        passes = pass_m[tid]
        present_passes = [v for v in passes if v is not None]
        comparable = len(present_passes) == pn
        all_p = "Y" if comparable and all(v is True for v in passes) else ("." if comparable else "-")

        run_cells = []
        for p in passes:
            if p is None:
                run_cells.append(". ")
            else:
                run_cells.append("P " if p else "F ")
        run_str = "".join(run_cells)

        avg_score = _avg([v for v in score_m[tid] if v is not None])
        avg_turns = _avg([v for v in turns_m[tid] if v is not None])
        avg_tools = _avg([v for v in tools_m[tid] if v is not None])

        print(f"| {tid:<44} | {run_str}| {all_p:>2} | {avg_score:5.1f} | {avg_turns:5.1f} | {avg_tools:5.1f} |")


def print_summary(s: dict, verbose: bool = False) -> None:
    """Print the summary metrics block."""
    pn, n = s["pn"], s["n"]
    print(f"\n{'=' * 60}")
    header = f"METRICS ({pn} runs, {n} scored tasks)"
    if s["partial"]:
        header += " [PARTIAL]"
    print(header)
    print(f"{'=' * 60}")
    print(
        f"{'task_completion_pass@1':<30s} {s['task_completion_pass@1']:.0%} +/- {s['task_completion_pass@1_std_dev']:.0%}"
    )
    print(f"{f'task_completion_pass^{pn}':<30s} {s['task_completion_pass^N']:.0%}")
    print(f"{'Mean UX score':<30s} {s['mean_ux_score']:.2f}/5")
    print(f"{'Mean cost/task':<30s} ${s['mean_cost_usd']:.4f}")
    if verbose:
        print(f"{'Mean turns':<30s} {s['mean_turns']:.1f}")
        print(f"{'Mean tool calls':<30s} {s['mean_tool_calls']:.1f}")
        print(f"{'state_pass@1':<30s} {s['state_pass@1']:.0%}")
        print(f"{'task_requirements_pass@1':<30s} {s['task_requirements_pass@1']:.0%}")
        print(f"{'Per-run scored counts':<30s} {', '.join(str(c) for c in s['per_run_scored_counts'])}")
        print(f"{'Per-run UX scores':<30s} {', '.join(f'{r:.2f}' for r in s['per_run_ux_scores'])}")
        print(f"{'Mean UX consent':<30s} {s['mean_ux_consent']:.2f}/5")
        print(f"{'Mean UX ease':<30s} {s['mean_ux_ease']:.2f}/5")
        print(f"{'Mean UX discovery':<30s} {s['mean_ux_discovery']:.2f}/5")
        print(f"{'Mean UX info quality':<30s} {s['mean_ux_information_quality']:.2f}/5")
        print(f"{'Mean UX disambiguation':<30s} {s['mean_ux_disambiguation']:.2f}/5")
        print(f"{'Per-run UX consent':<30s} {', '.join(f'{r:.2f}' for r in s['per_run_ux_consent_scores'])}")
        print(f"{'Per-run UX ease':<30s} {', '.join(f'{r:.2f}' for r in s['per_run_ux_ease_scores'])}")
        print(f"{'Per-run UX discovery':<30s} {', '.join(f'{r:.2f}' for r in s['per_run_ux_discovery_scores'])}")
        print(
            f"{'Per-run UX info quality':<30s} {', '.join(f'{r:.2f}' for r in s['per_run_ux_information_quality_scores'])}"
        )
        print(
            f"{'Per-run UX disambiguation':<30s} {', '.join(f'{r:.2f}' for r in s['per_run_ux_disambiguation_scores'])}"
        )
        print(f"{'Mean turns (pass only)':<30s} {s['mean_turns_pass']:.1f}")
        print(f"{'Mean tool calls (pass only)':<30s} {s['mean_tool_calls_pass']:.1f}")
        print(f"{'Mean input tokens':<30s} {s['mean_input_tokens']:.1f}")
        print(f"{'Mean cached input tokens':<30s} {s['mean_cached_input_tokens']:.1f}")
        print(f"{'Mean output tokens':<30s} {s['mean_output_tokens']:.1f}")
        print(f"{'Mean reasoning output tokens':<30s} {s['mean_reasoning_output_tokens']:.1f}")
        print(f"{'Mean total tokens':<30s} {s['mean_total_tokens']:.1f}")
        print(f"{'Mean embedding input tokens':<30s} {s['mean_embedding_input_tokens']:.1f}")
        print(f"{'Mean agent-turn cost':<30s} ${s['mean_agent_turn_cost_usd']:.4f}")
        print(f"{'Mean memory ingestion cost':<30s} ${s['mean_memory_ingestion_cost_usd']:.4f}")
        print(f"{'Mean memory retrieval cost':<30s} ${s['mean_memory_retrieval_cost_usd']:.4f}")
        print(f"{'Mean embedding cost':<30s} ${s['mean_embedding_cost_usd']:.4f}")
        print(f"{'Mean cost (pass only)':<30s} ${s['mean_cost_usd_pass']:.4f}")
        print(f"{'Comparable across all runs':<30s} {s['comparable_task_count']}")


def save_metrics(s: dict, results_dir: Path, *, skip_path: Path | None = None) -> None:
    """Save metrics.json."""
    pn = s["pn"]
    metrics = {
        "num_runs": pn,
        "total_scored_tasks": s["n"],
        "total_tasks": s["n"],
        "state_pass@1": s["state_pass@1"],
        "task_requirements_pass@1": s["task_requirements_pass@1"],
        "task_completion_pass@1": s["task_completion_pass@1"],
        "task_completion_pass@1_std_dev": s["task_completion_pass@1_std_dev"],
        f"task_completion_pass^{pn}": s["task_completion_pass^N"],
        f"task_completion_pass^{pn}_count": s["task_completion_pass^N_count"],
        "mean_ux_score": s["mean_ux_score"],
        "mean_ux_consent": s["mean_ux_consent"],
        "mean_ux_ease": s["mean_ux_ease"],
        "mean_ux_discovery": s["mean_ux_discovery"],
        "mean_ux_information_quality": s["mean_ux_information_quality"],
        "mean_ux_disambiguation": s["mean_ux_disambiguation"],
        "mean_turns": s["mean_turns"],
        "mean_turns_pass": s["mean_turns_pass"],
        "mean_tool_calls": s["mean_tool_calls"],
        "mean_tool_calls_pass": s["mean_tool_calls_pass"],
        "mean_input_tokens": s["mean_input_tokens"],
        "mean_cached_input_tokens": s["mean_cached_input_tokens"],
        "mean_output_tokens": s["mean_output_tokens"],
        "mean_reasoning_output_tokens": s["mean_reasoning_output_tokens"],
        "mean_total_tokens": s["mean_total_tokens"],
        "mean_embedding_input_tokens": s["mean_embedding_input_tokens"],
        "mean_cost_usd": s["mean_cost_usd"],
        "mean_cost_usd_pass": s["mean_cost_usd_pass"],
        "mean_agent_turn_cost_usd": s["mean_agent_turn_cost_usd"],
        "mean_memory_ingestion_cost_usd": s["mean_memory_ingestion_cost_usd"],
        "mean_memory_retrieval_cost_usd": s["mean_memory_retrieval_cost_usd"],
        "mean_embedding_cost_usd": s["mean_embedding_cost_usd"],
        "per_run_state_pass_rates": s["per_run_state_pass_rates"],
        "per_run_task_requirements_pass_rates": s["per_run_task_requirements_pass_rates"],
        "per_run_task_completion_pass_rates": s["per_run_task_completion_pass_rates"],
        "per_run_scored_counts": s["per_run_scored_counts"],
        "per_run_state_pass_counts": s["per_run_state_pass_counts"],
        "per_run_task_requirements_pass_counts": s["per_run_task_requirements_pass_counts"],
        "per_run_task_completion_pass_counts": s["per_run_task_completion_pass_counts"],
        "per_run_ux_scores": s["per_run_ux_scores"],
        "per_run_ux_consent_scores": s["per_run_ux_consent_scores"],
        "per_run_ux_ease_scores": s["per_run_ux_ease_scores"],
        "per_run_ux_discovery_scores": s["per_run_ux_discovery_scores"],
        "per_run_ux_information_quality_scores": s["per_run_ux_information_quality_scores"],
        "per_run_ux_disambiguation_scores": s["per_run_ux_disambiguation_scores"],
        "comparable_task_count": s["comparable_task_count"],
        "partial": s["partial"],
        "agent_model": s.get("agent_model"),
        "agent_pricing": s.get("agent_pricing"),
    }
    metrics_path = results_dir / "metrics.json"
    if skip_path is not None and metrics_path.resolve() == skip_path.resolve():
        print(f"Skipped detailed metrics overwrite: {metrics_path}")
        return
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nSaved: {metrics_path}")


def build_standard_metrics(s: dict, evaluation_protocol_id: str | None = None, *, verbose: bool = False) -> dict:
    """Return the official stamped public aggregate artifact."""
    pn = s["pn"]
    metrics = {
        "task_completion_pass@1": round(s["task_completion_pass@1"], 2),
        "task_completion_pass@1_std_dev": round(s["task_completion_pass@1_std_dev"], 2),
        f"task_completion_pass^{pn}": round(s["task_completion_pass^N"], 2),
        "mean_ux_score": round(s["mean_ux_score"], 2),
        "mean_cost_usd": round(s["mean_cost_usd"], 4),
    }
    if verbose:
        metrics.update(
            {
                "mean_turns": round(s["mean_turns"], 1),
                "mean_turns_pass": round(s["mean_turns_pass"], 1),
                "mean_tool_calls": round(s["mean_tool_calls"], 1),
                "mean_tool_calls_pass": round(s["mean_tool_calls_pass"], 1),
            }
        )
    return {
        "benchmark_version": get_package_version(),
        "timestamp": datetime.now(UTC).isoformat(),
        "evaluation_protocol_id": evaluation_protocol_id or load_default_protocol().protocol_id,
        "num_runs": pn,
        "agent_model": s.get("agent_model"),
        "agent_pricing": s.get("agent_pricing"),
        "metrics": metrics,
    }


def save_standard_metrics(
    s: dict, save_filepath: Path, evaluation_protocol_id: str | None = None, *, verbose: bool = False
) -> None:
    """Save the official public aggregate artifact."""
    save_filepath.parent.mkdir(parents=True, exist_ok=True)
    save_filepath.write_text(
        json.dumps(build_standard_metrics(s, evaluation_protocol_id, verbose=verbose), indent=2) + "\n"
    )
    print(f"Saved standardized metrics: {save_filepath}")


def save_per_task(m: dict, results_dir: Path) -> None:
    """Save per_task_metrics/{task_id}.json files."""
    all_tasks, pn = m["all_tasks"], m["pn"]
    (
        pass_m,
        score_m,
        ux_score_m,
        state_m,
        task_m,
        completion_m,
        turns_m,
        tools_m,
        input_tokens_m,
        cached_input_tokens_m,
        output_tokens_m,
        total_tokens_m,
        embedding_input_tokens_m,
        cost_m,
        agent_turn_cost_m,
        memory_ingestion_cost_m,
        memory_retrieval_cost_m,
        embedding_cost_m,
        reasoning_task_req_m,
        reasoning_state_req_m,
    ) = (
        m["pass"],
        m["score"],
        m["ux_score"],
        m["state"],
        m["task"],
        m["completion"],
        m["turns"],
        m["tools"],
        m["input_tokens"],
        m["cached_input_tokens"],
        m["output_tokens"],
        m["total_tokens"],
        m["embedding_input_tokens"],
        m["cost_usd"],
        m["agent_turn_cost_usd"],
        m["memory_ingestion_cost_usd"],
        m["memory_retrieval_cost_usd"],
        m["embedding_cost_usd"],
        m["reasoning_task_req"],
        m["reasoning_state_req"],
    )
    ux_consent_m = m["ux_consent"]
    ux_ease_m = m["ux_ease"]
    ux_discovery_m = m["ux_discovery"]
    ux_information_quality_m = m["ux_information_quality"]
    ux_disambiguation_m = m["ux_disambiguation"]

    analysis_dir = results_dir / "per_task_metrics"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    for tid in all_tasks:
        per_run = []
        for i in range(pn):
            per_run.append(
                {
                    "run": i + 1,
                    "present": pass_m[tid][i] is not None,
                    "passed": pass_m[tid][i],
                    "score": score_m[tid][i],
                    "ux_score": ux_score_m[tid][i],
                    "ux_consent": ux_consent_m[tid][i],
                    "ux_ease": ux_ease_m[tid][i],
                    "ux_discovery": ux_discovery_m[tid][i],
                    "ux_information_quality": ux_information_quality_m[tid][i],
                    "ux_disambiguation": ux_disambiguation_m[tid][i],
                    "state_requirements_met": state_m[tid][i],
                    "task_requirements_met": task_m[tid][i],
                    "task_completion_pass": completion_m[tid][i],
                    "turns": turns_m[tid][i],
                    "tool_calls": tools_m[tid][i],
                    "input_tokens": input_tokens_m[tid][i],
                    "cached_input_tokens": cached_input_tokens_m[tid][i],
                    "output_tokens": output_tokens_m[tid][i],
                    "total_tokens": total_tokens_m[tid][i],
                    "embedding_input_tokens": embedding_input_tokens_m[tid][i],
                    "cost_usd": cost_m[tid][i],
                    "agent_turn_cost_usd": agent_turn_cost_m[tid][i],
                    "memory_ingestion_cost_usd": memory_ingestion_cost_m[tid][i],
                    "memory_retrieval_cost_usd": memory_retrieval_cost_m[tid][i],
                    "embedding_cost_usd": embedding_cost_m[tid][i],
                    "task_requirements_reasoning": reasoning_task_req_m[tid][i],
                    "state_requirements_reasoning": reasoning_state_req_m[tid][i],
                }
            )
        task_analysis = {
            "task_id": tid,
            "avg_score": round(_avg([v for v in score_m[tid] if v is not None]), 2),
            "avg_ux_score": round(_avg([v for v in ux_score_m[tid] if v is not None]), 2),
            "avg_ux_consent": round(_avg([v for v in ux_consent_m[tid] if v is not None]), 2),
            "avg_ux_ease": round(_avg([v for v in ux_ease_m[tid] if v is not None]), 2),
            "avg_ux_discovery": round(_avg([v for v in ux_discovery_m[tid] if v is not None]), 2),
            "avg_ux_information_quality": round(_avg([v for v in ux_information_quality_m[tid] if v is not None]), 2),
            "avg_ux_disambiguation": round(_avg([v for v in ux_disambiguation_m[tid] if v is not None]), 2),
            "avg_turns": round(_avg([v for v in turns_m[tid] if v is not None]), 2),
            "avg_tool_calls": round(_avg([v for v in tools_m[tid] if v is not None]), 2),
            "avg_input_tokens": round(_avg([v for v in input_tokens_m[tid] if v is not None]), 2),
            "avg_cached_input_tokens": round(_avg([v for v in cached_input_tokens_m[tid] if v is not None]), 2),
            "avg_output_tokens": round(_avg([v for v in output_tokens_m[tid] if v is not None]), 2),
            "avg_total_tokens": round(_avg([v for v in total_tokens_m[tid] if v is not None]), 2),
            "avg_embedding_input_tokens": round(_avg([v for v in embedding_input_tokens_m[tid] if v is not None]), 2),
            "avg_cost_usd": round(_avg([v for v in cost_m[tid] if v is not None]), 6),
            "avg_agent_turn_cost_usd": round(_avg([v for v in agent_turn_cost_m[tid] if v is not None]), 6),
            "avg_memory_ingestion_cost_usd": round(_avg([v for v in memory_ingestion_cost_m[tid] if v is not None]), 6),
            "avg_memory_retrieval_cost_usd": round(_avg([v for v in memory_retrieval_cost_m[tid] if v is not None]), 6),
            "avg_embedding_cost_usd": round(_avg([v for v in embedding_cost_m[tid] if v is not None]), 6),
            "passes": pass_m[tid],
            "runs": per_run,
        }
        task_path = analysis_dir / f"{tid}.json"
        with open(task_path, "w") as f:
            json.dump(task_analysis, f, indent=2)
    print(f"Saved: {analysis_dir}/ ({len(all_tasks)} task files)")


def print_comparison(
    base_m: dict, base_s: dict, comp_m: dict, comp_s: dict, comp_dir: Path, verbose: bool = False
) -> None:
    """Print side-by-side comparison of baseline vs comparison metrics."""
    pn = base_s["pn"]
    cpn = comp_s["pn"]

    print(f"\n{'=' * 80}")
    print(f"COMPARISON: baseline ({pn} runs) vs {comp_dir.name} ({cpn} runs)")
    print(f"{'=' * 80}")

    print(f"\n{'Metric':<35} {'Baseline':>10} {'Compare':>10} {'Delta':>10}")
    print("-" * 68)
    print(
        f"{'Task completion pass@1':<35} {base_s['task_completion_pass@1']:>10.0%} {comp_s['task_completion_pass@1']:>10.0%} {comp_s['task_completion_pass@1'] - base_s['task_completion_pass@1']:>+10.0%}"
    )
    print(
        f"{f'Task completion pass^{pn}':<35} {base_s['task_completion_pass^N']:>10.0%} {comp_s['task_completion_pass^N']:>10.0%} {comp_s['task_completion_pass^N'] - base_s['task_completion_pass^N']:>+10.0%}"
    )
    print(
        f"{'Mean cost / task':<35} ${base_s['mean_cost_usd']:>9.4f} ${comp_s['mean_cost_usd']:>9.4f} {comp_s['mean_cost_usd'] - base_s['mean_cost_usd']:>+10.4f}"
    )
    print(
        f"{'Mean turns':<35} {base_s['mean_turns']:>10.1f} {comp_s['mean_turns']:>10.1f} {comp_s['mean_turns'] - base_s['mean_turns']:>+10.1f}"
    )
    print(
        f"{'Mean turns (pass only)':<35} {base_s['mean_turns_pass']:>10.1f} {comp_s['mean_turns_pass']:>10.1f} {comp_s['mean_turns_pass'] - base_s['mean_turns_pass']:>+10.1f}"
    )
    print(
        f"{'Mean tool calls':<35} {base_s['mean_tool_calls']:>10.1f} {comp_s['mean_tool_calls']:>10.1f} {comp_s['mean_tool_calls'] - base_s['mean_tool_calls']:>+10.1f}"
    )
    if verbose:
        print(
            f"{'Mean UX consent':<35} {base_s['mean_ux_consent']:>10.2f} {comp_s['mean_ux_consent']:>10.2f} {comp_s['mean_ux_consent'] - base_s['mean_ux_consent']:>+10.2f}"
        )
        print(
            f"{'Mean UX ease':<35} {base_s['mean_ux_ease']:>10.2f} {comp_s['mean_ux_ease']:>10.2f} {comp_s['mean_ux_ease'] - base_s['mean_ux_ease']:>+10.2f}"
        )
        print(
            f"{'Mean UX discovery':<35} {base_s['mean_ux_discovery']:>10.2f} {comp_s['mean_ux_discovery']:>10.2f} {comp_s['mean_ux_discovery'] - base_s['mean_ux_discovery']:>+10.2f}"
        )
        print(
            f"{'Mean UX info quality':<35} {base_s['mean_ux_information_quality']:>10.2f} {comp_s['mean_ux_information_quality']:>10.2f} {comp_s['mean_ux_information_quality'] - base_s['mean_ux_information_quality']:>+10.2f}"
        )
        print(
            f"{'Mean UX disambiguation':<35} {base_s['mean_ux_disambiguation']:>10.2f} {comp_s['mean_ux_disambiguation']:>10.2f} {comp_s['mean_ux_disambiguation'] - base_s['mean_ux_disambiguation']:>+10.2f}"
        )
        print(
            f"{'Mean turns (pass only)':<35} {base_s['mean_turns_pass']:>10.1f} {comp_s['mean_turns_pass']:>10.1f} {comp_s['mean_turns_pass'] - base_s['mean_turns_pass']:>+10.1f}"
        )
        print(
            f"{'Mean tool calls (pass only)':<35} {base_s['mean_tool_calls_pass']:>10.1f} {comp_s['mean_tool_calls_pass']:>10.1f} {comp_s['mean_tool_calls_pass'] - base_s['mean_tool_calls_pass']:>+10.1f}"
        )
        print(
            f"{'Mean input tokens':<35} {base_s['mean_input_tokens']:>10.1f} {comp_s['mean_input_tokens']:>10.1f} {comp_s['mean_input_tokens'] - base_s['mean_input_tokens']:>+10.1f}"
        )
        print(
            f"{'Mean cached input tokens':<35} {base_s['mean_cached_input_tokens']:>10.1f} {comp_s['mean_cached_input_tokens']:>10.1f} {comp_s['mean_cached_input_tokens'] - base_s['mean_cached_input_tokens']:>+10.1f}"
        )
        print(
            f"{'Mean output tokens':<35} {base_s['mean_output_tokens']:>10.1f} {comp_s['mean_output_tokens']:>10.1f} {comp_s['mean_output_tokens'] - base_s['mean_output_tokens']:>+10.1f}"
        )
        print(
            f"{'Mean embedding cost':<35} ${base_s['mean_embedding_cost_usd']:>9.4f} ${comp_s['mean_embedding_cost_usd']:>9.4f} {comp_s['mean_embedding_cost_usd'] - base_s['mean_embedding_cost_usd']:>+10.4f}"
        )

    base_pass_tasks = {tid for tid in base_m["all_tasks"] if any(v is True for v in base_m["pass"][tid])}
    comp_pass_tasks = {tid for tid in comp_m["all_tasks"] if any(v is True for v in comp_m["pass"][tid])}
    shared_pass_tasks = base_pass_tasks & comp_pass_tasks

    b_turns = [
        base_m["turns"][tid][i]
        for tid in shared_pass_tasks
        for i in range(pn)
        if base_m["pass"][tid][i] is True and base_m["turns"][tid][i] is not None
    ]
    b_tools = [
        base_m["tools"][tid][i]
        for tid in shared_pass_tasks
        for i in range(pn)
        if base_m["pass"][tid][i] is True and base_m["tools"][tid][i] is not None
    ]
    c_turns = [
        comp_m["turns"][tid][i]
        for tid in shared_pass_tasks
        for i in range(cpn)
        if comp_m["pass"].get(tid, [None] * cpn)[i] is True and comp_m["turns"][tid][i] is not None
    ]
    c_tools = [
        comp_m["tools"][tid][i]
        for tid in shared_pass_tasks
        for i in range(cpn)
        if comp_m["pass"].get(tid, [None] * cpn)[i] is True and comp_m["tools"][tid][i] is not None
    ]

    print(
        f"\n{'Shared-pass tasks (' + str(len(shared_pass_tasks)) + ')':<35} {'Baseline':>10} {'Compare':>10} {'Delta':>10}"
    )
    print("-" * 68)
    print(
        f"{'  Mean turns (pass only)':<35} {_avg(b_turns):>10.1f} {_avg(c_turns):>10.1f} {_avg(c_turns) - _avg(b_turns):>+10.1f}"
    )
    print(
        f"{'  Mean tool calls (pass only)':<35} {_avg(b_tools):>10.1f} {_avg(c_tools):>10.1f} {_avg(c_tools) - _avg(b_tools):>+10.1f}"
    )


def main():
    parser = argparse.ArgumentParser(description="Compute metrics from existing results")
    parser.add_argument("--domain", type=str, default="travel", help="Domain name (default: travel)")
    parser.add_argument("--results-dir", type=str, default=None, help="Results directory (default: outputs/<domain>)")
    parser.add_argument(
        "--split",
        type=str,
        default="test",
        choices=["test"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--ignore-missing-runs", action="store_true", help="Allow incomplete split coverage for local analysis"
    )
    parser.add_argument(
        "--agent-model-name",
        type=str,
        default=None,
        help="Override protocol model name when backfilling missing trajectory pricing from state_bench/configs/pricing.yaml",
    )
    parser.add_argument(
        "--num-runs", type=int, default=None, help="Number of runs to analyze (default: protocol requirement)"
    )
    parser.add_argument("--num-runs-idx-start", type=int, default=1, help="Starting run index to analyze (default: 1)")
    parser.add_argument(
        "--save-filepath", type=str, required=True, help="Path to write the standardized public metrics JSON file"
    )
    parser.add_argument("--compare", type=str, default=None, help="Compare against another results directory")
    parser.add_argument(
        "--verbose", action="store_true", help="Print UX dimension metrics and pass-only efficiency details"
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir) if args.results_dir else Path(f"outputs/{args.domain}")
    protocol = load_default_protocol()
    if args.num_runs is None:
        args.num_runs = protocol.num_runs
    if args.num_runs < 1:
        parser.error("--num-runs must be at least 1")
    if args.num_runs_idx_start < 1:
        parser.error("--num-runs-idx-start must be at least 1")
    if args.num_runs != protocol.num_runs:
        print(
            f"WARNING: Protocol {protocol.protocol_id} benchmark submission expects metrics computed on "
            f"{protocol.num_runs} runs; computing metrics on {args.num_runs} run(s) for local analysis."
        )
    fallback_agent_pricing = None
    if args.agent_model_name:
        fallback_agent_pricing = _agent_pricing_from_config(args.agent_model_name)
        print(f"Backfilling missing trajectory pricing from {PRICING_CONFIG_PATH}: {args.agent_model_name}")

    print(f"Loading from {results_dir}...")
    runs, run_meta = load_all_runs(
        results_dir,
        args.num_runs,
        args.num_runs_idx_start,
        fallback_agent_pricing=fallback_agent_pricing,
    )
    if not runs:
        print(
            f"No runs found. Run tasks first with: uv run python -m state_bench.scripts.run_batch --num-runs {protocol.num_runs}"
        )
        return
    runs, run_meta = filter_runs_to_split(
        runs,
        run_meta,
        domain=args.domain,
        split=args.split,
        split_version=protocol.split_version,
        ignore_missing_runs=args.ignore_missing_runs,
    )

    m = build_matrices(runs)
    s = compute_summary(m, run_meta=run_meta)

    print_per_task_table(m)
    print_summary(s, verbose=args.verbose)
    standard_metrics_path = Path(args.save_filepath)
    save_standard_metrics(s, standard_metrics_path, protocol.protocol_id, verbose=args.verbose)
    save_metrics(s, results_dir, skip_path=standard_metrics_path)
    save_per_task(m, results_dir)

    if args.compare:
        comp_dir = Path(args.compare)
        print(f"\nLoading comparison from {comp_dir}...")
        comp_runs, comp_meta = load_all_runs(
            comp_dir,
            args.num_runs,
            args.num_runs_idx_start,
            fallback_agent_pricing=fallback_agent_pricing,
        )
        if comp_runs:
            comp_runs, comp_meta = filter_runs_to_split(
                comp_runs,
                comp_meta,
                domain=args.domain,
                split=args.split,
                split_version=protocol.split_version,
                ignore_missing_runs=args.ignore_missing_runs,
            )
            comp_m = build_matrices(comp_runs)
            comp_s = compute_summary(comp_m, run_meta=comp_meta)
            print_comparison(m, s, comp_m, comp_s, comp_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
