"""Shipping option listing and selection policy."""

from __future__ import annotations

from typing import Any, Callable

from state_bench.domains.shopping_assistant import policies
from state_bench.domains.shopping_assistant.schemas import Cart, CartItem, Customer, Product
from state_bench.domains.shopping_assistant.services.pricing import PricingEngine


class ShippingPolicyService:
    """Own shipping costs, ETA text, eligibility text, and cart selection writes."""

    def __init__(
        self,
        *,
        products: dict[str, Product],
        customers: dict[str, Customer],
        resolve_cart: Callable[[str], Cart | None],
        items_in_cart: Callable[[Cart], list[CartItem]],
        pricing_engine: PricingEngine,
    ) -> None:
        self.products = products
        self.customers = customers
        self._resolve_cart = resolve_cart
        self._items_in_cart = items_in_cart
        self.pricing_engine = pricing_engine

    def _cart_shipping_context(self, cart: Cart) -> tuple[list[CartItem], int, int]:
        items = self._items_in_cart(cart)
        total_item_count = sum(ci.quantity for ci in items)
        max_product_shipping_days = max(
            (self.products[ci.product_id].shipping_days for ci in items if ci.product_id in self.products),
            default=0,
        )
        return items, total_item_count, max_product_shipping_days

    def _eta_description(self, option_name: str, max_product_shipping_days: int) -> str:
        if option_name == "standard":
            eta_days = max(max_product_shipping_days, 1)
            return f"{eta_days} business days"
        if option_name == "express":
            eta_days = max(max_product_shipping_days - 1, 1)
            return f"{eta_days} business days"
        return "next business day"

    def _eligibility(self, option_name: str, customer: Customer, total_item_count: int, cost: int) -> str:
        if option_name == "standard" and total_item_count >= policies.FREE_SHIPPING_ITEM_THRESHOLD:
            return "free — 5+ items in cart"
        if option_name == "express" and customer.tier.lower() in ("gold", "platinum"):
            return f"free — {customer.tier.capitalize()} perk"
        if option_name == "next_day" and customer.tier.lower() == "platinum":
            return "free — Platinum perk"
        return f"${cost}"

    def get_shipping_options(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        cart = self._resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}
        customer = self.customers.get(customer_id)
        if customer is None:
            return {"error": f"Customer {customer_id} not found."}

        _items, total_item_count, max_product_shipping_days = self._cart_shipping_context(cart)

        options: list[dict[str, Any]] = []
        for option_name in policies.VALID_SHIPPING_OPTIONS:
            spec = policies.compute_shipping_cost(option_name, customer.tier, total_item_count)
            options.append(
                {
                    "option": option_name,
                    "cost": spec["cost"],
                    "eta_description": self._eta_description(option_name, max_product_shipping_days),
                    "eligibility": self._eligibility(option_name, customer, total_item_count, spec["cost"]),
                }
            )

        return {
            "options": options,
            "cart_item_count": total_item_count,
            "customer_tier": customer.tier,
        }

    def set_shipping_option(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        option = params.get("option", "")
        cart = self._resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}
        customer = self.customers.get(customer_id)
        if customer is None:
            return {"error": f"Customer {customer_id} not found."}
        if not cart.item_ids:
            return {"error": "Cart is empty — cannot set shipping on an empty cart."}

        _items, total_item_count, _max_product_shipping_days = self._cart_shipping_context(cart)
        spec = policies.compute_shipping_cost(option, customer.tier, total_item_count)
        if not spec["valid"]:
            return {"error": spec["reason"]}

        cart.shipping_option = option
        cart.shipping_cost = int(spec["cost"])
        adjustments = self.pricing_engine.recompute_cart(cart)
        return {
            "status": "set",
            "shipping_option": option,
            "shipping_cost": cart.shipping_cost,
            "cart_subtotal": cart.subtotal,
            "cart_total": cart.total,
            **adjustments,
        }
