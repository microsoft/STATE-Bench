"""Shopping assistant domain configuration."""

from __future__ import annotations

from pathlib import Path

from state_bench.domain import DomainConfig

AGENT_SYSTEM_PROMPT = (
    "You are a shopping assistant for an online store. Today's date: {now}. "
    "You are currently helping customer {user_id}. "
    "Use the available tools to help the customer find products, compare options, "
    "manage their cart, and apply promotions."
)

JUDGE_SYSTEM_PROMPT = "You are an objective evaluator of shopping assistant agent correctness. Return JSON only."

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _check_termination(user_response: str) -> bool:
    return "[TASK_DONE]" in user_response


def get_config() -> DomainConfig:
    """Build DomainConfig for the shopping assistant domain."""
    from state_bench.domains.shopping_assistant.environment import ShoppingAssistantEnvironment
    from state_bench.domains.shopping_assistant.schemas import SAEnvironmentData
    from state_bench.domains.shopping_assistant.simulator import build_simulator_prompt
    from state_bench.domains.shopping_assistant.tools import TOOL_SCHEMAS, WRITE_TOOL_NAMES

    return DomainConfig(
        name="shopping_assistant",
        environment_class=ShoppingAssistantEnvironment,
        env_data_class=SAEnvironmentData,
        tool_schemas=TOOL_SCHEMAS,
        agent_system_prompt=AGENT_SYSTEM_PROMPT,
        build_simulator_prompt=build_simulator_prompt,
        prompts_dir=PROMPTS_DIR,
        judge_system_prompt=JUDGE_SYSTEM_PROMPT,
        max_agent_turns=15,
        check_termination=_check_termination,
        write_tool_names=WRITE_TOOL_NAMES,
    )
