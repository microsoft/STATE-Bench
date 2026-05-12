"""Customer support domain configuration."""

from __future__ import annotations

from pathlib import Path

from state_bench.domain import DomainConfig

AGENT_SYSTEM_PROMPT = (
    "You are a customer service agent for an e-commerce company. Today's date: {now}. "
    "You are currently helping customer {user_id}. "
    "Use the available system tools to inspect orders, products, customers, policies, "
    "and warranties so you can help the customer with their current issue. "
    "Keep customer-facing replies natural and direct, usually 1-4 sentences unless the "
    "answer genuinely needs more detail. "
    "Do not reveal tool names or available policy categories to the customer; "
    "use them only to decide what customer-facing help to provide. You may say you checked the policy when you did."
)

JUDGE_SYSTEM_PROMPT = "You are an objective benchmark evaluator. Score task completion and user experience using the provided rubric. Return JSON only."

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _check_termination(user_response: str) -> bool:
    return "[TASK_DONE]" in user_response


def get_config() -> DomainConfig:
    """Build DomainConfig for the customer support domain."""
    from state_bench.domains.customer_support.environment import CustomerSupportEnvironment
    from state_bench.domains.customer_support.schemas import CSEnvironmentData
    from state_bench.domains.customer_support.simulator import build_simulator_prompt
    from state_bench.domains.customer_support.tools import TOOL_SCHEMAS, WRITE_TOOL_NAMES

    return DomainConfig(
        name="customer_support",
        environment_class=CustomerSupportEnvironment,
        env_data_class=CSEnvironmentData,
        tool_schemas=TOOL_SCHEMAS,
        agent_system_prompt=AGENT_SYSTEM_PROMPT,
        build_simulator_prompt=build_simulator_prompt,
        prompts_dir=PROMPTS_DIR,
        judge_system_prompt=JUDGE_SYSTEM_PROMPT,
        max_agent_turns=15,
        check_termination=_check_termination,
        write_tool_names=WRITE_TOOL_NAMES,
    )
