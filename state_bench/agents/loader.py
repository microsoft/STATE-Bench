"""Load user-provided classes from repo-root extension directories."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TypeVar

from state_bench.agents.base import BaseAgent
from state_bench.client import BaseLLMClient

T = TypeVar("T")


def _load_root_class(
    class_name: str,
    *,
    root: Path | str | None,
    directory_name: str,
    base_class: type[T],
    kind: str,
) -> type[T]:
    """Load a subclass by class name from a repo-root extension directory.

    Files are imported by concrete path so an installed package named ``agents``
    or ``clients`` cannot shadow repository root extension directories.
    """
    if not class_name.strip():
        raise ValueError(f"{kind} class name must be non-empty")

    repo_root = Path(root) if root is not None else Path.cwd()
    extension_dir = repo_root / directory_name
    if not extension_dir.is_dir():
        raise ValueError(f"No root-level {directory_name} directory found at {extension_dir}")

    matches: list[type[T]] = []
    import_errors: list[str] = []
    for path in sorted(extension_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        module_name = (
            f"_state_bench_user_{kind}_{path.relative_to(extension_dir).with_suffix('').as_posix().replace('/', '_')}"
        )
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            import_errors.append(f"{path}: could not create import spec")
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # pragma: no cover - exercised by error message tests if needed
            import_errors.append(f"{path}: {type(exc).__name__}: {exc}")
            continue

        attr = getattr(module, class_name, None)
        if attr is None:
            continue
        if not isinstance(attr, type) or not issubclass(attr, base_class) or attr is base_class:
            raise TypeError(f"{class_name} in {path} must be a subclass of {base_class.__name__}")
        matches.append(attr)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Found multiple root {kind}s named {class_name}; class names must be unique")

    detail = ""
    if import_errors:
        detail = " Import errors: " + "; ".join(import_errors)
    raise ValueError(f"{kind.title()} class {class_name!r} not found under {extension_dir}.{detail}")


def load_root_agent_class(class_name: str, *, root: Path | str | None = None) -> type[BaseAgent]:
    """Load a BaseAgent subclass by class name from ./agents/**/*.py."""
    return _load_root_class(
        class_name,
        root=root,
        directory_name="agents",
        base_class=BaseAgent,
        kind="agent",
    )


def load_root_client_class(class_name: str, *, root: Path | str | None = None) -> type[BaseLLMClient]:
    """Load a BaseLLMClient subclass by class name from ./clients/**/*.py."""
    return _load_root_class(
        class_name,
        root=root,
        directory_name="clients",
        base_class=BaseLLMClient,
        kind="client",
    )
