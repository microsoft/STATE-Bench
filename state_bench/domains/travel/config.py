"""Travel domain configuration.

Wires up all travel-specific components into a DomainConfig that the
orchestrator can use without knowing anything about travel internals.
"""

from __future__ import annotations

from pathlib import Path

from state_bench.domain import DomainConfig

AGENT_SYSTEM_PROMPT = (
    "You are a customer service agent for a travel company. Today's date: {now}. "
    "You are currently helping customer {user_id}. "
    "Use the available tools to help the customer."
)

JUDGE_SYSTEM_PROMPT = "You are an objective benchmark evaluator. Score task completion and user experience using the provided rubric. Return JSON only."

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _check_termination(user_response: str) -> bool:
    return "[TASK_DONE]" in user_response


def get_config() -> DomainConfig:
    """Build DomainConfig for the travel domain."""
    from state_bench.domains.travel.environment import TravelEnvironment
    from state_bench.domains.travel.schemas import EnvironmentData
    from state_bench.domains.travel.simulator import build_simulator_prompt
    from state_bench.domains.travel.tools import TOOL_SCHEMAS, WRITE_TOOL_NAMES

    return DomainConfig(
        name="travel",
        environment_class=TravelEnvironment,
        env_data_class=EnvironmentData,
        tool_schemas=TOOL_SCHEMAS,
        agent_system_prompt=AGENT_SYSTEM_PROMPT,
        build_simulator_prompt=build_simulator_prompt,
        prompts_dir=PROMPTS_DIR,
        judge_system_prompt=JUDGE_SYSTEM_PROMPT,
        max_agent_turns=15,
        check_termination=_check_termination,
        write_tool_names=WRITE_TOOL_NAMES,
    )
