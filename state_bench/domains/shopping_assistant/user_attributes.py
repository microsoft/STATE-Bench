"""Shopping-specific user attribute lookups.

CUSTOMER_ATTRIBUTES describes task-local shopper records. Runtime simulator
prompts should read customer facts from the task environment.

Only identity + status fields are carried here. Preferences are NOT
pre-populated on the customer profile — they are introduced per-task
when a matching tool argument + state assertion exist to test elicitation.
Purchase history is likewise populated only when a task needs it.
"""

from __future__ import annotations

from typing import Any

CUSTOMER_ATTRIBUTES: dict[str, dict[str, Any]] = {
    "shop_001": {
        "name": "Alex Rivera",
        "email": "alex.rivera@example.com",
        "tier": "platinum",
        "is_first_time": False,
        "loyalty_points": 52000,
        "purchase_history": [],
    },
    "shop_002": {
        "name": "Jordan Lee",
        "email": "jordan.lee@example.com",
        "tier": "standard",
        "is_first_time": True,
        "loyalty_points": 0,
        "purchase_history": [],
    },
    "shop_003": {
        "name": "Sam Chen",
        "email": "sam.chen@example.com",
        "tier": "gold",
        "is_first_time": False,
        "loyalty_points": 18500,
        "purchase_history": [],
    },
    "shop_004": {
        "name": "Taylor Kim",
        "email": "taylor.kim@example.com",
        "tier": "standard",
        "is_first_time": False,
        "loyalty_points": 2200,
        "purchase_history": [],
    },
    "shop_005": {
        "name": "Morgan Patel",
        "email": "morgan.patel@example.com",
        "tier": "platinum",
        "is_first_time": False,
        "loyalty_points": 104000,
        "purchase_history": [],
    },
    "shop_006": {
        "name": "Riley Cooper",
        "email": "riley.cooper@example.com",
        "tier": "standard",
        "is_first_time": True,
        "loyalty_points": 20000,
        "purchase_history": [],
    },
}


TIER_LABELS: dict[str, str] = {
    "standard": "Standard",
    "gold": "Gold",
    "platinum": "Platinum",
}
