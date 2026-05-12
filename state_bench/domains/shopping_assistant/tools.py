"""Tool schemas (OpenAI function calling format) for the shopping assistant environment.

13 tools: 8 READ, 5 WRITE.
"""

from typing import Any

from state_bench.domains.shopping_assistant.policies import VALID_POLICY_TOPICS

# ---------------------------------------------------------------------------
# READ tools
# ---------------------------------------------------------------------------

SEARCH_PRODUCTS: dict[str, Any] = {
    "type": "function",
    "name": "search_products",
    "description": (
        "Search the product catalog. Returns up to 10 ranked products. "
        "Hard filters (category, price range, rating, in_stock_only) narrow the candidate pool; "
        "products failing a hard filter are excluded. "
        "`query` soft-ranks the survivors by matching against product name, brand, subcategory, "
        "description, and spec keys/values. If you supply a query and nothing matches, the response "
        "returns no products with a note — try broader keywords or relax filters. "
        "There is no curated recommendation shortcut; the agent must reason from catalog fields."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Short keyword phrase matched against product name, brand, subcategory, "
                    "description, and spec keys/values. Use 1-4 broad keywords (e.g., 'wireless headphones', "
                    "'ergonomic desk')."
                ),
            },
            "category": {
                "type": "string",
                "enum": ["electronics", "kitchen", "clothing", "accessories", "home_office", "outdoor"],
                "description": "Hard filter: only products in this category.",
            },
            "min_price": {"type": "integer", "description": "Hard filter: minimum price in dollars."},
            "max_price": {"type": "integer", "description": "Hard filter: maximum price in dollars."},
            "min_rating": {"type": "number", "description": "Hard filter: minimum rating (1.0-5.0)."},
            "in_stock_only": {"type": "boolean", "description": "Hard filter: only show in-stock products."},
            "sort_by": {
                "type": "string",
                "enum": ["price_low", "price_high", "rating", "review_count", "relevance"],
                "description": "Result ordering. Defaults to 'relevance'.",
            },
        },
        "required": [],
    },
}

GET_PRODUCT_DETAILS: dict[str, Any] = {
    "type": "function",
    "name": "get_product_details",
    "description": (
        "Get full details of a product including specs, description, stock, shipping days, "
        "gift_wrap_available, compatible_with list, any recent price drop, and any variants."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "The product ID (e.g. 'SP-1001')."},
        },
        "required": ["product_id"],
    },
}

GET_VARIANTS: dict[str, Any] = {
    "type": "function",
    "name": "get_variants",
    "description": (
        "List the variants (e.g. color, size) available for a product along with per-variant stock "
        "and effective price. Returns an empty list for products without variants. When a product has "
        "variants, add_to_cart REQUIRES a variant_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "The product ID to query."},
        },
        "required": ["product_id"],
    },
}

GET_CUSTOMER_ACCOUNT: dict[str, Any] = {
    "type": "function",
    "name": "get_customer_account",
    "description": (
        "Get a customer's account record: name, email, tier, first-time status, "
        "loyalty points, and purchase_history. No stored preferences — the agent "
        "must ask the customer about per-purchase decisions (e.g., gift wrap, "
        "shipping speed, brand preference) before acting."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID (e.g. 'shop_001')."},
        },
        "required": ["customer_id"],
    },
}

GET_CART: dict[str, Any] = {
    "type": "function",
    "name": "get_cart",
    "description": (
        "Get the customer's current cart: items with live pricing, subtotal, discount, "
        "gift-wrap fee, total, and applied promo codes. Does not compute promo eligibility — "
        "use get_promotions and get_customer_account to reason about which promos apply."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
        },
        "required": ["customer_id"],
    },
}

CHECK_COMPATIBILITY: dict[str, Any] = {
    "type": "function",
    "name": "check_compatibility",
    "description": (
        "Check whether a product is compatible with a specific device. "
        "Device names must match the canonical vocabulary exactly. "
        "If the device name is not recognized, the response includes the full list of canonical device names."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "The product to check."},
            "device_name": {
                "type": "string",
                "description": "Canonical device model name (e.g. 'TechPhone Pro 16', 'ProBook Laptop 15-inch').",
            },
        },
        "required": ["product_id", "device_name"],
    },
}

GET_PROMOTIONS: dict[str, Any] = {
    "type": "function",
    "name": "get_promotions",
    "description": (
        "List currently active, non-expired promotions. Optional category filter "
        "restricts to promos applicable to that category."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["electronics", "kitchen", "clothing", "accessories", "home_office", "outdoor"],
                "description": "Filter promotions by category.",
            },
        },
        "required": [],
    },
}

GET_POLICIES: dict[str, Any] = {
    "type": "function",
    "name": "get_policies",
    "description": (
        "Look up the store's policy for a given topic. Returns a summary and a list of rules. "
        "Use this when the customer's question or the scenario requires citing store policy "
        "(discounts, returns, gift wrap, quantity limit, backorder, stacking, shipping, price match, etc.)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "enum": VALID_POLICY_TOPICS,
                "description": "The policy topic to look up.",
            },
        },
        "required": ["topic"],
    },
}

# ---------------------------------------------------------------------------
# WRITE tools
# ---------------------------------------------------------------------------

ADD_TO_CART: dict[str, Any] = {
    "type": "function",
    "name": "add_to_cart",
    "description": (
        "Add a product to the customer's cart. Creates a new cart item or increments an existing one. "
        "Enforces stock availability and the per-product quantity limit."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
            "product_id": {"type": "string", "description": "The product to add."},
            "quantity": {"type": "integer", "description": "Units to add. Default: 1."},
            "gift_wrap": {
                "type": "boolean",
                "description": "Wrap this item (adds $5/unit to the gift-wrap fee). Default: false.",
            },
            "variant_id": {
                "type": "string",
                "description": "Variant selector, when applicable.",
            },
        },
        "required": ["customer_id", "product_id"],
    },
}

UPDATE_CART_ITEM: dict[str, Any] = {
    "type": "function",
    "name": "update_cart_item",
    "description": (
        "Update an existing cart item's quantity or gift-wrap flag. Setting quantity=0 removes the item from the cart."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
            "product_id": {"type": "string", "description": "The product already in the cart."},
            "variant_id": {
                "type": "string",
                "description": "Variant selector. Required when multiple variants of this product are in the cart.",
            },
            "quantity": {"type": "integer", "description": "New total quantity (0 removes the item)."},
            "gift_wrap": {"type": "boolean", "description": "New gift-wrap flag."},
        },
        "required": ["customer_id", "product_id"],
    },
}

REMOVE_FROM_CART: dict[str, Any] = {
    "type": "function",
    "name": "remove_from_cart",
    "description": "Remove a product from the customer's cart entirely.",
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
            "product_id": {"type": "string", "description": "The product to remove."},
            "variant_id": {
                "type": "string",
                "description": "Variant selector. Required when multiple variants of this product are in the cart.",
            },
        },
        "required": ["customer_id", "product_id"],
    },
}

APPLY_PROMO: dict[str, Any] = {
    "type": "function",
    "name": "apply_promo",
    "description": (
        "Apply a promo code to the cart. Validates the code against cart subtotal, category restriction, "
        "and expiry (intrinsic validity only — does NOT check customer-fit rules like first-time-only; "
        "that's the agent's responsibility via get_customer_account). One promo code can be applied per "
        "cart. Applying the same code twice is a no-op; applying a different code requires removing the "
        "existing promo code first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
            "promo_code": {"type": "string", "description": "The promotional code to apply."},
        },
        "required": ["customer_id", "promo_code"],
    },
}

REMOVE_PROMO: dict[str, Any] = {
    "type": "function",
    "name": "remove_promo",
    "description": (
        "Remove a previously applied promo code from the cart. Recomputes cart totals without it. "
        "Returns an error if the code is not currently applied."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
            "promo_code": {"type": "string", "description": "The promo code to remove."},
        },
        "required": ["customer_id", "promo_code"],
    },
}

REDEEM_LOYALTY_POINTS: dict[str, Any] = {
    "type": "function",
    "name": "redeem_loyalty_points",
    "description": (
        "Redeem the customer's loyalty points for a dollar discount on the current cart. "
        "Rules: 100 points = $1. Minimum redemption 500 points. Capped at 50% of cart total. "
        "Stacks with promo codes but NOT with the first-time welcome discount. Points are "
        "debited from the customer's balance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
            "points": {"type": "integer", "description": "How many points to redeem (multiples of 100 recommended)."},
        },
        "required": ["customer_id", "points"],
    },
}

CANCEL_LOYALTY_REDEMPTION: dict[str, Any] = {
    "type": "function",
    "name": "cancel_loyalty_redemption",
    "description": ("Cancel a prior redemption on the current cart, crediting points back to the customer's balance."),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
        },
        "required": ["customer_id"],
    },
}

GET_SHIPPING_OPTIONS: dict[str, Any] = {
    "type": "function",
    "name": "get_shipping_options",
    "description": (
        "List shipping options available for the customer's cart. Use ONLY when the customer "
        "explicitly asks about shipping (speed, cost, deadline, delivery time) or when resolving "
        "a dated-delivery need. Returns each option's cost, ETA, and tier-eligibility note. "
        "Do NOT call proactively as part of a standard checkout."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
        },
        "required": ["customer_id"],
    },
}

SET_SHIPPING_OPTION: dict[str, Any] = {
    "type": "function",
    "name": "set_shipping_option",
    "description": (
        "Write a shipping option to the cart. Adds shipping_cost to cart.total. "
        "Calling again overwrites the prior value."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
            "option": {
                "type": "string",
                "enum": ["standard", "express", "next_day"],
                "description": "Shipping speed to apply.",
            },
        },
        "required": ["customer_id", "option"],
    },
}

VALIDATE_PROMO: dict[str, Any] = {
    "type": "function",
    "name": "validate_promo",
    "description": (
        "Check whether a promo code would validate against the customer's current cart. Returns "
        "{valid, reason, estimated_discount}. Checks intrinsic validity only (exists, active, not "
        "expired, category restriction, min_purchase) — NOT customer-fit rules like first-time-only. "
        "The agent is responsible for customer-fit reasoning via get_customer_account. This is a "
        "pure read: does not mutate cart state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID."},
            "promo_code": {"type": "string", "description": "The promotional code to validate."},
        },
        "required": ["customer_id", "promo_code"],
    },
}

# ---------------------------------------------------------------------------
# Aggregated
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    SEARCH_PRODUCTS,
    GET_PRODUCT_DETAILS,
    GET_VARIANTS,
    GET_CUSTOMER_ACCOUNT,
    GET_CART,
    CHECK_COMPATIBILITY,
    GET_PROMOTIONS,
    GET_POLICIES,
    VALIDATE_PROMO,
    ADD_TO_CART,
    UPDATE_CART_ITEM,
    REMOVE_FROM_CART,
    APPLY_PROMO,
    REMOVE_PROMO,
    REDEEM_LOYALTY_POINTS,
    CANCEL_LOYALTY_REDEMPTION,
    GET_SHIPPING_OPTIONS,
    SET_SHIPPING_OPTION,
]

WRITE_TOOL_NAMES: list[str] = [
    "add_to_cart",
    "update_cart_item",
    "remove_from_cart",
    "apply_promo",
    "remove_promo",
    "redeem_loyalty_points",
    "cancel_loyalty_redemption",
    "set_shipping_option",
]
