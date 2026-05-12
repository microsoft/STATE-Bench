"""Load user-provided StateBenchAgent subclasses from repo-root agents/."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from state_bench.agents.state_bench import StateBenchAgent


def load_root_agent_class(class_name: str, *, root: Path | str | None = None) -> type[StateBenchAgent]:
    """Load a StateBenchAgent subclass by class name from ./agents/**/*.py.

    Files are imported by concrete path so an installed package named ``agents``
    cannot shadow the repository's root-level agents directory.
    """
    if not class_name.strip():
        raise ValueError("agent class name must be non-empty")

    repo_root = Path(root) if root is not None else Path.cwd()
    agents_dir = repo_root / "agents"
    if not agents_dir.is_dir():
        raise ValueError(f"No root-level agents directory found at {agents_dir}")

    matches: list[type[StateBenchAgent]] = []
    import_errors: list[str] = []
    for path in sorted(agents_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        module_name = (
            f"_state_bench_user_agent_{path.relative_to(agents_dir).with_suffix('').as_posix().replace('/', '_')}"
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
        if not isinstance(attr, type) or not issubclass(attr, StateBenchAgent) or attr is StateBenchAgent:
            raise TypeError(f"{class_name} in {path} must be a subclass of StateBenchAgent")
        matches.append(attr)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Found multiple root agents named {class_name}; class names must be unique")

    detail = ""
    if import_errors:
        detail = " Import errors: " + "; ".join(import_errors)
    raise ValueError(f"Agent class {class_name!r} not found under {agents_dir}.{detail}")
