"""Cart lookup and mutation operations."""

from __future__ import annotations

import re
from typing import Any

from state_bench.domains.shopping_assistant import policies
from state_bench.domains.shopping_assistant.schemas import Cart, CartItem, Product
from state_bench.domains.shopping_assistant.services.pricing import PricingEngine


class CartService:
    """Own cart item lookup, stock checks, ID generation, and mutations."""

    def __init__(
        self,
        *,
        products: dict[str, Product],
        carts_by_id: dict[str, Cart],
        cart_items: dict[str, CartItem],
    ) -> None:
        self.products = products
        self.carts_by_id = carts_by_id
        self.cart_items = cart_items
        self.pricing_engine: PricingEngine | None = None
        self._next_ci_seq = self._initial_ci_seq()

    def set_pricing_engine(self, pricing_engine: PricingEngine) -> None:
        self.pricing_engine = pricing_engine

    def _recompute_cart(self, cart: Cart) -> dict[str, Any]:
        assert self.pricing_engine is not None
        return self.pricing_engine.recompute_cart(cart)

    def _initial_ci_seq(self) -> int:
        max_seq = 0
        for ciid in self.cart_items:
            m = re.match(r"^CI-(\d+)$", ciid)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
        return max_seq + 1

    def next_cart_item_id(self) -> str:
        ciid = f"CI-{self._next_ci_seq:04d}"
        self._next_ci_seq += 1
        return ciid

    def resolve_cart(self, customer_id: str) -> Cart | None:
        return self.carts_by_id.get(f"CART-{customer_id}")

    def items_in_cart(self, cart: Cart) -> list[CartItem]:
        return [self.cart_items[iid] for iid in cart.item_ids if iid in self.cart_items]

    def resolve_cart_item(
        self,
        cart: Cart,
        product_id: str,
        variant_id: str | None = None,
    ) -> tuple[CartItem | None, str | None]:
        matches = [
            ci
            for ci in self.items_in_cart(cart)
            if ci.product_id == product_id and (variant_id is None or ci.variant_id == variant_id)
        ]
        if not matches:
            if variant_id is not None:
                return None, f"Product {product_id} with variant {variant_id} not in cart."
            return None, f"Product {product_id} not in cart."
        if variant_id is None and len(matches) > 1:
            variants = ", ".join(sorted(ci.variant_id or "<none>" for ci in matches))
            return None, f"Multiple variants of product {product_id} are in cart ({variants}); provide variant_id."
        return matches[0], None

    def variant_lookup(self, product: Product, variant_id: str | None) -> dict[str, Any] | None:
        """Find a variant dict on a product by id."""
        if not variant_id or not product.variants:
            return None
        for v in product.variants:
            if v.get("variant_id") == variant_id:
                return v
        return None

    def check_product_stock(
        self,
        product: Product,
        variant_id: str | None,
        requested_quantity: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if product.variants:
            if not variant_id:
                return None, (
                    f"{product.name} requires a variant selection. Check product details or variants to see options."
                )
            variant = self.variant_lookup(product, variant_id)
            if variant is None:
                return None, f"Variant '{variant_id}' not found for {product.name}."
            stock = policies.check_stock(
                bool(variant.get("in_stock", True)),
                int(variant.get("stock_quantity", 0)),
                requested_quantity,
            )
            if not stock["available"]:
                return None, stock["reason"]
            return variant, None
        if variant_id:
            return None, f"{product.name} does not have variants."
        stock = policies.check_stock(product.in_stock, product.stock_quantity, requested_quantity)
        if not stock["available"]:
            return None, stock["reason"]
        return None, None

    def add_to_cart(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        product_id = params.get("product_id", "")
        quantity = int(params.get("quantity", 1) or 1)
        gift_wrap = bool(params.get("gift_wrap", False))
        variant_id = params.get("variant_id") or None

        if quantity <= 0:
            return {"error": "quantity must be a positive integer."}

        cart = self.resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}

        product = self.products.get(product_id)
        if product is None:
            return {"error": f"Product {product_id} not found."}

        variant, stock_error = self.check_product_stock(product, variant_id, quantity)
        if stock_error:
            return {"error": stock_error}

        existing: CartItem | None = None
        for ci in self.items_in_cart(cart):
            if ci.product_id == product_id and ci.variant_id == variant_id:
                existing = ci
                break

        if existing is not None:
            final_quantity = existing.quantity + quantity
            qcheck = policies.check_quantity_limit(existing.quantity, quantity)
            if not qcheck["allowed"]:
                return {"error": qcheck["reason"]}
            _variant, stock_error = self.check_product_stock(product, variant_id, final_quantity)
            if stock_error:
                return {"error": stock_error}
            existing.quantity += quantity
            if gift_wrap:
                existing.gift_wrap = True
            adjustments = self._recompute_cart(cart)
            return {
                "status": "updated",
                "cart_item_id": existing.cart_item_id,
                "product_id": product_id,
                "product_name": product.name,
                "variant_id": existing.variant_id,
                "quantity": existing.quantity,
                "gift_wrap": existing.gift_wrap,
                "cart_subtotal": cart.subtotal,
                "cart_total": cart.total,
                **adjustments,
            }

        qcheck = policies.check_quantity_limit(0, quantity)
        if not qcheck["allowed"]:
            return {"error": qcheck["reason"]}

        if gift_wrap and not product.gift_wrap_available:
            return {"error": f"Gift wrapping is not available for {product.name}."}

        ci_id = self.next_cart_item_id()
        ci = CartItem(
            cart_item_id=ci_id,
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
            gift_wrap=gift_wrap,
            variant_id=variant_id,
        )
        self.cart_items[ci_id] = ci
        cart.item_ids.append(ci_id)
        adjustments = self._recompute_cart(cart)

        unit_price = int(product.price) + int((variant or {}).get("price_delta", 0))
        return {
            "status": "added",
            "cart_item_id": ci_id,
            "product_id": product_id,
            "product_name": product.name,
            "variant_id": variant_id,
            "quantity": quantity,
            "gift_wrap": gift_wrap,
            "unit_price": unit_price,
            "cart_subtotal": cart.subtotal,
            "cart_total": cart.total,
            **adjustments,
        }

    def update_cart_item(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        product_id = params.get("product_id", "")
        variant_id = params.get("variant_id") or None
        quantity = params.get("quantity")
        gift_wrap = params.get("gift_wrap")

        if quantity is None and gift_wrap is None:
            return {"error": "Provide at least one of quantity, gift_wrap."}

        cart = self.resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}

        ci, resolve_error = self.resolve_cart_item(cart, product_id, variant_id)
        if resolve_error:
            return {"error": resolve_error}
        assert ci is not None

        if quantity is not None:
            new_qty = int(quantity)
            if new_qty <= 0:
                args = {"customer_id": customer_id, "product_id": product_id}
                if variant_id is not None:
                    args["variant_id"] = variant_id
                return self.remove_from_cart(args)
            qcheck = policies.check_quantity_limit(0, new_qty)
            if not qcheck["allowed"]:
                return {"error": qcheck["reason"]}
            product = self.products.get(product_id)
            if product is not None:
                _variant, stock_error = self.check_product_stock(product, ci.variant_id, new_qty)
                if stock_error:
                    return {"error": stock_error}
            ci.quantity = new_qty

        if gift_wrap is not None:
            new_wrap = bool(gift_wrap)
            if new_wrap:
                product = self.products.get(product_id)
                if product is not None and not product.gift_wrap_available:
                    return {"error": f"Gift wrapping is not available for {product.name}."}
            ci.gift_wrap = new_wrap

        adjustments = self._recompute_cart(cart)
        product = self.products.get(product_id)
        return {
            "status": "updated",
            "cart_item_id": ci.cart_item_id,
            "product_id": product_id,
            "variant_id": ci.variant_id,
            "product_name": product.name if product else None,
            "quantity": ci.quantity,
            "gift_wrap": ci.gift_wrap,
            "cart_subtotal": cart.subtotal,
            "cart_total": cart.total,
            **adjustments,
        }

    def remove_from_cart(self, params: dict[str, Any]) -> dict[str, Any]:
        customer_id = params.get("customer_id", "")
        product_id = params.get("product_id", "")
        variant_id = params.get("variant_id") or None
        cart = self.resolve_cart(customer_id)
        if cart is None:
            return {"error": f"No cart for customer {customer_id}."}

        ci, resolve_error = self.resolve_cart_item(cart, product_id, variant_id)
        if resolve_error:
            return {"error": resolve_error}
        assert ci is not None

        cart.item_ids = [iid for iid in cart.item_ids if iid != ci.cart_item_id]
        self.cart_items.pop(ci.cart_item_id, None)
        adjustments = self._recompute_cart(cart)
        return {
            "status": "removed",
            "cart_id": cart.cart_id,
            "product_id": product_id,
            "variant_id": ci.variant_id,
            "cart_subtotal": cart.subtotal,
            "cart_total": cart.total,
            **adjustments,
        }
