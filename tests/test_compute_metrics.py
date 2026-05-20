import json
from datetime import datetime

import pytest

from state_bench.scripts.compute_metrics import (
    build_matrices,
    build_standard_metrics,
    compute_summary,
    filter_runs_to_split,
    load_run,
)
from state_bench.version import get_package_version


def test_compute_summary_includes_state_task_and_completion_rates():
    runs = [
        {
            "t1": {
                "task_id": "t1",
                "score": 5,
                "reasoning": "ok",
                "state_requirements_met": 1,
                "task_requirements_met": 1,
                "task_completion_pass": 1,
                "turns": 3,
                "tool_calls": 1,
                "input_tokens": 100,
                "cached_input_tokens": 50,
                "output_tokens": 10,
                "total_tokens": 110,
                "cost_usd": 0.001,
                "agent_turn_cost_usd": 0.0007,
                "memory_ingestion_cost_usd": 0.0002,
                "memory_retrieval_cost_usd": 0.0,
                "embedding_cost_usd": 0.0001,
                "embedding_input_tokens": 20,
            },
            "t2": {
                "task_id": "t2",
                "score": 2,
                "reasoning": "bad",
                "state_requirements_met": 1,
                "task_requirements_met": 0,
                "task_completion_pass": 0,
                "turns": 4,
                "tool_calls": 2,
                "input_tokens": 200,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "total_tokens": 220,
                "cost_usd": 0.002,
                "agent_turn_cost_usd": 0.0015,
                "memory_ingestion_cost_usd": 0.0,
                "memory_retrieval_cost_usd": 0.0002,
                "embedding_cost_usd": 0.0003,
                "embedding_input_tokens": 40,
            },
        },
        {
            "t1": {
                "task_id": "t1",
                "score": 3,
                "reasoning": "meh",
                "state_requirements_met": 0,
                "task_requirements_met": 1,
                "task_completion_pass": 0,
                "turns": 5,
                "tool_calls": 3,
                "input_tokens": 300,
                "cached_input_tokens": 100,
                "output_tokens": 30,
                "total_tokens": 330,
                "cost_usd": 0.003,
                "agent_turn_cost_usd": 0.002,
                "memory_ingestion_cost_usd": 0.0005,
                "memory_retrieval_cost_usd": 0.0002,
                "embedding_cost_usd": 0.0003,
                "embedding_input_tokens": 60,
            },
            "t2": {
                "task_id": "t2",
                "score": 4,
                "reasoning": "fine",
                "state_requirements_met": 1,
                "task_requirements_met": 1,
                "task_completion_pass": 1,
                "turns": 2,
                "tool_calls": 1,
                "input_tokens": 400,
                "cached_input_tokens": 150,
                "output_tokens": 40,
                "total_tokens": 440,
                "cost_usd": 0.004,
                "agent_turn_cost_usd": 0.003,
                "memory_ingestion_cost_usd": 0.0003,
                "memory_retrieval_cost_usd": 0.0004,
                "embedding_cost_usd": 0.0003,
                "embedding_input_tokens": 80,
            },
        },
    ]

    summary = compute_summary(build_matrices(runs))

    assert summary["state_pass@1"] == 0.75
    assert summary["task_requirements_pass@1"] == 0.75
    assert summary["task_completion_pass@1"] == 0.5
    assert summary["task_completion_pass@1_std_dev"] == 0.0
    assert summary["per_run_state_pass_counts"] == [2, 1]
    assert summary["per_run_task_requirements_pass_counts"] == [1, 2]
    assert summary["per_run_task_completion_pass_counts"] == [1, 1]
    assert summary["mean_cost_usd"] == 0.0025
    assert summary["mean_cost_usd_pass"] == 0.0025
    assert summary["mean_input_tokens"] == 250.0
    assert summary["mean_cached_input_tokens"] == 75.0
    assert summary["mean_output_tokens"] == 25.0
    assert summary["mean_total_tokens"] == 275.0
    assert summary["mean_embedding_input_tokens"] == 50.0
    assert summary["mean_agent_turn_cost_usd"] == 0.0018
    assert summary["mean_memory_ingestion_cost_usd"] == 0.00025
    assert summary["mean_memory_retrieval_cost_usd"] == 0.0002
    assert summary["mean_embedding_cost_usd"] == 0.00025
    assert "pass^2" not in summary


def test_compute_summary_includes_ux_scores():
    runs = [
        {
            "t1": {
                "task_id": "t1",
                "score": 1,
                "ux_score": 4.2,
                "reasoning": "ok",
                "state_requirements_met": 1,
                "task_requirements_met": 1,
                "task_completion_pass": 1,
                "turns": 3,
                "tool_calls": 1,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 10,
                "total_tokens": 110,
                "cost_usd": 0.001,
                "agent_turn_cost_usd": 0.0008,
                "memory_ingestion_cost_usd": 0.0001,
                "memory_retrieval_cost_usd": 0.0,
                "embedding_cost_usd": 0.0001,
                "embedding_input_tokens": 10,
            }
        },
        {
            "t1": {
                "task_id": "t1",
                "score": 0,
                "ux_score": 3.8,
                "reasoning": "bad",
                "state_requirements_met": 0,
                "task_requirements_met": 0,
                "task_completion_pass": 0,
                "turns": 5,
                "tool_calls": 2,
                "input_tokens": 200,
                "cached_input_tokens": 50,
                "output_tokens": 20,
                "total_tokens": 220,
                "cost_usd": 0.002,
                "agent_turn_cost_usd": 0.0014,
                "memory_ingestion_cost_usd": 0.0002,
                "memory_retrieval_cost_usd": 0.0002,
                "embedding_cost_usd": 0.0002,
                "embedding_input_tokens": 30,
            }
        },
    ]

    summary = compute_summary(build_matrices(runs))

    assert summary["mean_ux_score"] == 4.0
    assert summary["per_run_ux_scores"] == [4.2, 3.8]


def test_build_standard_metrics_returns_protocol_stamped_public_metrics():
    summary = {
        "pn": 5,
        "task_completion_pass@1": 0.72,
        "task_completion_pass@1_std_dev": 0.08,
        "task_completion_pass^N": 0.41,
        "mean_ux_score": 4.12,
        "mean_cost_usd": 0.003456,
        "mean_turns": 6.0,
        "mean_turns_pass": 5.5,
        "mean_tool_calls": 3.2,
        "mean_tool_calls_pass": 2.8,
    }

    standard_metrics = build_standard_metrics(summary, evaluation_protocol_id="protocol-test")

    datetime.fromisoformat(standard_metrics["timestamp"])
    assert standard_metrics == {
        "benchmark_version": get_package_version(),
        "timestamp": standard_metrics["timestamp"],
        "evaluation_protocol_id": "protocol-test",
        "num_runs": 5,
        "agent_model": None,
        "agent_pricing": None,
        "metrics": {
            "task_completion_pass@1": 0.72,
            "task_completion_pass@1_std_dev": 0.08,
            "task_completion_pass^5": 0.41,
            "mean_ux_score": 4.12,
            "mean_cost_usd": 0.0035,
        },
    }


def test_build_standard_metrics_verbose_includes_efficiency_metrics():
    summary = {
        "pn": 5,
        "task_completion_pass@1": 0.72,
        "task_completion_pass@1_std_dev": 0.08,
        "task_completion_pass^N": 0.41,
        "mean_ux_score": 4.12,
        "mean_cost_usd": 0.003456,
        "mean_turns": 6.04,
        "mean_turns_pass": 5.45,
        "mean_tool_calls": 3.24,
        "mean_tool_calls_pass": 2.84,
    }

    metrics = build_standard_metrics(summary, evaluation_protocol_id="protocol-test", verbose=True)["metrics"]

    assert metrics["mean_turns"] == 6.0
    assert metrics["mean_turns_pass"] == 5.5
    assert metrics["mean_tool_calls"] == 3.2
    assert metrics["mean_tool_calls_pass"] == 2.8


def _priced_trajectory(**overrides):
    traj = {
        "task_id": "t1",
        "task_completion_pass": 1,
        "ux_score": 4.0,
        "conversation": [],
        "agent_model": {"model_name": "test-model", "reasoning_level": "high"},
        "agent_pricing": {
            "model_name": "test-model",
            "input_cost_per_1m_tokens": 1.0,
            "output_cost_per_1m_tokens": 10.0,
            "cached_input_cost_per_1m_tokens": 0.1,
            "cached_input_pricing_provided": True,
            "currency": "USD",
            "source": "user_provided",
            "cost_accounting_version": "agent-pricing-v1",
            "cost_includes": [],
        },
        "token_usage": {
            "input_tokens": 1000,
            "cached_input_tokens": 100,
            "output_tokens": 50,
            "reasoning_output_tokens": 5,
            "total_tokens": 1050,
            "embedding_input_tokens": 0,
            "input_cost_usd": 0.0009,
            "cached_input_cost_usd": 0.00001,
            "output_cost_usd": 0.0005,
            "agent_turn_cost_usd": 0.00141,
            "memory_ingestion_cost_usd": 0.0,
            "memory_retrieval_cost_usd": 0.0,
            "embedding_cost_usd": 0.0,
            "other_llm_cost_usd": 0.0,
            "total_cost_usd": 0.00141,
        },
        "cost_usd": 0.00141,
    }
    traj.update(overrides)
    return traj


def test_load_run_validates_declared_pricing_against_token_usage(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    (run_dir / "t1.json").write_text(json.dumps(_priced_trajectory()))

    runs, meta = load_run(run_dir)

    assert runs["t1"]["cost_usd"] == 0.00141
    assert runs["t1"]["reasoning_output_tokens"] == 5
    assert runs["t1"]["agent_model"] == {"model_name": "test-model", "reasoning_level": "high"}
    assert meta["agent_pricing_records"] == [_priced_trajectory()["agent_pricing"]]


def test_load_run_allows_missing_agent_pricing(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    traj = _priced_trajectory()
    del traj["agent_pricing"]
    (run_dir / "t1.json").write_text(json.dumps(traj))

    runs, meta = load_run(run_dir)

    assert runs["t1"]["agent_pricing"] is None
    assert meta["agent_model_records"] == [{"model_name": "test-model", "reasoning_level": "high"}]
    assert meta["agent_pricing_records"] == []


def test_load_run_can_backfill_missing_agent_pricing(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    traj = _priced_trajectory()
    del traj["agent_pricing"]
    traj["token_usage"]["input_cost_usd"] = 0
    traj["token_usage"]["cached_input_cost_usd"] = 0
    traj["token_usage"]["output_cost_usd"] = 0
    traj["token_usage"]["agent_turn_cost_usd"] = 0
    traj["token_usage"]["total_cost_usd"] = 0
    traj["cost_usd"] = 0
    fallback_pricing = {
        "model_name": "test-model",
        "input_cost_per_1m_tokens": 1.0,
        "output_cost_per_1m_tokens": 10.0,
        "cached_input_cost_per_1m_tokens": 0.1,
        "cached_input_pricing_provided": True,
        "currency": "USD",
        "source": "test",
        "cost_accounting_version": "agent-pricing-v1",
        "cost_includes": [],
    }
    (run_dir / "t1.json").write_text(json.dumps(traj))

    runs, meta = load_run(run_dir, fallback_agent_pricing=fallback_pricing)

    assert runs["t1"]["cost_usd"] == pytest.approx(0.00141)
    assert runs["t1"]["agent_turn_cost_usd"] == pytest.approx(0.00141)
    assert runs["t1"]["agent_pricing"] == fallback_pricing
    assert meta["agent_pricing_records"] == [fallback_pricing]


def test_load_run_charges_cached_tokens_at_input_rate_without_cached_pricing(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    traj = _priced_trajectory()
    traj["agent_pricing"]["cached_input_cost_per_1m_tokens"] = None
    traj["agent_pricing"]["cached_input_pricing_provided"] = False
    traj["token_usage"]["input_cost_usd"] = 0.0009
    traj["token_usage"]["cached_input_cost_usd"] = 0.0001
    traj["token_usage"]["agent_turn_cost_usd"] = 0.0015
    traj["token_usage"]["total_cost_usd"] = 0.0015
    traj["cost_usd"] = 0.0015
    (run_dir / "t1.json").write_text(json.dumps(traj))

    runs, meta = load_run(run_dir)

    assert runs["t1"]["cost_usd"] == pytest.approx(0.0015)
    assert runs["t1"]["agent_pricing"]["cached_input_cost_per_1m_tokens"] is None
    assert meta["agent_pricing_records"] == [traj["agent_pricing"]]


def test_load_run_rejects_cost_that_does_not_match_declared_pricing(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    traj = _priced_trajectory()
    traj["token_usage"]["total_cost_usd"] = 9.0
    traj["cost_usd"] = 9.0
    (run_dir / "t1.json").write_text(json.dumps(traj))

    with pytest.raises(ValueError, match="does not match declared pricing"):
        load_run(run_dir)


def test_filter_runs_to_split_ignores_non_split_tasks():
    with open("state_bench/domains/travel/splits/train_test.json") as f:
        test_task_ids = json.load(f)["splits"]["test"]
    runs = [{task_id: {"task_id": task_id} for task_id in test_task_ids}]
    runs[0]["2-cancel_business_international"] = {"task_id": "2-cancel_business_international"}
    meta = [{"run_dir": "run1", "scored": 3, "files_seen": 3, "unscored": 0, "unscored_task_ids": []}]

    filtered, filtered_meta = filter_runs_to_split(
        runs, meta, domain="travel", split="test", split_version="train_test"
    )

    assert "2-cancel_business_international" not in filtered[0]
    assert len(filtered[0]) == 50
    assert filtered_meta[0]["ignored_non_split_scored"] == 1


def test_filter_runs_to_split_requires_complete_split():
    runs = [{"1-cancel_economy_domestic": {"task_id": "1-cancel_economy_domestic"}}]
    meta = [{"run_dir": "run1", "scored": 1, "files_seen": 1, "unscored": 0, "unscored_task_ids": []}]

    with pytest.raises(ValueError, match="split=test is incomplete"):
        filter_runs_to_split(runs, meta, domain="travel", split="test", split_version="train_test")


def test_filter_runs_to_split_can_ignore_missing_runs_for_local_analysis():
    runs = [{"1-cancel_economy_domestic": {"task_id": "1-cancel_economy_domestic"}}]
    meta = [{"run_dir": "run1", "scored": 1, "files_seen": 1, "unscored": 0, "unscored_task_ids": []}]

    filtered, filtered_meta = filter_runs_to_split(
        runs,
        meta,
        domain="travel",
        split="test",
        split_version="train_test",
        ignore_missing_runs=True,
    )

    assert list(filtered[0]) == ["1-cancel_economy_domestic"]
    assert filtered_meta[0]["missing_split_scored"] == 49
