"""Stateful shopping assistant environment with tool handlers.

Designed for JIT per-task environments (each task ships its own `task_envs/<id>.json`)
and the dual-axis scoring contract:
- `state_requirements` (deterministic): cart aggregates as `modified` entries,
  cart_items as `created` entries with minimal 5-field records.
- `task_requirements` (LLM-judged): conversational verification of policy
  surfacing, acceptable picks, proactive discovery.

Key behaviors:
- Cart pre-exists empty in every task_env, keyed `CART-<customer_id>`. No
  set_task_cart hack and no on-demand cart creation.
- search_products hard-filters on customer-asserted constraints (price,
  rating, stock, category) and soft-ranks on `query` against name, brand,
  subcategory, description, and spec keys/values. A non-empty query with
  zero matches returns no results (not a silent degrade).
- check_compatibility returns canonical-device list when device name unknown.
- get_cart returns persisted cart state only (no derived promo eligibility).
- No process gates: get_promotions / get_policies / apply_promo are independent.
- All time comparisons use `self.now` (set at env init).
"""

from __future__ import annotations

from typing import Any

from state_bench.domains.shopping_assistant import policies
from state_bench.domains.shopping_assistant.policies import POLICY_TEXTS, VALID_POLICY_TOPICS
from state_bench.domains.shopping_assistant.schemas import (
    Cart,
    CartItem,
    Customer,
    Product,
    Promotion,
    SAEnvironmentData,
)
from state_bench.domains.shopping_assistant.services.cart import CartService
from state_bench.domains.shopping_assistant.services.catalog import (
    CatalogSearch,
    CompatibilityService,
)
from state_bench.domains.shopping_assistant.services.pricing import PricingEngine
from state_bench.domains.shopping_assistant.services.promotion import PromotionService
from state_bench.domains.shopping_assistant.services.shipping import ShippingPolicyService
from state_bench.environment import BaseEnvironment

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


class ShoppingAssistantEnvironment(BaseEnvironment):
    """Stateful environment for the shopping assistant domain."""

    def __init__(self, env_data: SAEnvironmentData, now: str):
        super().__init__(env_data, now)
        self.products: dict[str, Product] = {p.product_id: p for p in env_data.products}
        self.customers: dict[str, Customer] = {c.customer_id: c for c in env_data.customers}
        self.carts_by_id: dict[str, Cart] = {c.cart_id: c for c in env_data.carts}
        self.cart_items: dict[str, CartItem] = {ci.cart_item_id: ci for ci in env_data.cart_items}
        self.promotions: dict[str, Promotion] = {p.promo_code: p for p in env_data.promotions}

        self.cart_service = CartService(
            products=self.products,
            carts_by_id=self.carts_by_id,
            cart_items=self.cart_items,
        )

        self.pricing_engine = PricingEngine(
            products=self.products,
            promotions=self.promotions,
            customers=self.customers,
            items_in_cart=self._items_in_cart,
            variant_lookup=self._variant_lookup,
            now=self.now,
        )
        self.cart_service.set_pricing_engine(self.pricing_engine)
        self.promotion_service = PromotionService(
            products=self.products,
            promotions=self.promotions,
            resolve_cart=self._resolve_cart,
            items_in_cart=self._items_in_cart,
            pricing_engine=self.pricing_engine,
            now=self.now,
        )
        self.shipping_service = ShippingPolicyService(
            products=self.products,
            customers=self.customers,
            resolve_cart=self._resolve_cart,
            items_in_cart=self._items_in_cart,
            pricing_engine=self.pricing_engine,
        )
        self.catalog_search = CatalogSearch(
            products=self.products,
            variant_lookup=self._variant_lookup,
        )
        self.compatibility_service = CompatibilityService(products=self.products)

    # -------------------------------------------------------------------
    # Snapshot for state_requirements check
    # -------------------------------------------------------------------

    def get_full_snapshot(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Return mutable entities indexed by type and id.

        Carts, cart_items, and customers mutate during a run (customers via
        loyalty-points redemption). Products and promotions are immutable
        per task_env.

        Deep-copied so subsequent mutations to the env do not alias into the
        returned snapshot (lists/dicts on the dataclasses would otherwise be
        shared references via DictMixin.to_dict).
        """
        import copy

        return {
            "carts": {cid: copy.deepcopy(c.to_dict()) for cid, c in self.carts_by_id.items()},
            "cart_items": {ciid: copy.deepcopy(ci.to_dict()) for ciid, ci in self.cart_items.items()},
            "customers": {cid: copy.deepcopy(c.to_dict()) for cid, c in self.customers.items()},
        }

    # -------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------

    def _resolve_cart(self, customer_id: str) -> Cart | None:
        return self.cart_service.resolve_cart(customer_id)

    def _items_in_cart(self, cart: Cart) -> list[CartItem]:
        return self.cart_service.items_in_cart(cart)

    def _variant_lookup(self, product: Product, variant_id: str | None) -> dict[str, Any] | None:
        """Find a variant dict on `product.variants` by id. Returns None if no variant requested or no match."""
        return self.cart_service.variant_lookup(product, variant_id)

    def _unit_price(self, ci: CartItem) -> int:
        """Live unit price for a cart_item, accounting for variant price_delta when set."""
        return self.pricing_engine.unit_price(ci)

    def _recompute_cart(self, cart: Cart) -> dict[str, Any]:
        """Single source of truth for cart aggregates.

        Pulls live unit prices from the products table — cart_items don't
        store prices. Reapplies any active promo so discount_amount stays
        in sync with subtotal changes (e.g., qty updates).
        """
        return self.pricing_engine.recompute_cart(cart)

    # -------------------------------------------------------------------
    # READ tools
    # -------------------------------------------------------------------

    def search_products(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search the catalog with hard filters + soft ranking.

        Hard filters (exclude): category, min_price, max_price, min_rating, in_stock_only.
        Soft signal (rank): query — matched against name, brand, subcategory,
        description, and spec keys/values. No curated tags; the agent has to
        work through customer-facing fields.

        Behavior:
        - Hard filters empty -> {"products": [], "note": "..."} with guidance.
        - `query` non-empty -> drop products with zero query matches (score=0).
          This mirrors real search: "no matches" is a valid answer; it forces
          the agent to refine the query or relax filters.
        - `query` empty -> all hard-filter-surviving products are returned in
          stable order (by product_id) up to SEARCH_TOP_N.
        """
        return self.catalog_search.search_products(params)

    def get_product_details(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.catalog_search.get_product_details(params)

    def get_variants(self, params: dict[str, Any]) -> dict[str, Any]:
        """List variants (color/size/etc) for a product, if any.

        Returns {product_id, product_name, base_price, variants: [...]}.
        For products without variants, returns an empty list and a note.
        """
        return self.catalog_search.get_variants(params)

    def get_customer_account(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        customer = self.customers.get(customer_id)
        if not customer:
            return {"error": f"Customer {customer_id} not found."}
        return customer.to_dict()

    def get_cart(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return cart contents (persisted state only).

        Does not compute promo eligibility — agents should use
        get_promotions + get_customer_account to reason about applicability.
        """
        customer_id = params.get("customer_id", "")
        cart = self._resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}
        items_view = []
        for ci in self._items_in_cart(cart):
            product = self.products.get(ci.product_id)
            variant = self._variant_lookup(product, ci.variant_id) if product else None
            unit_price = self._unit_price(ci) if product else 0
            item_view = {
                "cart_item_id": ci.cart_item_id,
                "product_id": ci.product_id,
                "product_name": product.name if product else None,
                "quantity": ci.quantity,
                "gift_wrap": ci.gift_wrap,
                "unit_price": unit_price,
                "line_total": unit_price * ci.quantity,
            }
            if ci.variant_id:
                item_view["variant_id"] = ci.variant_id
                item_view["variant_label"] = (variant or {}).get("label") if variant else None
            items_view.append(item_view)
        return {
            "cart_id": cart.cart_id,
            "customer_id": cart.customer_id,
            "items": items_view,
            "subtotal": cart.subtotal,
            "discount_amount": cart.discount_amount,
            "gift_wrap_fee": cart.gift_wrap_fee,
            "loyalty_discount": cart.loyalty_discount,
            "loyalty_points_redeemed": cart.loyalty_points_redeemed,
            "shipping_option": cart.shipping_option,
            "shipping_cost": cart.shipping_cost,
            "total": cart.total,
            "applied_promo_codes": list(cart.applied_promo_codes),
        }

    def check_compatibility(self, params: dict[str, Any]) -> dict[str, Any]:
        """Check whether `device_name` exact-matches any of product.compatible_with.

        On miss with an unknown device name, returns the canonical-device list
        as a discoverability hint so the agent can correct the spelling.
        """
        return self.compatibility_service.check_compatibility(params)

    def browse_recommendations(self, params: dict[str, Any]) -> dict[str, Any]:
        """Unsupported helper for schemas that are not part of this benchmark.

        The shopping domain is intentionally search-only; recommendation
        requests should be handled through search_products.
        """
        raise RuntimeError("browse_recommendations is not supported. Use search_products.")

    def get_promotions(self, params: dict[str, Any]) -> dict[str, Any]:
        """List active promo codes. Optional category filter. No cart coupling."""
        return self.promotion_service.get_promotions(params)

    def get_policies(self, params: dict[str, Any]) -> dict[str, Any]:
        topic = params.get("topic", "")
        if topic in POLICY_TEXTS:
            return POLICY_TEXTS[topic]
        return {
            "error": f"Unknown policy topic: '{topic}'. Valid topics: {', '.join(VALID_POLICY_TOPICS)}.",
        }

    # -------------------------------------------------------------------
    # WRITE tools
    # -------------------------------------------------------------------

    def add_to_cart(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a cart_item record for (cart, product). Recompute cart aggregates.

        If the product is already in the cart, increment its quantity instead
        of creating a duplicate cart_item. Quantity limit enforced.

        If the product has variants, a `variant_id` MUST be supplied. Two items
        of the same product but different variants result in separate lines.
        """
        return self.cart_service.add_to_cart(params)

    def update_cart_item(self, params: dict[str, Any]) -> dict[str, Any]:
        """Modify quantity and/or gift_wrap for an existing cart_item.

        quantity=0 removes the item (delegates to remove_from_cart semantics).
        At least one of quantity / gift_wrap must be provided.
        """
        return self.cart_service.update_cart_item(params)

    def remove_from_cart(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete the cart_item for (cart, product). Recompute aggregates."""
        return self.cart_service.remove_from_cart(params)

    def apply_promo(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate `promo_code` against current cart and add it to applied codes.

        One promo code can be applied per cart. Applying the same code twice is
        a no-op (deduped); applying a different code requires removing the
        existing code first. Validates intrinsic rules (active, expiry,
        category, min_purchase) — does NOT check customer-fit rules; that's the
        agent's responsibility.
        """
        return self.promotion_service.apply_promo(params)

    def remove_promo(self, params: dict[str, Any]) -> dict[str, Any]:
        """Remove a previously applied promo code and recompute totals."""
        return self.promotion_service.remove_promo(params)

    def redeem_loyalty_points(self, params: dict[str, Any]) -> dict[str, Any]:
        """Redeem loyalty points for a dollar discount on the current cart total.

        Debits points from customer.loyalty_points. Enforces minimum, balance, and
        50%-of-cart-total cap per the loyalty_redemption policy.
        """
        customer_id = params.get("customer_id", "")
        requested = int(params.get("points") or 0)
        cart = self._resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}
        customer = self.customers.get(customer_id)
        if customer is None:
            return {"error": f"Customer {customer_id} not found."}
        if cart.subtotal <= 0:
            return {"error": "Cart is empty — cannot redeem points on an empty cart."}
        if cart.loyalty_discount > 0:
            return {
                "error": (
                    f"Points already redeemed on this cart ({cart.loyalty_points_redeemed} pts = "
                    f"${cart.loyalty_discount}). Cancel first to redeem a different amount."
                )
            }
        result = policies.validate_redemption(
            balance=customer.loyalty_points,
            requested_points=requested,
            cart_total=cart.subtotal + cart.gift_wrap_fee - cart.discount_amount,
        )
        if not result["valid"]:
            return {"error": result["reason"]}

        discount = int(result["discount_amount"])
        points_debited = int(result["points_debited"])
        customer.loyalty_points -= points_debited
        cart.loyalty_discount = discount
        cart.loyalty_points_redeemed = points_debited
        adjustments = self._recompute_cart(cart)
        return {
            "status": "redeemed",
            "points_redeemed": points_debited,
            "discount_applied": discount,
            "remaining_balance": customer.loyalty_points,
            "cart_subtotal": cart.subtotal,
            "cart_total": cart.total,
            **adjustments,
        }

    def cancel_loyalty_redemption(self, params: dict[str, Any]) -> dict[str, Any]:
        """Reverse a prior loyalty_points redemption on this cart and credit points back."""
        customer_id = params.get("customer_id", "")
        cart = self._resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}
        customer = self.customers.get(customer_id)
        if customer is None:
            return {"error": f"Customer {customer_id} not found."}
        if cart.loyalty_discount == 0 and cart.loyalty_points_redeemed == 0:
            return {"error": "No loyalty redemption on this cart to cancel."}
        credited = cart.loyalty_points_redeemed
        customer.loyalty_points += credited
        cart.loyalty_discount = 0
        cart.loyalty_points_redeemed = 0
        adjustments = self._recompute_cart(cart)
        return {
            "status": "cancelled",
            "points_credited": credited,
            "new_balance": customer.loyalty_points,
            "cart_subtotal": cart.subtotal,
            "cart_total": cart.total,
            **adjustments,
        }

    def get_shipping_options(self, params: dict[str, Any]) -> dict[str, Any]:
        """List available shipping options for the customer's cart with prices and ETAs.

        Does not mutate cart state. Returns each valid option with `option`,
        `cost`, `eta_description`, and an `eligibility` note explaining any
        tier-based free perk or the 5+-item standard override.
        """
        return self.shipping_service.get_shipping_options(params)

    def set_shipping_option(self, params: dict[str, Any]) -> dict[str, Any]:
        """Set the shipping option on the cart. Validates and writes cart.shipping_cost.

        Recomputes cart totals so cart.total reflects the added shipping cost.
        Customers can switch options freely by calling again; the prior value
        is overwritten.
        """
        return self.shipping_service.set_shipping_option(params)

    def validate_promo(self, params: dict[str, Any]) -> dict[str, Any]:
        """Pure read — check whether a promo code would validate against the current cart.

        Checks intrinsic validity only (exists, active, not expired, category
        restriction, min_purchase). Does NOT check customer-fit rules like
        first-time-only — that's the agent's job via get_customer_account.
        """
        return self.promotion_service.validate_promo(params)

    # -------------------------------------------------------------------
    # Tool handler registry
    # -------------------------------------------------------------------

    @property
    def tool_handlers(self) -> dict[str, Any]:
        return {
            # READ
            "search_products": self.search_products,
            "get_product_details": self.get_product_details,
            "get_variants": self.get_variants,
            "get_customer_account": self.get_customer_account,
            "get_cart": self.get_cart,
            "check_compatibility": self.check_compatibility,
            "get_promotions": self.get_promotions,
            "get_policies": self.get_policies,
            "validate_promo": self.validate_promo,
            # WRITE
            "add_to_cart": self.add_to_cart,
            "update_cart_item": self.update_cart_item,
            "remove_from_cart": self.remove_from_cart,
            "apply_promo": self.apply_promo,
            "remove_promo": self.remove_promo,
            "redeem_loyalty_points": self.redeem_loyalty_points,
            "cancel_loyalty_redemption": self.cancel_loyalty_redemption,
            "get_shipping_options": self.get_shipping_options,
            "set_shipping_option": self.set_shipping_option,
        }
