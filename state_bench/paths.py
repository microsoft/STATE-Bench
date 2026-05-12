"""Package data paths for STATE-Bench."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
CONFIGS_DIR = PACKAGE_ROOT / "configs"
DOMAINS_DIR = PACKAGE_ROOT / "domains"


def domain_dir(domain: str) -> Path:
    return DOMAINS_DIR / domain


def domain_tasks_dir(domain: str) -> Path:
    return domain_dir(domain) / "tasks"


def domain_task_envs_dir(domain: str) -> Path:
    return domain_dir(domain) / "task_envs"


def domain_splits_dir(domain: str) -> Path:
    return domain_dir(domain) / "splits"
