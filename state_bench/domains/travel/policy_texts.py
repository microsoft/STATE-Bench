"""Canonical policy lookup payloads for the travel domain.

This module owns the human-readable policy responses returned by the
``get_policies`` tool. Deterministic policy calculations stay in
``travel.policies``.
"""

from __future__ import annotations

from typing import Any

from state_bench.domains.travel import policies

VALID_POLICY_TOPICS: tuple[str, ...] = (
    "cancel",
    "cancellation",
    "change",
    "baggage",
    "delay_compensation",
    "loyalty",
    "points",
    "upgrade",
    "hotel_cancel",
    "car_rental_cancel",
)


def get_policy_text(params: dict[str, Any]) -> dict[str, Any]:
    """Return the policy payload for ``get_policies`` without mutating state."""
    topic = params.get("topic", "")
    cabin_class = params.get("cabin_class", "economy")
    loyalty_tier = params.get("loyalty_tier", "basic")
    route_type = params.get("route_type", "domestic")

    if topic == "cancel" or topic == "cancellation":
        rules: dict[str, str] = {
            "free_cancellation_window": (
                "Full refund within 24 hours (domestic) or 48 hours (international) of booking"
            ),
            "basic_economy": "Not cancellable after free window (unless insured)",
            "economy_domestic": "Cancellation fee: max($50, 15% of ticket price)",
            "economy_international": "Cancellation fee: max($75, 20% of ticket price)",
            "business_domestic": "Cancellation fee: 5% of ticket price",
            "business_international": "Cancellation fee: 8% of ticket price",
            "first": "Free cancellation",
            "insurance": "Travel insurance covers cancellation regardless of cabin class",
            "route_type_matters": "Fees differ by route type (domestic vs international). Check flight route_type.",
        }
        return {
            "topic": "cancellation",
            "rules": rules,
            "applicable_cabin_class": cabin_class,
            "applicable_route_type": route_type,
        }
    if topic == "change":
        return {
            "topic": "change",
            "rules": {
                "free_change_window": (
                    "Free changes within 24 hours (domestic) or 48 hours (international) of booking"
                ),
                "basic_economy": "Not changeable after free window",
                "economy_domestic_personal": (
                    "Domestic change fee: $75 if departure >7 days, $150 if ≤7 days. Fare difference also applies."
                ),
                "economy_international_personal": (
                    "International change fee: $100 if departure >7 days, $200 if ≤7 days. Fare difference also applies."
                ),
                "economy_medical": "Medical changes: 50% discount on standard fee (requires change_reason='medical')",
                "economy_bereavement": (
                    "Bereavement changes: 75% discount on standard fee (requires change_reason='bereavement')"
                ),
                "jury_duty": "Jury duty: free change (change_reason='jury_duty')",
                "military": "Military deployment: free change (change_reason='military')",
                "schedule_change": "Airline schedule changes: free, no fee (change_reason='schedule_change')",
                "weather": "Weather-related changes: free, no fee (change_reason='weather')",
                "business": "Free changes (fare difference still applies)",
                "first": "Free changes (fare difference still applies)",
                "change_reason_required": (
                    "Pass change_reason parameter: 'personal', 'medical', 'bereavement', "
                    "'jury_duty', 'military', 'schedule_change', or 'weather'"
                ),
                "route_type_matters": "Fees differ by route type. Check flight route_type.",
            },
            "applicable_cabin_class": cabin_class,
            "applicable_route_type": route_type,
        }
    if topic == "baggage":
        return policies.get_baggage_allowance(cabin_class, loyalty_tier)
    if topic == "delay_compensation":
        return {
            "topic": "delay_compensation",
            "rules": {
                "under_2_hours": "No compensation",
                "2_to_4_hours": "$25 meal voucher",
                "over_4_hours": "Rebooking + $25 meal voucher + hotel (if overnight)",
                "overnight_delay": "If delay causes overnight stay, hotel voucher + $50 incidentals provided",
            },
        }
    if topic == "loyalty" or topic == "points":
        return {
            "topic": "loyalty_points",
            "rules": {
                "minimum_redemption": "1,000 points minimum to redeem",
                "domestic_rate": "1 point = $0.01 (100 points = $1)",
                "international_rate": "1 point = $0.015 (100 points = $1.50)",
                "rounding": "Points used are rounded to the nearest 100",
                "max_coverage": "Points can cover up to 100% of flight price",
            },
            "applicable_loyalty_tier": loyalty_tier,
            "applicable_route_type": route_type,
        }
    if topic == "upgrade":
        return {
            "topic": "upgrade",
            "rules": {
                "economy_to_business": "Upgrade fee = target cabin listed price minus amount already paid",
                "business_to_first": "Upgrade fee = target cabin listed price minus amount already paid",
                "economy_to_first": "Not available directly (must upgrade to business first)",
                "basic_economy": "Not eligible for upgrades",
            },
            "applicable_cabin_class": cabin_class,
        }
    if topic == "hotel_cancel":
        return {
            "topic": "hotel_cancellation",
            "rules": {
                "standard_room_48h_plus": "Free cancellation if 48+ hours before check-in",
                "standard_room_24_48h": "50% of first night charge if 24-48 hours before check-in",
                "standard_room_under_24h": "Full first night charge if <24 hours before check-in",
                "suite": "Suite bookings are non-refundable (full charge regardless of timing)",
            },
        }
    if topic == "car_rental_cancel":
        return {
            "topic": "car_rental_cancellation",
            "rules": {
                "24h_plus": "Free cancellation if 24+ hours before pickup",
                "under_24h": "One day charge if <24 hours before pickup",
                "luxury_suv_surcharge": "Luxury and SUV rentals incur an additional $50 cancellation surcharge at all times",
            },
        }
    return {"error": f"Unknown policy topic: {topic}."}
