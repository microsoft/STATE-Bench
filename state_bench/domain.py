"""Domain configuration abstraction.

Each benchmark domain (travel, customer_support, etc.) provides a DomainConfig
that encapsulates all domain-specific behavior: environment, tools, prompts,
metric judges, and termination logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from state_bench.environment import BaseEnvironment


@dataclass
class DomainConfig:
    """Configuration for a benchmark domain.

    The orchestrator uses this to run tasks without any domain-specific imports.
    """

    name: str  # "travel", "customer_support", etc.
    environment_class: type[BaseEnvironment]  # e.g. TravelEnvironment
    env_data_class: type  # e.g. EnvironmentData — must have .load(path) and .deep_copy()
    tool_schemas: list[dict[str, Any]]
    agent_system_prompt: str  # prompt template with runtime fields
    build_simulator_prompt: Callable[..., str]  # (task, env_data, user_id) -> str
    prompts_dir: Path  # directory containing task-requirements and UX judge prompts
    judge_system_prompt: str  # system prompt for shared metric judges
    max_agent_turns: int = 15
    check_termination: Callable[[str], bool] | None = None  # (user_response) -> bool
    write_tool_names: list[str] = field(default_factory=list)


def get_domain_config(name: str) -> DomainConfig:
    """Factory — lazy-imports domain config to avoid circular imports."""
    if name == "travel":
        from state_bench.domains.travel.config import get_config

        return get_config()
    if name == "customer_support":
        from state_bench.domains.customer_support.config import get_config

        return get_config()
    if name == "shopping_assistant":
        from state_bench.domains.shopping_assistant.config import get_config

        return get_config()
    raise ValueError(f"Unknown domain: {name!r}. Available: travel, customer_support, shopping_assistant")
