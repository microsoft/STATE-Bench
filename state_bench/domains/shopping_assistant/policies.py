"""Deterministic policy engine for the shopping assistant domain.

All functions are pure — no randomness, no side effects, no calls to
`datetime.now()` (all time comparisons use an explicit `now` parameter
passed from the environment).

Two kinds of artifacts live here:
1. Pure functions that back write-tool behavior (validate_promo, check_stock,
   check_quantity_limit, compute_gift_wrap_fee, etc.).
2. `POLICY_TEXTS` — a canonical dict of human-readable policy statements.
   `get_policies(topic)` returns these verbatim. Whether the agent verbalizes
   them to the customer is LLM-judged via `task_requirements` — there is no
   process gate that tracks which topics have been fetched.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

GIFT_WRAP_FEE_PER_ITEM: int = 5

QUANTITY_LIMIT: int = 3  # per-product cap per cart

LOYALTY_POINTS_RATE: dict[str, int] = {
    "platinum": 3,
    "gold": 2,
    "standard": 1,
}

BRAND_BUNDLE_PCT: float = 0.03  # 3% off same-brand 2+ items
CATEGORY_BUNDLE_PCT: float = 0.05  # 5% off same-category 3+ items
WELCOME_DISCOUNT_PCT: float = 0.05  # 5% off first order
BACKORDER_DEPOSIT_PCT: float = 0.10  # 10% deposit to backorder
MAX_PROMO_CODES_PER_CART: int = 1


# ---------------------------------------------------------------------------
# Promo validation (used by apply_promo)
# ---------------------------------------------------------------------------


def check_promo_stack(existing_codes: list[str], promo_code: str) -> dict[str, Any]:
    """Enforce the one-promo-code-per-cart rule for apply_promo."""
    if promo_code in existing_codes or len(existing_codes) < MAX_PROMO_CODES_PER_CART:
        return {"valid": True}

    existing = existing_codes[0]
    return {
        "valid": False,
        "reason": (
            "Only one promo code can be applied per cart. "
            f"Remove existing promo code {existing} before applying {promo_code}."
        ),
    }


def validate_promo(
    promo_code: str,
    promo: dict[str, Any] | None,
    cart_subtotal: int,
    cart_categories: list[str],
    now: str,
) -> dict[str, Any]:
    """Validate a promo code against current cart state.

    Rules applied in order:
    - Promo must exist.
    - Promo must be active.
    - Must not be past expiry_date.
    - All cart categories must satisfy category_restriction if set.
    - Cart subtotal must meet min_purchase.
    """
    if promo is None:
        return {"valid": False, "reason": f"Promo code '{promo_code}' not found."}

    if not promo.get("active", False):
        return {"valid": False, "reason": "This promo code is no longer active."}

    expiry = promo.get("expiry_date") or ""
    if expiry:
        now_dt = datetime.fromisoformat(now)
        exp_dt = datetime.fromisoformat(expiry)
        if now_dt > exp_dt:
            return {"valid": False, "reason": f"Promo code expired on {expiry}."}

    cat_restriction = promo.get("category_restriction")
    if cat_restriction:
        invalid_cats = [c for c in cart_categories if c not in cat_restriction]
        if invalid_cats:
            return {
                "valid": False,
                "reason": (
                    f"Promo applies only to {', '.join(cat_restriction)}. "
                    f"Cart contains {', '.join(sorted(set(invalid_cats)))} items."
                ),
            }

    min_purchase = int(promo.get("min_purchase") or 0)
    if cart_subtotal < min_purchase:
        return {
            "valid": False,
            "reason": f"Minimum purchase of ${min_purchase} required. Cart subtotal: ${cart_subtotal}.",
        }

    discount_type = promo.get("discount_type", "percentage")
    discount_value = int(promo.get("discount_value") or 0)
    max_discount = int(promo.get("max_discount") or 0)

    if discount_type == "percentage":
        discount = int(cart_subtotal * discount_value / 100)
    else:
        discount = discount_value

    if max_discount > 0:
        discount = min(discount, max_discount)

    return {
        "valid": True,
        "discount_amount": discount,
        "reason": f"Promo applied: {promo.get('description', promo_code)}",
    }


# ---------------------------------------------------------------------------
# Stock & quantity (used by add_to_cart / update_cart_item)
# ---------------------------------------------------------------------------


def check_stock(
    product_in_stock: bool,
    stock_quantity: int,
    requested_quantity: int,
) -> dict[str, Any]:
    """Check whether `requested_quantity` can be fulfilled from stock."""
    if not product_in_stock:
        return {"available": False, "reason": "Product is currently out of stock."}
    if requested_quantity > stock_quantity:
        return {
            "available": False,
            "reason": f"Only {stock_quantity} units available. Requested: {requested_quantity}.",
        }
    return {"available": True, "quantity": requested_quantity}


def check_quantity_limit(
    current_quantity: int,
    requested_add: int,
) -> dict[str, Any]:
    """Enforce the per-product cap per cart (anti-hoarding)."""
    total = current_quantity + requested_add
    if total > QUANTITY_LIMIT:
        return {
            "allowed": False,
            "limit": QUANTITY_LIMIT,
            "current": current_quantity,
            "reason": (f"Maximum {QUANTITY_LIMIT} of the same product per cart. You already have {current_quantity}."),
        }
    return {"allowed": True, "total_after_add": total}


# ---------------------------------------------------------------------------
# Gift wrap
# ---------------------------------------------------------------------------


def compute_gift_wrap_fee(wrapped_item_count: int) -> int:
    """Flat per-wrapped-item fee. No threshold — any item can be wrapped."""
    return wrapped_item_count * GIFT_WRAP_FEE_PER_ITEM


# ---------------------------------------------------------------------------
# Loyalty points (info-only — agent verbalizes; no state write)
# ---------------------------------------------------------------------------


def compute_loyalty_points(cart_total: int, tier: str) -> dict[str, Any]:
    """Points earned on a purchase at the given tier's rate."""
    rate = LOYALTY_POINTS_RATE.get(tier, 1)
    return {"points_earned": cart_total * rate, "rate": rate, "tier": tier}


# Loyalty redemption constants
LOYALTY_REDEMPTION_RATE_POINTS_PER_DOLLAR: int = 100
LOYALTY_REDEMPTION_MIN_POINTS: int = 500
LOYALTY_REDEMPTION_CAP_PCT: float = 0.5  # 50% of cart total


def validate_redemption(balance: int, requested_points: int, cart_total: int) -> dict[str, Any]:
    """Validate a loyalty-point redemption request.

    Returns {valid, reason, discount_amount (cents→dollars), points_debited}.
    """
    if requested_points <= 0:
        return {
            "valid": False,
            "reason": "requested_points must be positive.",
            "discount_amount": 0,
            "points_debited": 0,
        }
    if requested_points < LOYALTY_REDEMPTION_MIN_POINTS:
        return {
            "valid": False,
            "reason": f"Minimum redemption is {LOYALTY_REDEMPTION_MIN_POINTS} points (${LOYALTY_REDEMPTION_MIN_POINTS // LOYALTY_REDEMPTION_RATE_POINTS_PER_DOLLAR}).",
            "discount_amount": 0,
            "points_debited": 0,
        }
    if requested_points > balance:
        return {
            "valid": False,
            "reason": f"Insufficient balance: have {balance} points, requested {requested_points}.",
            "discount_amount": 0,
            "points_debited": 0,
        }
    # Cap at 50% of cart total.
    max_discount = int(cart_total * LOYALTY_REDEMPTION_CAP_PCT)
    requested_dollars = requested_points // LOYALTY_REDEMPTION_RATE_POINTS_PER_DOLLAR
    discount = min(requested_dollars, max_discount)
    if discount <= 0:
        return {
            "valid": False,
            "reason": "Cart total is too low for redemption (50% cap too small to cover minimum).",
            "discount_amount": 0,
            "points_debited": 0,
        }
    points_debited = discount * LOYALTY_REDEMPTION_RATE_POINTS_PER_DOLLAR
    return {
        "valid": True,
        "reason": "Redemption validated.",
        "discount_amount": discount,
        "points_debited": points_debited,
    }


# ---------------------------------------------------------------------------
# Shipping options
# ---------------------------------------------------------------------------

VALID_SHIPPING_OPTIONS: list[str] = ["standard", "express", "next_day"]
STANDARD_SHIPPING_FEE: int = 6
EXPRESS_SHIPPING_FEE: int = 12  # express paid rate when not free-tier
NEXT_DAY_SHIPPING_FEE: int = 15  # next-day paid rate when not Platinum
FREE_SHIPPING_ITEM_THRESHOLD: int = 5  # 5+ units in cart -> free standard


def compute_shipping_cost(option: str, tier: str, total_item_count: int) -> dict[str, Any]:
    """Return {valid, reason, cost, eta_days_delta} for a shipping option.

    eta_days_delta: 0 for standard (use product.shipping_days as-is), -1 for
    express (one day faster), and -99 for next-day (caller special-cases to
    'next business day'). Callers surface ETAs; this function owns only the
    cost + validity.
    """
    tier = (tier or "standard").lower()
    if option not in VALID_SHIPPING_OPTIONS:
        return {
            "valid": False,
            "reason": f"Unknown shipping option {option!r}. Valid: {VALID_SHIPPING_OPTIONS}.",
            "cost": 0,
            "eta_days_delta": 0,
        }

    if option == "standard":
        cost = 0 if total_item_count >= FREE_SHIPPING_ITEM_THRESHOLD else STANDARD_SHIPPING_FEE
        return {"valid": True, "reason": "", "cost": cost, "eta_days_delta": 0}

    if option == "express":
        cost = 0 if tier in ("gold", "platinum") else EXPRESS_SHIPPING_FEE
        return {"valid": True, "reason": "", "cost": cost, "eta_days_delta": -1}

    # next_day
    cost = 0 if tier == "platinum" else NEXT_DAY_SHIPPING_FEE
    return {"valid": True, "reason": "", "cost": cost, "eta_days_delta": -99}


# ---------------------------------------------------------------------------
# Bundle bonuses (info-only — agent verbalizes; no state write)
# ---------------------------------------------------------------------------


def compute_brand_bundle_bonus(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Same-brand 2+ items → 3% off those items' line totals.

    Each item dict must carry: brand, unit_price, quantity.
    """
    brand_counts = Counter(item.get("brand", "") for item in items if item.get("brand"))
    bonus_brands = [b for b, c in brand_counts.items() if c >= 2]
    discount = 0
    for item in items:
        if item.get("brand") in bonus_brands:
            discount += int(item.get("unit_price", 0) * item.get("quantity", 1) * BRAND_BUNDLE_PCT)
    return {
        "has_brand_bonus": bool(bonus_brands),
        "bonus_brands": bonus_brands,
        "brand_discount": discount,
    }


def compute_category_bundle(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Same-category 3+ items → 5% off those items' line totals.

    Each item dict must carry: category, unit_price, quantity.
    """
    category_counts = Counter(item.get("category", "") for item in items if item.get("category"))
    bundle_cats = [c for c, count in category_counts.items() if count >= 3]
    discount = 0
    for item in items:
        if item.get("category") in bundle_cats:
            discount += int(item.get("unit_price", 0) * item.get("quantity", 1) * CATEGORY_BUNDLE_PCT)
    return {
        "has_category_bundle": bool(bundle_cats),
        "bundle_categories": bundle_cats,
        "category_discount": discount,
    }


# ---------------------------------------------------------------------------
# Welcome discount (info-only)
# ---------------------------------------------------------------------------


def check_welcome_discount(is_first_time: bool, cart_subtotal: int) -> dict[str, Any]:
    """First-time customers get 5% off; caller decides whether to verbalize."""
    if is_first_time:
        discount = int(cart_subtotal * WELCOME_DISCOUNT_PCT)
        return {
            "eligible": True,
            "discount_pct": int(WELCOME_DISCOUNT_PCT * 100),
            "discount_amount": discount,
            "reason": "First-time customer: 5% welcome discount applies.",
        }
    return {"eligible": False, "reason": "Welcome discount is for first-time customers only."}


# ---------------------------------------------------------------------------
# Backorder (info-only)
# ---------------------------------------------------------------------------


def compute_backorder_deposit(product_price: int) -> dict[str, Any]:
    deposit = int(product_price * BACKORDER_DEPOSIT_PCT)
    return {
        "deposit": deposit,
        "product_price": product_price,
        "estimated_restock": "2-4 weeks",
        "reason": f"Backorder available. 10% deposit (${deposit}) required. Estimated restock: 2-4 weeks.",
    }


# ---------------------------------------------------------------------------
# Price drop alerts (info-only)
# ---------------------------------------------------------------------------


def check_price_drop(current_price: int, previous_price: int | None) -> dict[str, Any]:
    if previous_price is not None and previous_price > current_price:
        savings = previous_price - current_price
        pct = int(savings / previous_price * 100)
        return {
            "has_drop": True,
            "previous_price": previous_price,
            "current_price": current_price,
            "savings": savings,
            "drop_pct": pct,
            "reason": f"Price dropped from ${previous_price} to ${current_price} — save ${savings} ({pct}% off).",
        }
    return {"has_drop": False}


# ---------------------------------------------------------------------------
# Policy texts served by get_policies(topic)
#
# Keep these authored as plain strings so the LLM judge can verify the
# agent's verbalization against them. No process gate — "did the agent
# explain X?" is judged conversationally in task_requirements.
# ---------------------------------------------------------------------------


POLICY_TEXTS: dict[str, dict[str, Any]] = {
    "welcome_discount": {
        "topic": "welcome_discount",
        "summary": "First-time customers receive an automatic 5% welcome discount on their first order.",
        "rules": [
            "Eligibility: customer.is_first_time is True (empty purchase history).",
            "Application: applied automatically at checkout, not via promo code.",
            "Stacking: not combinable with promo codes. Customer gets the better of the two.",
            "One-time: returning customers are not eligible.",
        ],
    },
    "loyalty_points": {
        "topic": "loyalty_points",
        "summary": "Loyalty points are earned on every purchase. Rate depends on membership tier.",
        "rules": [
            "Platinum: 3 points per dollar spent.",
            "Gold: 2 points per dollar spent.",
            "Standard: 1 point per dollar spent.",
            "Calculation: applied to the final total after all discounts.",
            "Disclosure: agents should mention points earned after any cart completion.",
        ],
    },
    "gift_wrap": {
        "topic": "gift_wrap",
        "summary": "Gift wrapping is a $5 per-item add-on available on any product.",
        "rules": [
            "Fee: $5 per wrapped item.",
            "Availability: available on all products unless product.gift_wrap_available is False.",
            "Modification: can be toggled per cart item via update_cart_item.",
        ],
    },
    "quantity_limit": {
        "topic": "quantity_limit",
        "summary": "Anti-hoarding: maximum 3 units of the same product per cart.",
        "rules": [
            f"Limit: {QUANTITY_LIMIT} units of the same product per cart.",
            "Enforcement: applies to total quantity in cart (existing + new).",
            "No exceptions regardless of tier, promo, or reason.",
        ],
    },
    "brand_bundle": {
        "topic": "brand_bundle",
        "summary": "Buying 2+ items of the same brand qualifies for a 3% bonus discount on those items.",
        "rules": [
            "Eligibility: 2+ items sharing the same brand.",
            "Discount: 3% off each qualifying item's line total.",
            "Stacking: stacks with category bundle and promo codes.",
            "Informational: agent surfaces this to the customer; the cart does not auto-apply it.",
        ],
    },
    "category_bundle": {
        "topic": "category_bundle",
        "summary": "Buying 3+ items from the same category qualifies for a 5% bundle discount on those items.",
        "rules": [
            "Eligibility: 3+ items sharing the same category.",
            "Discount: 5% off each qualifying item's line total.",
            "Stacking: does NOT stack with promo codes on the same items. Customer gets the better of the two.",
        ],
    },
    "backorder": {
        "topic": "backorder",
        "summary": "Out-of-stock items flagged backorder_available can be reserved with a 10% deposit.",
        "rules": [
            "Eligibility: product.in_stock is False AND product.backorder_available is True.",
            "Deposit: 10% of the product price, refundable if restock fails.",
            "Timeline: estimated 2–4 weeks to restock.",
            "Proactive: when a requested product is OOS, agent should check and offer backorder if available.",
        ],
    },
    "price_alerts": {
        "topic": "price_alerts",
        "summary": "Products with previous_price higher than current price recently went on sale.",
        "rules": [
            "Detection: product.previous_price > product.price.",
            "Disclosure: agent should proactively mention price drops when recommending or showing details.",
        ],
    },
    "promo_stacking": {
        "topic": "promo_stacking",
        "summary": "At most one promo code per cart. Some discounts stack with each other but not with promo codes.",
        "rules": [
            "One promo code per cart.",
            "Category bundle (5%) does NOT stack with promo codes on the same items — customer gets the better of the two.",
            "Welcome discount (5%) does NOT stack with promo codes — customer gets the better of the two.",
            "Brand bundle bonus (3%) DOES stack with everything.",
        ],
    },
    "shipping": {
        "topic": "shipping",
        "summary": "Shipping speed depends on customer preference and tier. Three options: standard, express, next_day.",
        "rules": [
            "Standard: listed shipping_days, $6 fee.",
            "Express: -1 day vs standard, $12 fee. Free for Gold and Platinum.",
            "Next-day: next business day, $15 fee. Free for Platinum.",
            "Bundle override: 5+ items total grants free standard shipping regardless of tier.",
            "Agent action rule: do NOT call set_shipping_option without an explicit customer choice. You may discuss options in chat when the customer asks about shipping/delivery/deadlines, but the write call must come AFTER the customer names a specific option.",
        ],
    },
    "returns": {
        "topic": "returns",
        "summary": "30-day return window from delivery. Items must be in original condition.",
        "rules": [
            "Window: 30 days from delivery date.",
            "Condition: unused, with original packaging.",
            "Refund: to original payment method within 5 business days of return receipt.",
            "Exclusions: final-sale items and digital goods are not returnable.",
        ],
    },
    "price_match": {
        "topic": "price_match",
        "summary": "One-time price adjustment within 7 days of purchase if the same item goes on sale.",
        "rules": [
            "Window: 7 days from order date.",
            "Scope: same SKU, not similar items.",
            "Refund: difference is credited to original payment method.",
            "Exclusions: third-party promo codes, flash sales shorter than 24 hours.",
        ],
    },
    "loyalty_redemption": {
        "topic": "loyalty_redemption",
        "summary": "Loyalty points can be redeemed at checkout to offset part of the cart total. 100 points = $1.",
        "rules": [
            "Rate: 100 loyalty points = $1.00 off.",
            "Cap: redemption cannot exceed 50% of the current cart total.",
            "Minimum redemption: 500 points ($5).",
            "Stacking: stacks with promo codes and category bundles.",
            "Restriction: not combinable with the first-time welcome discount.",
            "Points are debited from the customer's balance at redemption.",
            "Agent action rule: do NOT call redeem_loyalty_points without an explicit customer-specified amount. You may discuss and recommend redemption in chat, but the write call must come AFTER the customer names a specific number of points.",
        ],
    },
}


VALID_POLICY_TOPICS: list[str] = list(POLICY_TEXTS.keys())
