"""Travel domain user simulator prompt builder.

Assembles the simulator prompt from task definition and user profile.
This is travel-specific: it references airline preferences, cabin classes,
loyalty tiers, hotel/car rental neutrality, etc.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from state_bench.domains.travel.schemas import EnvironmentData
from state_bench.domains.travel.user_attributes import AIRLINE_NAMES
from state_bench.schemas import TaskDefinition

_BASE_RULES_PATH = Path(__file__).resolve().parent / "prompts" / "user_sim_base.md"


def build_simulator_prompt(
    task: TaskDefinition,
    env_data: EnvironmentData,
    user_id: str,
) -> str:
    """Assemble the simulator prompt from structured UserSimulatorConfig.

    Order:
    1. Preamble (role + precedence note)
    2. Identity (name, personality, tier, points, constraints, preferences)
    3. Task Context (user_sim_context + known_info + unknown_info)
    4. Base Rules (shared canonical rules from user_sim_base.md)
    5. Task-Specific Rules
    """
    user = next((candidate for candidate in env_data.users if candidate.user_id == user_id), None)
    if user is None:
        raise ValueError(f"Task env does not contain user {user_id!r}")

    sim = task.user_simulator

    # --- 0. Preamble ---
    sections: list[str] = [
        "You are a simulated customer in a conversation with a travel agent. "
        "Your opening message has already been sent. Respond naturally based on the identity, context, and rules below.\n\n"
        "**Important:** Task-specific rules take precedence over base rules if there is a conflict."
    ]

    # --- 1. Identity (who you are + personality) ---
    name = user.name
    loyalty_tier = user.loyalty_tier
    loyalty_points = user.loyalty_points
    budget = user.budget
    preferences = user.preferences

    placeholders: dict[str, Any] = {
        "user_name": name,
        "loyalty_tier": loyalty_tier,
        "loyalty_points": str(loyalty_points),
        "budget": f"${budget}",
    }
    for key, value in preferences.items():
        if key == "airline" and value:
            placeholders[key] = AIRLINE_NAMES.get(value, value)
        elif isinstance(value, bool):
            placeholders[key] = "yes" if value else "no"
        elif key == "max_stops":
            placeholders[key] = "nonstop" if value == 0 else f"up to {value} stop(s)"
        else:
            placeholders[key] = str(value) if value else "no preference"

    identity_lines = [
        "## Identity\n",
        f"You are **{name}**.",
        f"- Personality: {sim.personality}",
        f"- Loyalty tier: {loyalty_tier}",
        f"- Loyalty points: {loyalty_points}",
        "\n### Budget",
        f"- {placeholders.get('budget', 'none')} — you will NOT accept anything above this amount",
        "\n### Preferences",
        f"- Meal: {placeholders.get('meal_preference', 'no preference')}",
        f"- Seat: {placeholders.get('seat_type', 'no preference')}",
        f"- WiFi: {placeholders.get('add_wifi', 'no')}",
        f"- Extra legroom: {placeholders.get('add_extra_legroom', 'no')}",
        f"- Insurance: {placeholders.get('add_insurance', 'no')}",
        "\nTask-specific search preferences such as airline, cabin class, departure time, and max stops are provided in the task context below, not as fixed cross-task identity defaults.",
        "\nYou do not have specific preferences for hotel room type, car rental class, or rental company. "
        "If asked, say you have no preference and let the agent decide. Your budget still applies to these state_bench.domains.",
    ]

    # What you know (includes identity facts + task-specific known info)
    know_items = [
        f"Your name is {name}",
        f"Your loyalty tier is {loyalty_tier}",
        f"Your loyalty points balance is {loyalty_points}",
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

    # --- 2. Task Context ---
    sections.append(f"## Task Context\n\n{sim.user_sim_context}")

    # --- 3. Base Rules (shared canonical rules) ---
    sections.append(_BASE_RULES_PATH.read_text())

    # --- 4. Task-Specific Rules ---
    if sim.task_rules:
        rule_lines = ["## Task-Specific Rules\n"]
        for i, rule in enumerate(sim.task_rules, 1):
            rule_lines.append(f"{i}. {rule}")
        sections.append("\n".join(rule_lines))

    return "\n\n---\n\n".join(sections)
