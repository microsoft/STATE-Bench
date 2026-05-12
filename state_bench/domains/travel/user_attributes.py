"""Travel-specific user attribute lookups.

AIRLINE_NAMES is used by the simulator prompt builder to convert IATA codes
to human-readable airline names.

CUSTOMER_ATTRIBUTES describes task-local user records. Runtime simulator
prompts should read user facts from the task environment.
"""

from __future__ import annotations

from typing import Any

AIRLINE_NAMES: dict[str, str] = {
    "DL": "Delta",
    "UA": "United",
    "AA": "American Airlines",
    "WN": "Southwest",
    "AS": "Alaska Airlines",
    "B6": "JetBlue",
}

CUSTOMER_ATTRIBUTES: dict[str, dict[str, Any]] = {
    "user_001": {
        "name": "Emma Smith",
        "email": "emma.smith@example.com",
        "loyalty_tier": "gold",
        "loyalty_points": 75000,
        "budget": 1500,
        "preferences": {
            "meal_preference": "kosher",
            "seat_type": "aisle",
            "add_wifi": True,
            "add_extra_legroom": True,
            "add_insurance": False,
        },
    },
    "user_002": {
        "name": "Liam Johnson",
        "email": "liam.johnson@example.com",
        "loyalty_tier": "basic",
        "loyalty_points": 5000,
        "budget": 800,
        "preferences": {
            "meal_preference": "vegetarian",
            "seat_type": "window",
            "add_wifi": False,
            "add_extra_legroom": False,
            "add_insurance": False,
        },
    },
    "user_003": {
        "name": "Olivia Williams",
        "email": "olivia.williams@example.com",
        "loyalty_tier": "platinum",
        "loyalty_points": 120000,
        "budget": 2000,
        "preferences": {
            "meal_preference": "standard",
            "seat_type": "aisle",
            "add_wifi": True,
            "add_extra_legroom": True,
            "add_insurance": True,
        },
    },
    "user_004": {
        "name": "Noah Brown",
        "email": "noah.brown@example.com",
        "loyalty_tier": "silver",
        "loyalty_points": 15000,
        "budget": 600,
        "preferences": {
            "meal_preference": "standard",
            "seat_type": "window",
            "add_wifi": False,
            "add_extra_legroom": False,
            "add_insurance": True,
        },
    },
    "user_005": {
        "name": "Ava Garcia",
        "email": "ava.garcia@example.com",
        "loyalty_tier": "basic",
        "loyalty_points": 12000,
        "budget": 700,
        "preferences": {
            "meal_preference": "vegan",
            "seat_type": "aisle",
            "add_wifi": True,
            "add_extra_legroom": False,
            "add_insurance": False,
        },
    },
}


def format_attributes_for_prompt(customer_id: str) -> str:
    """Format a customer's attributes as a human-readable string for prompts."""
    attrs = CUSTOMER_ATTRIBUTES.get(customer_id, {})
    if not attrs:
        return f"Unknown customer: {customer_id}"
    lines = [
        f"Name: {attrs['name']}",
        f"Loyalty tier: {attrs['loyalty_tier']}",
        f"Loyalty points: {attrs['loyalty_points']}",
    ]
    if attrs.get("budget"):
        lines.append(f"Budget: ${attrs['budget']}")
    prefs = attrs.get("preferences", {})
    if prefs.get("meal_preference"):
        lines.append(f"Meal: {prefs['meal_preference']}")
    if prefs.get("airline"):
        lines.append(f"Preferred airline: {AIRLINE_NAMES.get(prefs['airline'], prefs['airline'])}")
    if prefs.get("cabin_class"):
        lines.append(f"Preferred cabin: {prefs['cabin_class']}")
    return "\n".join(lines)
