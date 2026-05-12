"""Promotion listing, validation, and cart application."""

from __future__ import annotations

from datetime import datetime as _dt
from typing import Any, Callable

from state_bench.domains.shopping_assistant import policies
from state_bench.domains.shopping_assistant.schemas import Cart, CartItem, Product, Promotion
from state_bench.domains.shopping_assistant.services.pricing import PricingEngine


class PromotionService:
    """Own promo tool behavior while pricing owns aggregate recompute."""

    def __init__(
        self,
        *,
        products: dict[str, Product],
        promotions: dict[str, Promotion],
        resolve_cart: Callable[[str], Cart | None],
        items_in_cart: Callable[[Cart], list[CartItem]],
        pricing_engine: PricingEngine,
        now: str,
    ) -> None:
        self.products = products
        self.promotions = promotions
        self._resolve_cart = resolve_cart
        self._items_in_cart = items_in_cart
        self.pricing_engine = pricing_engine
        self.now = now

    def _item_categories(self, cart: Cart) -> list[str]:
        return sorted({self.products[ci.product_id].category for ci in self._items_in_cart(cart)})

    def get_promotions(self, params: dict[str, Any]) -> dict[str, Any]:
        category = params.get("category")
        promos = []
        for p in self.promotions.values():
            if not p.active:
                continue
            if category and p.category_restriction and category not in p.category_restriction:
                continue
            if p.expiry_date and _dt.fromisoformat(self.now) > _dt.fromisoformat(p.expiry_date):
                continue
            promos.append(p.to_dict())
        return {"promotions": promos}

    def validate_promo(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        promo_code = params.get("promo_code", "")
        cart = self._resolve_cart(customer_id)
        if cart is None:
            return {"valid": False, "reason": f"No cart for customer {customer_id}.", "estimated_discount": 0}

        promo = self.promotions.get(promo_code)
        result = policies.validate_promo(
            promo_code=promo_code,
            promo=promo.to_dict() if promo else None,
            cart_subtotal=cart.subtotal,
            cart_categories=self._item_categories(cart),
            now=self.now,
        )
        return {
            "valid": result["valid"],
            "reason": result["reason"],
            "estimated_discount": int(result.get("discount_amount") or 0) if result["valid"] else 0,
        }

    def apply_promo(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        promo_code = params.get("promo_code", "")
        cart = self._resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}

        if promo_code in cart.applied_promo_codes:
            return {
                "status": "already_applied",
                "promo_code": promo_code,
                "discount_amount": cart.discount_amount,
                "cart_subtotal": cart.subtotal,
                "cart_total": cart.total,
            }

        stack_result = policies.check_promo_stack(cart.applied_promo_codes, promo_code)
        if not stack_result["valid"]:
            return {"error": stack_result["reason"]}

        promo = self.promotions.get(promo_code)
        result = policies.validate_promo(
            promo_code=promo_code,
            promo=promo.to_dict() if promo else None,
            cart_subtotal=cart.subtotal,
            cart_categories=self._item_categories(cart),
            now=self.now,
        )
        if not result["valid"]:
            return {"error": result["reason"]}

        cart.applied_promo_codes = [*cart.applied_promo_codes, promo_code]
        adjustments = self.pricing_engine.recompute_cart(cart)
        return {
            "status": "applied",
            "promo_code": promo_code,
            "applied_promo_codes": list(cart.applied_promo_codes),
            "discount_amount": cart.discount_amount,
            "cart_subtotal": cart.subtotal,
            "cart_total": cart.total,
            **adjustments,
        }

    def remove_promo(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        promo_code = params.get("promo_code", "")
        cart = self._resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}

        if promo_code not in cart.applied_promo_codes:
            return {"error": f"Promo code '{promo_code}' is not currently applied to this cart."}

        cart.applied_promo_codes = [c for c in cart.applied_promo_codes if c != promo_code]
        adjustments = self.pricing_engine.recompute_cart(cart)
        return {
            "status": "removed",
            "promo_code": promo_code,
            "applied_promo_codes": list(cart.applied_promo_codes),
            "discount_amount": cart.discount_amount,
            "cart_subtotal": cart.subtotal,
            "cart_total": cart.total,
            **adjustments,
        }
