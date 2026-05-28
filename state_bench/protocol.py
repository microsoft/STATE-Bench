"""Versioned canonical evaluation protocol helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from state_bench.paths import CONFIGS_DIR, DOMAINS_DIR
from state_bench.version import get_benchmark_version, get_package_version

PROTOCOLS_DIR = CONFIGS_DIR / "eval_protocols"
DEFAULT_PROTOCOL_KEY = "gpt54"


def build_protocol_id(protocol_key: str = DEFAULT_PROTOCOL_KEY) -> str:
    return f"state_bench_{get_benchmark_version()}_{protocol_key}"


DEFAULT_PROTOCOL_ID = build_protocol_id()


@dataclass(frozen=True)
class EvaluationProtocol:
    """Public, non-secret metadata for a canonical evaluation protocol."""

    data: dict[str, Any]

    @property
    def protocol_id(self) -> str:
        return str(self.data["protocol_id"])

    @property
    def split(self) -> str:
        return str(self.data["split"])

    @property
    def split_version(self) -> str:
        return str(self.data["split_version"])

    @property
    def num_runs(self) -> int:
        return int(self.data["num_runs"])

    @property
    def domains(self) -> list[str]:
        return [str(domain) for domain in self.data["domains"]]

    @property
    def official_model(self) -> str:
        return str(self.data["official_model"])

    @property
    def judge_reasoning_effort(self) -> str | None:
        value = self.data.get("judge", {}).get("reasoning_effort")
        return None if value is None else str(value)

    def simulator_metadata(self, domain: str) -> dict[str, Any]:
        simulator = self.data["simulator"]
        return {
            "evaluation_protocol_id": self.protocol_id,
            "simulator_model": simulator["model"],
            "simulator_prompt_hash": self._single_hash("simulator", domain, "user_sim_base.md"),
        }

    def judge_metadata(self, domain: str) -> dict[str, Any]:
        judge = self.data["judge"]
        return {
            "scoring_protocol_id": self.protocol_id,
            "judge_model": judge["model"],
            "judge_reasoning_effort": judge.get("reasoning_effort"),
            "judge_prompt_hashes": self.domain_prompt_hashes("judge", domain),
        }

    def domain_prompt_hashes(self, section: str, domain: str) -> dict[str, str]:
        prefix = f"{domain}/"
        hashes = self.data[section]["prompt_hashes"]
        return {key.split("/", 1)[1]: value for key, value in hashes.items() if key.startswith(prefix)}

    def validate_prompt_hashes(self) -> list[str]:
        """Return validation errors for prompt files whose content no longer matches the protocol."""
        errors: list[str] = []
        for section in ("simulator", "judge"):
            for key, expected in self.data[section]["prompt_hashes"].items():
                domain, filename = key.split("/", 1)
                path = DOMAINS_DIR / domain / "prompts" / filename
                if not path.exists():
                    errors.append(f"missing prompt file for {section}: {path}")
                    continue
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual != expected:
                    errors.append(f"prompt hash mismatch for {section} {key}: expected {expected}, got {actual}")
        return errors

    def _single_hash(self, section: str, domain: str, filename: str) -> str:
        key = f"{domain}/{filename}"
        return str(self.data[section]["prompt_hashes"][key])


def _protocol_path(protocol_id: str) -> Path:
    version_prefix = f"state_bench_{get_benchmark_version()}_"
    protocol_key = protocol_id.removeprefix(version_prefix)
    return PROTOCOLS_DIR / f"{protocol_key}.json"


def load_protocol(protocol_id: str) -> EvaluationProtocol:
    path = _protocol_path(protocol_id)
    if not path.exists():
        available = ", ".join(build_protocol_id(p.stem) for p in sorted(PROTOCOLS_DIR.glob("*.json"))) or "(none)"
        raise ValueError(f"Unknown evaluation protocol {protocol_id!r}. Available: {available}")
    data = json.loads(path.read_text())
    data["protocol_id"] = protocol_id
    data["benchmark_version"] = get_benchmark_version()
    return EvaluationProtocol(data=data)


def load_default_protocol() -> EvaluationProtocol:
    """Load the benchmark-owner selected canonical protocol."""
    return load_protocol(DEFAULT_PROTOCOL_ID)


def list_protocols() -> list[str]:
    return [path.stem for path in sorted(PROTOCOLS_DIR.glob("*.json"))]


def load_split_manifest(domain: str, split_version: str = "train_test") -> dict[str, Any]:
    path = DOMAINS_DIR / domain / "splits" / f"{split_version}.json"
    data = json.loads(path.read_text())
    data["version"] = get_package_version()
    return data


def load_split_task_ids(domain: str, split: str, split_version: str = "train_test") -> list[str]:
    path = DOMAINS_DIR / domain / "splits" / f"{split_version}.json"
    data = load_split_manifest(domain, split_version)
    splits = data["splits"]
    if split == "all":
        seen: dict[str, None] = {}
        for split_ids in splits.values():
            for task_id in split_ids:
                seen.setdefault(str(task_id), None)
        return list(seen)
    try:
        task_ids = splits[split]
    except KeyError as exc:
        raise ValueError(f"Split {split!r} not found in {path}") from exc
    return [str(task_id) for task_id in task_ids]
