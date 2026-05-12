"""Read-only catalog search, product details, variants, and compatibility."""

from __future__ import annotations

import re
from typing import Any, Callable

from state_bench.domains.shopping_assistant.schemas import Product

SEARCH_TOP_N: int = 10
QUERY_TOKEN_WEIGHT: int = 2
QUERY_NAME_BRAND_BOOST: int = 5


def norm_token(s: str) -> str:
    """Lowercase + collapse hyphens/spaces to underscores."""
    return s.lower().replace("-", "_").replace(" ", "_")


def tokenize(s: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop empties and length-1 tokens."""
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) > 1]


def build_searchable_text(p: Product) -> str:
    """Compose a normalized text blob over which queries rank."""
    parts: list[str] = [p.name.lower(), (p.brand or "").lower()]
    if p.subcategory:
        parts.append(p.subcategory.lower().replace("_", " "))
        parts.append(norm_token(p.subcategory))
    if p.description:
        parts.append(p.description.lower())
    for spec_key, spec_val in p.specs.items():
        parts.append(spec_key.lower().replace("_", " "))
        parts.append(norm_token(spec_key))
        sval = str(spec_val)
        if not re.match(r"^\s*\d", sval):
            parts.append(sval.lower())
    return " ".join(parts)


class CatalogSearch:
    """Read-only catalog product operations."""

    def __init__(
        self,
        *,
        products: dict[str, Product],
        variant_lookup: Callable[[Product, str | None], dict[str, Any] | None],
    ) -> None:
        self.products = products
        self._variant_lookup = variant_lookup

    def search_products(self, params: dict[str, Any]) -> dict[str, Any]:
        query = (params.get("query") or "").strip()
        category = params.get("category")
        min_price = params.get("min_price")
        max_price = params.get("max_price")
        min_rating = params.get("min_rating")
        in_stock_only = bool(params.get("in_stock_only", False))
        sort_by = params.get("sort_by", "relevance")

        candidates: list[Product] = []
        for p in self.products.values():
            if category and p.category != category:
                continue
            if min_price is not None and p.price < int(min_price):
                continue
            if max_price is not None and p.price > int(max_price):
                continue
            if min_rating is not None and p.rating < float(min_rating):
                continue
            if in_stock_only and not p.in_stock:
                continue
            candidates.append(p)

        if not candidates:
            return {
                "products": [],
                "total_found": 0,
                "note": (
                    "No products match the hard filters "
                    "(category / price / rating / stock). "
                    "Try relaxing them and search again."
                ),
            }

        query_tokens = tokenize(query) if query else []

        scored: list[tuple[int, Product]] = []
        for p in candidates:
            text = build_searchable_text(p)
            score = 0
            if query_tokens:
                hits = sum(1 for tok in query_tokens if re.search(rf"\b{re.escape(tok)}\b", text))
                score += hits * QUERY_TOKEN_WEIGHT
                name_brand = f"{p.name.lower()} {(p.brand or '').lower()}"
                nb_hits = sum(1 for tok in query_tokens if re.search(rf"\b{re.escape(tok)}\b", name_brand))
                score += nb_hits * QUERY_NAME_BRAND_BOOST
            scored.append((score, p))

        if query_tokens:
            scored = [(s, p) for s, p in scored if s > 0]
            if not scored:
                return {
                    "products": [],
                    "total_found": 0,
                    "note": (f"No products match the query '{query}'. Try broader or different keywords."),
                }

        if sort_by == "price_low":
            scored.sort(key=lambda x: x[1].price)
        elif sort_by == "price_high":
            scored.sort(key=lambda x: -x[1].price)
        elif sort_by == "rating":
            scored.sort(key=lambda x: -x[1].rating)
        elif sort_by == "review_count":
            scored.sort(key=lambda x: -x[1].review_count)
        else:
            scored.sort(key=lambda x: (-x[0], -x[1].rating))

        results = [
            {
                "product_id": p.product_id,
                "name": p.name,
                "brand": p.brand,
                "category": p.category,
                "subcategory": p.subcategory,
                "price": p.price,
                "rating": p.rating,
                "review_count": p.review_count,
                "in_stock": p.in_stock,
            }
            for _, p in scored[:SEARCH_TOP_N]
        ]
        return {"products": results, "total_found": len(scored)}

    def get_product_details(self, params: dict[str, Any]) -> dict[str, Any]:
        product_id = params.get("product_id", "")
        product = self.products.get(product_id)
        if not product:
            return {"error": f"Product {product_id} not found."}
        result = product.to_dict()
        result["shipping_estimate"] = f"{product.shipping_days} business days (standard)"
        return result

    def get_variants(self, params: dict[str, Any]) -> dict[str, Any]:
        product_id = params.get("product_id", "")
        product = self.products.get(product_id)
        if not product:
            return {"error": f"Product {product_id} not found."}
        if not product.variants:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "base_price": product.price,
                "variants": [],
                "note": "This product has no variants; no variant_id is needed for add_to_cart.",
            }
        return {
            "product_id": product_id,
            "product_name": product.name,
            "base_price": product.price,
            "variants": [
                {
                    "variant_id": v["variant_id"],
                    "label": v.get("label", ""),
                    "effective_price": product.price + int(v.get("price_delta", 0)),
                    "in_stock": bool(v.get("in_stock", True)),
                    "stock_quantity": int(v.get("stock_quantity", 0)),
                }
                for v in product.variants
            ],
        }


class CompatibilityService:
    """Read-only product compatibility checks."""

    def __init__(self, *, products: dict[str, Product]) -> None:
        self.products = products
        self.canonical_devices: list[str] = sorted({d for p in self.products.values() for d in p.compatible_with})

    def check_compatibility(self, params: dict[str, Any]) -> dict[str, Any]:
        product_id = params.get("product_id", "")
        device_name = (params.get("device_name") or "").strip()
        product = self.products.get(product_id)
        if not product:
            return {"error": f"Product {product_id} not found."}

        device_lower = device_name.lower()
        for compat in product.compatible_with:
            if compat.lower() == device_lower:
                return {
                    "compatible": True,
                    "product_id": product_id,
                    "device": compat,
                    "reason": f"{product.name} is compatible with {compat}.",
                }

        device_known = any(d.lower() == device_lower for d in self.canonical_devices)
        if device_known:
            return {
                "compatible": False,
                "product_id": product_id,
                "device": device_name,
                "reason": (
                    f"{product.name} is not compatible with {device_name}. "
                    f"Compatible devices for this product: "
                    f"{', '.join(product.compatible_with) if product.compatible_with else 'none listed'}."
                ),
            }
        return {
            "compatible": False,
            "product_id": product_id,
            "device": device_name,
            "reason": (
                f"Unknown device name '{device_name}'. "
                f"Canonical devices in this catalog: "
                f"{', '.join(self.canonical_devices) if self.canonical_devices else 'none'}."
            ),
            "canonical_devices": list(self.canonical_devices),
        }
