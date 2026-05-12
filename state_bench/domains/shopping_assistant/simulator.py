"""Shopping assistant domain user simulator prompt builder."""

from __future__ import annotations

from pathlib import Path

from state_bench.domains.shopping_assistant.schemas import SAEnvironmentData
from state_bench.domains.shopping_assistant.user_attributes import TIER_LABELS
from state_bench.schemas import TaskDefinition

_BASE_RULES_PATH = Path(__file__).resolve().parent / "prompts" / "user_sim_base.md"


def build_simulator_prompt(
    task: TaskDefinition,
    env_data: SAEnvironmentData,
    user_id: str,
) -> str:
    """Assemble the full simulator prompt for a shopping assistant task.

    Order:
    1. Preamble (role + precedence note)
    2. Identity (name, personality, tier, first-time, loyalty points, purchase history)
    3. Task Context (from user_sim_context — sim-safe framing)
    4. Base Rules (static behavioral rules from user_sim_base.md)
    5. Task-Specific Rules (override base rules if conflicting)
    """
    customer = next((candidate for candidate in env_data.customers if candidate.customer_id == user_id), None)
    if customer is None:
        raise ValueError(f"Task env does not contain customer {user_id!r}")

    sim = task.user_simulator

    sections: list[str] = [
        "You are a simulated customer browsing an online store with a shopping assistant. "
        "Your opening message has already been sent. Respond naturally based on the identity, context, and rules below.\n\n"
        "**Important:** Task-specific rules take precedence over base rules if there is a conflict."
    ]

    # --- Identity ---
    name = customer.name
    tier = customer.tier
    tier_label = TIER_LABELS.get(tier, tier)
    is_first_time = customer.is_first_time
    loyalty_points = customer.loyalty_points
    purchase_history = customer.purchase_history or []

    identity_lines: list[str] = [
        "## Identity\n",
        f"You are **{name}**.",
        f"- Personality: {sim.personality}",
        f"- Membership tier: {tier_label}",
        f"- First-time customer: {'yes' if is_first_time else 'no'}",
        f"- Loyalty points: {loyalty_points}",
    ]
    if purchase_history:
        identity_lines.append(f"- Past purchases: {', '.join(purchase_history)}")

    # What you know
    know_items = [
        f"Your name is {name}",
        f"Your customer ID is {user_id}",
        f"Your membership tier is {tier_label}",
    ]
    if sim.known_info:
        know_items.extend(sim.known_info)
    identity_lines.append("\n### What you know")
    for item in know_items:
        identity_lines.append(f"- {item}")
    identity_lines.append("\nIf the agent states any of these incorrectly, correct them.")

    # What you don't know
    if sim.unknown_info:
        identity_lines.append("\n### What you don't know")
        for item in sim.unknown_info:
            identity_lines.append(f"- {item}")

    sections.append("\n".join(identity_lines))

    # --- Task Context (sim-safe framing only) ---
    if sim.user_sim_context:
        sections.append(f"## Task Context\n\n{sim.user_sim_context}")

    # --- Base Rules ---
    sections.append(_BASE_RULES_PATH.read_text())

    # --- Task-Specific Rules ---
    if sim.task_rules:
        rule_lines = ["## Task-Specific Rules\n"]
        for i, rule in enumerate(sim.task_rules, 1):
            rule_lines.append(f"{i}. {rule}")
        sections.append("\n".join(rule_lines))

    return "\n\n---\n\n".join(sections)
