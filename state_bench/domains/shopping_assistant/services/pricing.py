"""Cart pricing and aggregate recomputation."""

from __future__ import annotations

from typing import Any, Callable

from state_bench.domains.shopping_assistant import policies
from state_bench.domains.shopping_assistant.schemas import Cart, CartItem, Customer, Product, Promotion


class PricingEngine:
    """Recompute cart aggregate fields from live catalog and cart state."""

    def __init__(
        self,
        *,
        products: dict[str, Product],
        promotions: dict[str, Promotion],
        customers: dict[str, Customer],
        items_in_cart: Callable[[Cart], list[CartItem]],
        variant_lookup: Callable[[Product, str | None], dict[str, Any] | None],
        now: str,
    ) -> None:
        self.products = products
        self.promotions = promotions
        self.customers = customers
        self._items_in_cart = items_in_cart
        self._variant_lookup = variant_lookup
        self.now = now

    def unit_price(self, ci: CartItem) -> int:
        """Live unit price for a cart item, including variant price delta."""
        product = self.products[ci.product_id]
        variant = self._variant_lookup(product, ci.variant_id)
        if variant is not None:
            return int(product.price) + int(variant.get("price_delta", 0))
        return int(product.price)

    def recompute_cart(self, cart: Cart) -> dict[str, Any]:
        """Single source of truth for cart aggregates."""
        items = self._items_in_cart(cart)
        cart.subtotal = sum(self.unit_price(ci) * ci.quantity for ci in items)
        cart.gift_wrap_fee = policies.compute_gift_wrap_fee(sum(1 for ci in items if ci.gift_wrap))

        cart.discount_amount = 0
        if cart.applied_promo_codes:
            kept_promos: list[str] = []
            item_categories = sorted({self.products[ci.product_id].category for ci in items})
            total_discount = 0
            for code in cart.applied_promo_codes:
                promo = self.promotions.get(code)
                result = policies.validate_promo(
                    promo_code=code,
                    promo=promo.to_dict() if promo else None,
                    cart_subtotal=cart.subtotal,
                    cart_categories=item_categories,
                    now=self.now,
                )
                if result["valid"]:
                    kept_promos.append(code)
                    total_discount += result["discount_amount"]
            cart.applied_promo_codes = kept_promos
            cart.discount_amount = total_discount

        adjustments: dict[str, Any] = {}

        if cart.loyalty_discount > 0:
            max_discount = int(cart.subtotal * policies.LOYALTY_REDEMPTION_CAP_PCT)
            if cart.loyalty_discount > max_discount:
                previous_discount = cart.loyalty_discount
                previous_points = cart.loyalty_points_redeemed
                new_discount = max(0, max_discount)
                new_points = new_discount * policies.LOYALTY_REDEMPTION_RATE_POINTS_PER_DOLLAR
                refunded_points = max(0, previous_points - new_points)
                cart.loyalty_discount = new_discount
                cart.loyalty_points_redeemed = new_points
                customer = self.customers.get(cart.customer_id)
                if customer is not None and refunded_points > 0:
                    customer.loyalty_points += refunded_points
                adjustments["loyalty_redemption_clamped"] = True
                adjustments["previous_loyalty_discount"] = previous_discount
                adjustments["loyalty_points_refunded"] = refunded_points
                adjustments["new_loyalty_discount"] = new_discount
                adjustments["new_loyalty_points_redeemed"] = new_points
                if customer is not None:
                    adjustments["customer_loyalty_points"] = customer.loyalty_points

        cart.total = max(
            0,
            cart.subtotal + cart.gift_wrap_fee + cart.shipping_cost - cart.discount_amount - cart.loyalty_discount,
        )
        return adjustments
