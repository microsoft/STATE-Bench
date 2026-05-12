"""Base class for domain environments.

All domain environments (travel, customer_support, shopping_assistant) inherit
from BaseEnvironment and implement the required interface: tool_handlers and
get_full_snapshot().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class BaseEnvironment(ABC):
    """Abstract base for domain environments.

    Subclasses must implement:
    - tool_handlers: property mapping tool names to handler methods
    - get_full_snapshot(): returns full environment state for state diffing
    """

    def __init__(self, env_data: Any, now: str):
        self.now = now

    @property
    @abstractmethod
    def tool_handlers(self) -> dict[str, Callable]:
        """Map of tool name -> handler function."""
        ...

    @abstractmethod
    def get_full_snapshot(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Return full environment state indexed by entity type and ID.

        Used by the orchestrator to compute state diffs (before vs after).
        """
        ...

    @staticmethod
    def parse_bool(value: Any) -> bool | None:
        """Parse a value to bool, handling strings like 'true'/'false'."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)
