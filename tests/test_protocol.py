import json
import tomllib
from pathlib import Path

from state_bench.protocol import (
    DEFAULT_PROTOCOL_ID,
    DEFAULT_PROTOCOL_KEY,
    PROTOCOLS_DIR,
    build_protocol_id,
    load_default_protocol,
    load_protocol,
    load_split_manifest,
    load_split_task_ids,
)
from state_bench.version import get_benchmark_version, get_package_version


def test_protocol_loads_locked_gpt54_metadata_without_infra() -> None:
    protocol = load_protocol(DEFAULT_PROTOCOL_ID)

    assert protocol.protocol_id == DEFAULT_PROTOCOL_ID
    assert DEFAULT_PROTOCOL_ID == build_protocol_id(DEFAULT_PROTOCOL_KEY)
    assert protocol.data["benchmark_version"] == get_benchmark_version()
    assert protocol.official_model == "gpt-5.4"
    assert protocol.split == "test"
    assert protocol.split_version == "train_test"
    assert protocol.num_runs == 5
    assert "temperature" not in protocol.data["simulator"]
    assert "temperature" not in protocol.data["judge"]
    assert "base_url" not in str(protocol.data).lower()
    assert "endpoint" not in str(protocol.data).lower()


def test_default_protocol_is_benchmark_owned_current_protocol() -> None:
    protocol = load_default_protocol()

    assert protocol.protocol_id == DEFAULT_PROTOCOL_ID


def test_protocol_prompt_hashes_match_checked_in_prompts() -> None:
    protocol = load_protocol(DEFAULT_PROTOCOL_ID)

    assert protocol.validate_prompt_hashes() == []


def test_load_split_task_ids_reads_test_manifest() -> None:
    task_ids = load_split_task_ids("travel", "test")

    assert len(task_ids) == 50
    assert all(isinstance(task_id, str) for task_id in task_ids)


def test_checked_in_protocol_and_split_manifests_do_not_duplicate_package_version() -> None:
    protocol_data = json.loads((PROTOCOLS_DIR / f"{DEFAULT_PROTOCOL_KEY}.json").read_text())
    assert "benchmark_version" not in protocol_data
    assert "protocol_id" not in protocol_data

    for path in Path("state_bench/domains").glob("*/splits/train_test.json"):
        data = json.loads(path.read_text())
        assert "version" not in data


def test_version_helpers_read_single_pyproject_source() -> None:
    pyproject_version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]

    assert get_package_version() == pyproject_version
    assert get_benchmark_version() == f"v{pyproject_version}"


def test_split_manifest_loader_injects_package_version() -> None:
    manifest = load_split_manifest("travel")

    assert manifest["version"] == get_package_version()
