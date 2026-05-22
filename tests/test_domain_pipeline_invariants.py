import json
from pathlib import Path

from state_bench.protocol import load_default_protocol, load_split_manifest


def _domain_tasks(domain: str) -> list[Path]:
    return sorted(Path(f"state_bench/domains/{domain}/tasks").glob("*.json"))


def _domain_envs(domain: str) -> list[Path]:
    return sorted(Path(f"state_bench/domains/{domain}/task_envs").glob("*.json"))


def test_all_domains_have_task_env_and_state_requirements_metadata() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        for task_path in _domain_tasks(domain):
            task = json.loads(task_path.read_text())
            assert task.get("task_env_path") == f"state_bench/domains/{domain}/task_envs/{task_path.stem}.json", (
                task_path.name
            )
            assert "state_requirements" in task, task_path.name
            assert task["state_requirements"] is not None, task_path.name


def test_all_domains_have_matching_task_and_env_sets() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        task_ids = [path.stem for path in _domain_tasks(domain)]
        env_ids = [path.stem for path in _domain_envs(domain)]
        split_version = load_default_protocol().split_version
        manifest = load_split_manifest(domain, split_version)
        all_split_ids = set(manifest["splits"]["train"]) | set(manifest["splits"]["test"])

        assert set(task_ids) == all_split_ids, domain
        assert set(env_ids) == all_split_ids, domain


def test_public_task_and_env_ids_match_test_split() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        split_version = load_default_protocol().split_version
        manifest = load_split_manifest(domain, split_version)
        all_split_ids = set(manifest["splits"]["train"]) | set(manifest["splits"]["test"])

        assert {path.stem for path in _domain_tasks(domain)} == all_split_ids, domain
        assert {path.stem for path in _domain_envs(domain)} == all_split_ids, domain


def test_split_manifests_only_contain_train_test_task_ids() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        split_version = load_default_protocol().split_version
        raw_manifest = json.loads(Path(f"state_bench/domains/{domain}/splits/{split_version}.json").read_text())
        manifest = load_split_manifest(domain, split_version)
        task_ids = {path.stem for path in _domain_tasks(domain)}
        env_ids = {path.stem for path in _domain_envs(domain)}
        train = manifest["splits"]["train"]
        test = manifest["splits"]["test"]

        assert set(raw_manifest) == {"splits"}
        assert set(manifest) == {"splits", "version"}
        assert set(manifest["splits"]) == {"train", "test"}
        assert len(train) == 100
        assert len(test) == 50
        assert set(train).isdisjoint(test)
        assert set(train) | set(test) == task_ids
        assert set(train) | set(test) == env_ids


def test_split_entries_have_checked_in_task_and_env_files() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        split_version = load_default_protocol().split_version
        manifest = load_split_manifest(domain, split_version)
        root = Path("state_bench/domains") / domain

        for task_id in [*manifest["splits"]["train"], *manifest["splits"]["test"]]:
            task_path = root / "tasks" / f"{task_id}.json"
            assert task_path.is_file(), f"{domain} split missing task file: {task_id}"

        for task_id in [*manifest["splits"]["train"], *manifest["splits"]["test"]]:
            env_path = root / "task_envs" / f"{task_id}.json"
            assert env_path.is_file(), f"{domain} split missing task env file: {task_id}"
