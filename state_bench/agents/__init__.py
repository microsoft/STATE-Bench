"""Agent discovery utilities."""

from __future__ import annotations

import importlib
import pkgutil

from state_bench.agents.base import Agent


def discover_agents() -> dict[str, type[Agent]]:
    """Return checked-in Agent subclasses."""
    found: dict[str, type[Agent]] = {}
    package_path = __path__
    package_name = __name__

    for _, module_name, _ in pkgutil.iter_modules(package_path):
        module = importlib.import_module(f"{package_name}.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Agent) and attr is not Agent:
                found[attr_name] = attr

    return found


def get_agent_class(name: str) -> type[Agent]:
    """Get an agent class by name. Raises ValueError if not found."""
    agents = discover_agents()
    if name not in agents:
        available = ", ".join(sorted(agents.keys())) or "(none)"
        raise ValueError(f"Agent '{name}' not found. Available: {available}")
    return agents[name]


def list_agents() -> list[str]:
    """List all available agent class names."""
    return sorted(discover_agents().keys())
