"""BaseAgent discovery utilities."""

from __future__ import annotations

import importlib
import pkgutil

from state_bench.agents.base import BaseAgent


def discover_agents() -> dict[str, type[BaseAgent]]:
    """Return checked-in BaseAgent subclasses."""
    found: dict[str, type[BaseAgent]] = {}
    package_path = __path__
    package_name = __name__

    for _, module_name, _ in pkgutil.iter_modules(package_path):
        module = importlib.import_module(f"{package_name}.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr is not BaseAgent:
                found[attr_name] = attr

    return found


def get_agent_class(name: str) -> type[BaseAgent]:
    """Get an agent class by name. Raises ValueError if not found."""
    agents = discover_agents()
    if name not in agents:
        available = ", ".join(sorted(agents.keys())) or "(none)"
        raise ValueError(f"BaseAgent '{name}' not found. Available: {available}")
    return agents[name]


def list_agents() -> list[str]:
    """List all available agent class names."""
    return sorted(discover_agents().keys())
