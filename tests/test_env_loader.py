from pathlib import Path

import pytest

from state_bench.domain import get_domain_config
from state_bench.env_loader import load_task_environment
from state_bench.schemas import TaskDefinition, UserSimulatorConfig


def _make_task(*, task_env_path: str | None) -> TaskDefinition:
    return TaskDefinition(
        task_id="test-task",
        task_summary="Task summary",
        task_type="test_type",
        user_id="cust_001",
        now="2026-06-15T10:00:00",
        opening_message="hello",
        user_simulator=UserSimulatorConfig(
            personality="cooperative",
            user_sim_context="User simulator context",
            known_info=[],
            unknown_info=[],
            task_rules=[],
        ),
        task_env_path=task_env_path,
    )


def test_load_task_environment_uses_declared_task_env_for_customer_support() -> None:
    domain = get_domain_config("customer_support")
    task = _make_task(task_env_path="state_bench/domains/customer_support/task_envs/1-return_partial_order.json")

    env_data, env_path = load_task_environment(domain, task)

    assert env_path == Path.cwd() / "state_bench/domains/customer_support/task_envs/1-return_partial_order.json"
    assert len(env_data.orders) == 1


def test_load_task_environment_errors_when_declared_task_env_is_missing() -> None:
    domain = get_domain_config("customer_support")
    task = _make_task(task_env_path="state_bench/domains/customer_support/task_envs/does-not-exist.json")

    with pytest.raises(FileNotFoundError, match="Task-local environment declared"):
        load_task_environment(domain, task)


def test_load_task_environment_errors_when_task_env_path_is_missing() -> None:
    domain = get_domain_config("customer_support")
    task = _make_task(task_env_path=None)

    with pytest.raises(FileNotFoundError, match="Task-local environment not declared"):
        load_task_environment(domain, task)


def test_task_definition_normalizes_null_state_requirements_to_empty_list() -> None:
    task = TaskDefinition.from_dict(
        {
            "task_id": "test-task",
            "task_summary": "Task summary",
            "state_requirements": None,
            "user_id": "cust_001",
            "opening_message": "hello",
            "user_simulator": {
                "personality": "cooperative",
                "user_sim_context": "User simulator context",
                "known_info": [],
                "unknown_info": [],
                "task_rules": [],
            },
        }
    )

    assert task.state_requirements == []


def test_task_definition_serializes_empty_state_requirements_as_list() -> None:
    task = _make_task(task_env_path="state_bench/domains/customer_support/task_envs/1-return_partial_order.json")
    task.state_requirements = []

    payload = task.to_dict()

    assert payload["state_requirements"] == []


def test_task_definition_round_trips_optional_task_type() -> None:
    task = TaskDefinition.from_dict(
        {
            "task_id": "test-task",
            "task_summary": "Task summary",
            "task_type": "policy_info_or_restraint",
            "user_id": "cust_001",
            "opening_message": "hello",
            "user_simulator": {"personality": "cooperative", "user_sim_context": "ctx"},
        }
    )

    assert task.task_type == "policy_info_or_restraint"
    assert task.to_dict()["task_type"] == "policy_info_or_restraint"


def test_task_definition_requires_task_summary_and_user_sim_context() -> None:
    with pytest.raises(ValueError, match="task_summary is required"):
        TaskDefinition.from_dict(
            {
                "task_id": "missing-summary",
                "user_id": "cust_001",
                "opening_message": "hello",
                "user_simulator": {
                    "personality": "cooperative",
                    "user_sim_context": "ctx",
                    "known_info": [],
                    "unknown_info": [],
                    "task_rules": [],
                },
            }
        )

    with pytest.raises(ValueError, match="user_simulator.user_sim_context is required"):
        TaskDefinition.from_dict(
            {
                "task_id": "missing-context",
                "task_summary": "Task summary",
                "user_id": "cust_001",
                "opening_message": "hello",
                "user_simulator": {
                    "personality": "cooperative",
                    "known_info": [],
                    "unknown_info": [],
                    "task_rules": [],
                },
            }
        )
