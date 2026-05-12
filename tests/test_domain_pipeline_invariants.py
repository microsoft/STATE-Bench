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
        assert task_ids == env_ids, domain


def test_all_domains_have_contiguous_numbered_task_prefixes() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        task_numbers = sorted(int(path.stem.split("-", 1)[0]) for path in _domain_tasks(domain))
        assert task_numbers == list(range(1, len(task_numbers) + 1)), domain


def test_split_manifests_only_contain_train_test_task_ids() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        split_version = load_default_protocol().split_version
        raw_manifest = json.loads(Path(f"state_bench/domains/{domain}/splits/{split_version}.json").read_text())
        manifest = load_split_manifest(domain, split_version)
        task_ids = {path.stem for path in _domain_tasks(domain)}
        train = manifest["splits"]["train"]
        test = manifest["splits"]["test"]

        assert set(raw_manifest) == {"splits"}
        assert set(manifest) == {"splits", "version"}
        assert set(manifest["splits"]) == {"train", "test"}
        assert len(train) == 100
        assert len(test) == 50
        assert set(train).isdisjoint(test)
        assert set(train) | set(test) == task_ids


def test_split_entries_have_checked_in_task_and_env_files() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        split_version = load_default_protocol().split_version
        manifest = load_split_manifest(domain, split_version)
        root = Path("state_bench/domains") / domain

        for split_name in ("train", "test"):
            for task_id in manifest["splits"][split_name]:
                task_path = root / "tasks" / f"{task_id}.json"
                env_path = root / "task_envs" / f"{task_id}.json"

                assert task_path.is_file(), f"{domain} {split_name} missing task file: {task_id}"
                assert env_path.is_file(), f"{domain} {split_name} missing task env file: {task_id}"
