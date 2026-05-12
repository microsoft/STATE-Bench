from __future__ import annotations

from pathlib import Path

from state_bench.domain import DomainConfig
from state_bench.paths import PACKAGE_ROOT
from state_bench.schemas import TaskDefinition


def resolve_task_env_path(task: TaskDefinition) -> Path:
    if not task.task_env_path:
        raise FileNotFoundError(
            f"Task-local environment not declared for task {task.task_id}; expected task_env_path in task JSON"
        )
    path = Path(task.task_env_path)
    if path.is_absolute():
        return path
    repo_path = Path.cwd() / path
    if repo_path.exists():
        return repo_path
    package_relative = path
    if path.parts and path.parts[0] == "state_bench":
        package_relative = Path(*path.parts[1:])
    return PACKAGE_ROOT / package_relative


def load_task_environment(domain: DomainConfig, task: TaskDefinition):
    task_env_path = resolve_task_env_path(task)
    if task_env_path.exists():
        return domain.env_data_class.load(task_env_path), task_env_path
    raise FileNotFoundError(f"Task-local environment declared for task {task.task_id} but not found: {task_env_path}")
