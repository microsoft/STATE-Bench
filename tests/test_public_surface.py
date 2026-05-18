import importlib
import json
import tomllib
from pathlib import Path

import pytest

from state_bench.domain import get_domain_config
from state_bench.protocol import load_split_task_ids

PUBLIC_SCRIPT_MODULES = [
    "state_bench.scripts.run_task",
    "state_bench.scripts.run_batch",
    "state_bench.scripts.score",
    "state_bench.scripts.compute_metrics",
]

NON_PUBLIC_MODULES = [
    "state_bench.generation",
    "state_bench.replay",
    "state_bench.audits",
    "state_bench.scripts.generate_tasks",
    "state_bench.scripts.audit",
    "state_bench.domains.travel.generate_tasks",
    "state_bench.domains.customer_support.generate_tasks",
    "state_bench.domains.shopping_assistant.generate_tasks",
    "state_bench.domains.travel.task_registry",
    "state_bench.domains.customer_support.task_registry",
    "state_bench.domains.shopping_assistant.task_registry",
]


def test_public_script_modules_import() -> None:
    for module_name in PUBLIC_SCRIPT_MODULES:
        importlib.import_module(module_name)


def test_non_public_modules_are_not_importable() -> None:
    for module_name in NON_PUBLIC_MODULES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)


def test_public_domain_data_counts_and_no_provenance_fields() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        root = Path("state_bench/domains") / domain
        tasks = sorted((root / "tasks").glob("*.json"))
        envs = sorted((root / "task_envs").glob("*.json"))
        test_task_ids = load_split_task_ids(domain, "test")

        assert len(tasks) == 50, domain
        assert len(envs) == 50, domain
        assert {path.stem for path in tasks} == set(test_task_ids), domain
        assert {path.stem for path in envs} == set(test_task_ids), domain

        for task_path in tasks:
            task = json.loads(task_path.read_text())
            assert "replay_trace_hash" not in task, task_path.name
            assert "_replay_trace" not in task, task_path.name


def test_public_task_summaries_do_not_expose_internal_provenance() -> None:
    forbidden_fragments = [
        "v0.",
        "0/3 pass",
        "Sourced from",
        "Source:",
        "failed this task",
        "hard task #",
        "hard tasks #",
    ]

    for task_path in sorted(Path("state_bench/domains").glob("*/tasks/*.json")):
        task = json.loads(task_path.read_text())
        summary = task.get("task_summary", "")
        for fragment in forbidden_fragments:
            assert fragment not in summary, f"{task_path}: {fragment}"


def test_train_task_trajectories_only_expose_complete_conversations() -> None:
    dataset_root = Path("datasets/train_task_trajectories")
    trajectory_paths = sorted(dataset_root.glob("*/*.json"))

    assert len(trajectory_paths) == 300
    for trajectory_path in trajectory_paths:
        domain_name = trajectory_path.parent.name
        trajectory = json.loads(trajectory_path.read_text())

        assert list(trajectory) == ["conversation"], trajectory_path
        assert isinstance(trajectory["conversation"], list), trajectory_path
        assert trajectory["conversation"][0]["role"] == "system", trajectory_path
        assert trajectory["conversation"][0]["content"].startswith(
            get_domain_config(domain_name).agent_system_prompt.split("{now}", 1)[0]
        )


def test_package_config_includes_train_task_trajectories() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert force_include["datasets/train_task_trajectories"] == "datasets/train_task_trajectories"


def test_declared_license_has_license_file() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert pyproject["project"]["license"]["text"] == "MIT"
    assert Path("LICENSE").read_text().startswith("MIT License\n")


def test_public_dev_extra_matches_uv_dev_group() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert pyproject["project"]["optional-dependencies"]["dev"] == pyproject["dependency-groups"]["dev"]
