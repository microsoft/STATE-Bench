"""Customer support domain user simulator prompt builder."""

from __future__ import annotations

from pathlib import Path

from state_bench.domains.customer_support.schemas import CSEnvironmentData
from state_bench.schemas import TaskDefinition

_BASE_RULES_PATH = Path(__file__).resolve().parent / "prompts" / "user_sim_base.md"


def build_simulator_prompt(
    task: TaskDefinition,
    env_data: CSEnvironmentData,
    user_id: str,
) -> str:
    """Build the user simulator prompt for a customer support task."""
    sim = task.user_simulator

    sections: list[str] = [
        "You are a simulated customer contacting an e-commerce support agent. "
        "Your opening message has already been sent. Respond naturally based on the identity, context, and rules below.\n\n"
        "**Important:** Task-specific rules take precedence over base rules if there is a conflict."
    ]

    # Identity
    customer = next((candidate for candidate in env_data.customers if candidate.customer_id == user_id), None)
    if customer is None:
        raise ValueError(f"Task env does not contain customer {user_id!r}")

    identity_lines = [
        "## Identity\n",
        f"You are **{customer.name}**.",
        f"- Personality: {sim.personality}",
        f"- Membership tier: {customer.membership_tier}",
        f"- Customer ID: {customer.customer_id}",
    ]

    if sim.known_info:
        identity_lines.append("\n### What you know")
        for item in sim.known_info:
            identity_lines.append(f"- {item}")

    if sim.unknown_info:
        identity_lines.append("\n### What you don't know")
        for item in sim.unknown_info:
            identity_lines.append(f"- {item}")

    sections.append("\n".join(identity_lines))

    # Task context
    sections.append(f"## Task Context\n\n{sim.user_sim_context}")

    # Base rules (loaded from file)
    sections.append(_BASE_RULES_PATH.read_text())

    # Task-specific rules
    if sim.task_rules:
        rule_lines = ["## Task-Specific Rules\n"]
        for i, rule in enumerate(sim.task_rules, 1):
            rule_lines.append(f"{i}. {rule}")
        sections.append("\n".join(rule_lines))

    return "\n\n---\n\n".join(sections)
