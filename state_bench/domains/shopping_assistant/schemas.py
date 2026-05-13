"""Shopping assistant domain data models.

Designed for the strict-equality semantics of `evaluate_state_requirements`:
- `cart` is pre-created empty in every task_env and mutated as the agent acts.
  Only changed fields show up in StateDiff.modified, so aggregate assertions
  stay selective.
- `cart_item` is minimal (5 fields). Created by add_to_cart, identified in
  assertions via `match_fields`. No stored unit_price or line_total —
  those are derived on-the-fly from `products[product_id].price`.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from state_bench.schemas import DictMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database records
# ---------------------------------------------------------------------------


@dataclass
class Product(DictMixin):
    """Catalog product. Frozen at env-load time — never mutated during a run."""

    product_id: str  # e.g. "SP-1003"
    name: str  # Unique within a single task_env
    category: str  # electronics | kitchen | clothing | accessories | home_office | outdoor
    subcategory: str  # laptop | phone | headphones | blender | jacket | desk | etc.
    brand: str
    price: int  # dollars
    rating: float  # 1.0-5.0
    review_count: int
    description: str = ""  # short prose description surfaced in details
    specs: dict[str, Any] = field(default_factory=dict)
    compatible_with: list[str] = field(default_factory=list)  # canonical device strings
    in_stock: bool = True
    stock_quantity: int = 50
    shipping_days: int = 3
    gift_wrap_available: bool = True
    backorder_available: bool = False
    previous_price: int | None = None  # for price-drop alerts
    variants: list[dict[str, Any]] | None = (
        None  # None = no variants; when set, each dict has {variant_id, label, price_delta, in_stock, stock_quantity}
    )


@dataclass
class Customer(DictMixin):
    """Shopper profile. Generally not mutated during a run."""

    customer_id: str
    name: str
    email: str
    tier: str = "standard"  # standard | gold | platinum
    is_first_time: bool = False
    loyalty_points: int = 0
    purchase_history: list[str] = field(default_factory=list)  # product_ids; populated per-task when needed


@dataclass
class CartItem(DictMixin):
    """Minimal cart item. Created by add_to_cart, mutated by update_cart_item.

    Only 5 fields so that a fresh creation produces a tight StateDiff.
    Unit price is NOT stored; cart.subtotal recomputes from products table.
    """

    cart_item_id: str  # e.g. "CI-0001"
    customer_id: str  # denormalized for match_fields convenience
    product_id: str
    quantity: int
    gift_wrap: bool
    variant_id: str | None = None  # None = no variant selected; must match a variant on the product when set


@dataclass
class Cart(DictMixin):
    """One cart per customer. Pre-exists empty in every task_env."""

    cart_id: str  # canonical: f"CART-{customer_id}"
    customer_id: str
    item_ids: list[str] = field(default_factory=list)  # ordered list of cart_item_ids
    subtotal: int = 0
    discount_amount: int = 0
    gift_wrap_fee: int = 0
    total: int = 0
    applied_promo_codes: list[str] = field(default_factory=list)
    loyalty_points_redeemed: int = 0  # points debited from customer balance for this cart
    loyalty_discount: int = 0  # dollars discounted from total via redemption (defaults to 0 = no regression)
    shipping_option: str | None = None  # None = not yet chosen; 'standard' | 'express' | 'next_day'
    shipping_cost: int = 0  # dollars added to cart.total for shipping (defaults to 0 = no regression)


@dataclass
class Promotion(DictMixin):
    promo_code: str
    description: str
    discount_type: str = "percentage"  # percentage | fixed
    discount_value: int = 0  # percentage (10 = 10%) or fixed dollar amount
    min_purchase: int = 0
    max_discount: int = 0  # 0 = no max
    category_restriction: list[str] | None = None  # None = all categories
    expiry_date: str = ""  # ISO date
    active: bool = True


# ---------------------------------------------------------------------------
# Environment snapshot
# ---------------------------------------------------------------------------


@dataclass
class SAEnvironmentData:
    """Full environment state for a single task run."""

    products: list[Product]
    customers: list[Customer]
    carts: list[Cart]
    cart_items: list[CartItem] = field(default_factory=list)
    promotions: list[Promotion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": [p.to_dict() for p in self.products],
            "customers": [c.to_dict() for c in self.customers],
            "carts": [c.to_dict() for c in self.carts],
            "cart_items": [ci.to_dict() for ci in self.cart_items],
            "promotions": [p.to_dict() for p in self.promotions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SAEnvironmentData:
        return cls(
            products=[Product.from_dict(p) for p in data["products"]],
            customers=[Customer.from_dict(c) for c in data["customers"]],
            carts=[Cart.from_dict(c) for c in data["carts"]],
            cart_items=[CartItem.from_dict(ci) for ci in data.get("cart_items", [])],
            promotions=[Promotion.from_dict(p) for p in data.get("promotions", [])],
        )

    def deep_copy(self) -> SAEnvironmentData:
        return SAEnvironmentData.from_dict(copy.deepcopy(self.to_dict()))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(
            "Saved environment: %s products, %s customers, %s carts, %s cart_items, %s promotions -> %s",
            len(self.products),
            len(self.customers),
            len(self.carts),
            len(self.cart_items),
            len(self.promotions),
            path,
        )

    @classmethod
    def load(cls, path: Path) -> SAEnvironmentData:
        with open(path) as f:
            return cls.from_dict(json.load(f))
