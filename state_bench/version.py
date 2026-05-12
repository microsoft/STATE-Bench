"""Package version helpers."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def get_package_version() -> str:
    """Return the installed package version, falling back to local pyproject.toml."""
    try:
        return version("state-bench")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        return str(tomllib.loads(pyproject.read_text())["project"]["version"])


def get_benchmark_version() -> str:
    return f"v{get_package_version()}"
