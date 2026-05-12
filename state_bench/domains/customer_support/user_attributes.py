"""Customer profiles for the customer support benchmark.

Five customers with distinct membership tiers and preferences that affect
policy outcomes (return windows, fee waivers, compensation multipliers).
These profiles describe task-local customer records. Runtime simulator
prompts should read customer facts from the task environment.
"""

from __future__ import annotations

CUSTOMER_ATTRIBUTES: dict[str, dict] = {
    "cust_001": {
        # "Platinum Power User" — high-value, extended windows, fee waivers
        "name": "Emma Chen",
        "email": "emma.chen@example.com",
        "membership_tier": "platinum",
        "preferred_refund_method": "original_payment",
        "has_prime_shipping": True,
        "store_credit_balance": 150,
        "total_orders": 87,
        "account_created": "2020-03-15",
    },
    "cust_002": {
        # "Budget Basic" — standard tier, accepts store credit
        "name": "Marcus Johnson",
        "email": "marcus.j@example.com",
        "membership_tier": "standard",
        "preferred_refund_method": "store_credit",
        "has_prime_shipping": False,
        "store_credit_balance": 0,
        "total_orders": 12,
        "account_created": "2024-06-01",
    },
    "cust_003": {
        # "Gold Gift-Giver" — frequently buys gifts, 1.5x compensation
        "name": "Sarah Williams",
        "email": "sarah.w@example.com",
        "membership_tier": "gold",
        "preferred_refund_method": "original_payment",
        "has_prime_shipping": True,
        "store_credit_balance": 45,
        "total_orders": 53,
        "account_created": "2021-11-20",
    },
    "cust_004": {
        # "Silver Tech Buyer" — electronics-focused, warranty-conscious
        "name": "David Kim",
        "email": "david.kim@example.com",
        "membership_tier": "silver",
        "preferred_refund_method": "original_payment",
        "has_prime_shipping": False,
        "store_credit_balance": 25,
        "total_orders": 31,
        "account_created": "2022-08-10",
    },
    "cust_005": {
        # "New Standard" — new customer, few orders
        "name": "Priya Patel",
        "email": "priya.p@example.com",
        "membership_tier": "standard",
        "preferred_refund_method": "store_credit",
        "has_prime_shipping": False,
        "store_credit_balance": 0,
        "total_orders": 4,
        "account_created": "2025-12-01",
    },
}


TIER_LABELS: dict[str, str] = {
    "standard": "Standard",
    "silver": "Silver",
    "gold": "Gold",
    "platinum": "Platinum",
}


def format_attributes_for_prompt(customer_id: str) -> str:
    """Format customer attributes as human-readable text for the user simulator prompt."""
    attrs = CUSTOMER_ATTRIBUTES.get(customer_id)
    if not attrs:
        return f"Unknown customer: {customer_id}"

    lines = [
        f"Name: {attrs['name']}",
        f"Membership: {TIER_LABELS.get(attrs['membership_tier'], attrs['membership_tier'])}",
        f"Prime Shipping: {'Yes' if attrs['has_prime_shipping'] else 'No'}",
        f"Store Credit Balance: ${attrs['store_credit_balance']}",
        f"Previous Orders: {attrs['total_orders']}",
    ]
    return "\n".join(lines)
