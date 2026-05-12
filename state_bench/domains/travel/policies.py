"""Deterministic policy engine for the travel environment.

All rules are hard-coded and return structured results.
Tool handlers consult these functions before executing mutations.
"""

from datetime import datetime, timedelta
from typing import Any


def check_cancellation_policy(
    cabin_class: str,
    booked_at: str,
    now: str,
    has_insurance: bool,
    airline_cancelled: bool = False,
    price_paid: int = 0,
    route_type: str = "domestic",
) -> dict[str, Any]:
    """Check if a booking can be cancelled and compute the refund.

    Rules:
    - Airline-initiated cancellation: full refund regardless of cabin class
    - Within free cancellation window (24h domestic, 48h international): full refund
    - basic_economy after window: not cancellable (unless insured)
    - economy after window: domestic max($50, 15%), international max($75, 20%)
    - business after window: domestic 5%, international 8%
    - first after window: free cancellation
    - Insurance overrides: if insured, full refund regardless
    """
    if airline_cancelled:
        return {"eligible": True, "fee": 0, "reason": "Airline-initiated cancellation: full refund"}

    booked = datetime.fromisoformat(booked_at)
    current = datetime.fromisoformat(now)

    free_window_hours = 48 if route_type == "international" else 24
    within_window = (current - booked) < timedelta(hours=free_window_hours)

    if within_window:
        return {
            "eligible": True,
            "fee": 0,
            "reason": f"Within {free_window_hours}-hour free cancellation window",
        }

    if has_insurance:
        return {"eligible": True, "fee": 0, "reason": "Travel insurance covers cancellation"}

    if cabin_class == "basic_economy":
        return {
            "eligible": False,
            "fee": 0,
            "reason": f"Basic economy fares cannot be cancelled after the {free_window_hours}-hour window",
        }
    elif cabin_class == "economy":
        if route_type == "international":
            fee = max(75, int(price_paid * 0.20))
            return {
                "eligible": True,
                "fee": fee,
                "reason": f"International economy cancellation fee: max($75, 20% of ${price_paid}) = ${fee}",
            }
        else:
            fee = max(50, int(price_paid * 0.15))
            return {
                "eligible": True,
                "fee": fee,
                "reason": f"Economy cancellation fee: max($50, 15% of ${price_paid}) = ${fee}",
            }
    elif cabin_class == "business":
        if route_type == "international":
            fee = int(price_paid * 0.08)
            return {
                "eligible": True,
                "fee": fee,
                "reason": f"International business cancellation fee: 8% of ${price_paid} = ${fee}",
            }
        else:
            fee = int(price_paid * 0.05)
            return {"eligible": True, "fee": fee, "reason": f"Business cancellation fee: 5% of ${price_paid} = ${fee}"}
    elif cabin_class == "first":
        return {"eligible": True, "fee": 0, "reason": "First class: free cancellation"}

    return {"eligible": False, "fee": 0, "reason": f"Unknown cabin class: {cabin_class}"}


def check_change_policy(
    cabin_class: str,
    booked_at: str,
    now: str,
    has_insurance: bool,
    departure_date: str = "",
    change_reason: str = "personal",
    route_type: str = "domestic",
) -> dict[str, Any]:
    """Check if a booking can be changed (flight swap) and compute the fee.

    Rules:
    - Within free window (24h domestic, 48h international): free change
    - basic_economy: no changes allowed
    - Reason-based fee modifiers:
      - 'schedule_change' (airline-initiated): free, no fee regardless
      - 'personal': standard fee (economy domestic: $75 if >7d, $150 if <=7d;
                                   economy international: $100 if >7d, $200 if <=7d)
      - 'medical': 50% of standard fee
      - 'bereavement': 75% discount on standard fee
      - 'jury_duty': free change
      - 'military': free change
      - 'weather': free
    - business/first: free changes for any reason
    - Insurance does NOT waive change fees (only covers cancellation)
    """
    booked = datetime.fromisoformat(booked_at)
    current = datetime.fromisoformat(now)

    free_window_hours = 48 if route_type == "international" else 24
    within_window = (current - booked) < timedelta(hours=free_window_hours)

    if within_window:
        return {
            "eligible": True,
            "fee": 0,
            "reason": f"Within {free_window_hours}-hour free change window",
        }

    # Airline-initiated schedule change, weather, jury duty, military: always free
    if change_reason in ("schedule_change", "weather", "jury_duty", "military"):
        return {
            "eligible": True,
            "fee": 0,
            "reason": f"Free change: {change_reason} (exempt category)",
        }

    rules: dict[str, dict[str, Any]] = {
        "basic_economy": {
            "eligible": False,
            "fee": 0,
            "reason": f"Basic economy fares cannot be changed after the {free_window_hours}-hour window",
        },
        "business": {"eligible": True, "fee": 0, "reason": "Business class: free changes"},
        "first": {"eligible": True, "fee": 0, "reason": "First class: free changes"},
    }

    if cabin_class in rules:
        return rules[cabin_class]

    # Economy: time-based fee with route and reason modifiers
    if cabin_class == "economy":
        if departure_date:
            dep = (
                datetime.fromisoformat(departure_date)
                if "T" in departure_date
                else datetime.fromisoformat(departure_date + "T00:00:00")
            )
            days_to_departure = (dep - current).days
        else:
            days_to_departure = 999

        # Route-dependent base fees
        if route_type == "international":
            base_fee = 200 if days_to_departure <= 7 else 100
        else:
            base_fee = 150 if days_to_departure <= 7 else 75

        # Reason-based fee modifiers
        if change_reason == "medical":
            fee = base_fee // 2
            reason = f"Economy change fee (medical, {route_type}): ${fee} (50% of ${base_fee})"
        elif change_reason == "bereavement":
            fee = base_fee // 4  # 75% discount = pay 25%
            reason = f"Economy change fee (bereavement, {route_type}): ${fee} (75% discount on ${base_fee})"
        else:
            fee = base_fee
            reason = f"Economy change fee ({route_type}): ${fee} ({days_to_departure} days to departure)"

        return {"eligible": True, "fee": fee, "reason": reason}

    return {"eligible": False, "fee": 0, "reason": f"Unknown cabin class: {cabin_class}"}


def get_baggage_allowance(
    cabin_class: str,
    loyalty_tier: str,
) -> dict[str, Any]:
    """Get baggage allowance based on cabin class and loyalty tier.

    Rules:
    - All passengers: 1 free carry-on
    - Checked bags by cabin class: basic_economy=0, economy=1, business=2, first=3
    - Loyalty bonus checked bags: silver=+1, gold=+2, platinum=+3
    - Extra checked bag fee: $50 per bag (basic_economy), $35 per bag (all others)
    - Oversized bags: $100 per bag
    """
    carry_on = 1
    checked_by_cabin: dict[str, int] = {
        "basic_economy": 0,
        "economy": 1,
        "business": 2,
        "first": 3,
    }
    loyalty_bonus: dict[str, int] = {
        "basic": 0,
        "silver": 1,
        "gold": 2,
        "platinum": 3,
    }

    base_checked = checked_by_cabin.get(cabin_class, 1)
    bonus = loyalty_bonus.get(loyalty_tier, 0)
    total_checked = base_checked + bonus

    extra_bag_fee = 50 if cabin_class == "basic_economy" else 35

    return {
        "topic": "baggage",
        "carry_on": carry_on,
        "base_checked_bags": base_checked,
        "loyalty_bonus_checked_bags": bonus,
        "checked_bags_free": total_checked,
        "checked_bag_fee": extra_bag_fee,
        "oversized_bag_fee": 100,
        "cabin_class": cabin_class,
        "loyalty_tier": loyalty_tier,
    }


def check_delay_compensation(
    delay_minutes: int,
) -> dict[str, Any]:
    """Check compensation eligibility based on delay duration.

    Rules:
    - < 120 minutes: no compensation
    - 120-239 minutes: meal voucher ($25)
    - 240+ minutes: rebooking + meal voucher + hotel (if overnight)
    """
    if delay_minutes < 120:
        return {
            "eligible": False,
            "compensation": "none",
            "reason": f"Delay of {delay_minutes} minutes does not meet the 2-hour threshold for compensation",
        }
    elif delay_minutes < 240:
        return {
            "eligible": True,
            "compensation": "meal_voucher",
            "voucher_amount": 25,
            "reason": f"Delay of {delay_minutes} minutes qualifies for a $25 meal voucher",
        }
    else:
        return {
            "eligible": True,
            "compensation": "full",
            "voucher_amount": 25,
            "rebooking": True,
            "hotel": True,
            "reason": f"Delay of {delay_minutes} minutes qualifies for rebooking, meal voucher, and hotel accommodation",
        }


def check_loyalty_point_redemption(
    loyalty_tier: str,
    loyalty_points: int,
    flight_price: int,
    route_type: str = "domestic",
) -> dict[str, Any]:
    """Check loyalty point redemption eligibility and calculate value.

    Rules:
    - Minimum 1,000 points to redeem
    - Domestic: 1 point = $0.01 (100 points = $1)
    - International: 1 point = $0.015 (100 points = $1.50)
    - Points used are rounded to nearest 100 (ensuring whole dollar amounts)
    - Cannot exceed flight price; remainder stays as points
    """
    if loyalty_points < 1000:
        return {
            "eligible": False,
            "reason": f"Need minimum 1,000 points to redeem. Current balance: {loyalty_points}",
            "points_available": loyalty_points,
        }

    # Redemption rate based on route type
    if route_type == "international":
        dollar_per_point = 0.015
        rate_description = "1 point = $0.015 (international rate)"
    else:
        dollar_per_point = 0.01
        rate_description = "1 point = $0.01 (domestic rate)"

    max_dollar_value = loyalty_points * dollar_per_point

    # Cap at flight price (no overcoverage)
    applied_value = min(max_dollar_value, float(flight_price))

    # Calculate points used and round to nearest 100
    points_used = int(applied_value / dollar_per_point)
    points_used = round(points_used, -2)  # round to nearest 100

    # Recalculate applied value from rounded points
    applied_value = points_used * dollar_per_point
    applied_value = min(applied_value, float(flight_price))
    remaining_cash = round(flight_price - applied_value, 2)

    return {
        "eligible": True,
        "loyalty_tier": loyalty_tier,
        "points_available": loyalty_points,
        "points_used": points_used,
        "dollar_value": applied_value,
        "remaining_cash_payment": remaining_cash,
        "redemption_rate": rate_description,
    }


def check_upgrade_eligibility(
    current_cabin: str,
    target_cabin: str,
    cabin_class: str,
    flight_price: int,
) -> dict[str, Any]:
    """Check if a booking can be upgraded and compute the fare difference.

    Rules:
    - economy -> business: upgrade fee is 2.5x base price minus already paid
    - economy -> first: not available (must upgrade through business first)
    - business -> first: upgrade fee is 1.8x base price minus already paid
    - basic_economy: no upgrades allowed
    """
    if cabin_class == "basic_economy":
        return {
            "eligible": False,
            "reason": "Basic economy fares are not eligible for upgrades",
        }

    upgrade_multipliers: dict[tuple[str, str], float] = {
        ("economy", "business"): 2.5,
        ("economy", "first"): 0,  # not directly available
        ("business", "first"): 1.8,
    }

    key = (current_cabin, target_cabin)
    multiplier = upgrade_multipliers.get(key, 0)

    if multiplier == 0:
        if current_cabin == target_cabin:
            return {"eligible": False, "reason": f"Already in {current_cabin} class"}
        return {
            "eligible": False,
            "reason": f"Direct upgrade from {current_cabin} to {target_cabin} is not available",
        }

    upgrade_price = int(flight_price * multiplier)
    fare_difference = upgrade_price - flight_price

    # Eligibility is multiplier-gated, but executable upgrade pricing uses
    # the target cabin listed price minus the amount already paid.
    return {
        "eligible": True,
        "current_cabin": current_cabin,
        "target_cabin": target_cabin,
        "fare_difference": fare_difference,
        "new_total_price": upgrade_price,
        "reason": f"Upgrade from {current_cabin} to {target_cabin} is eligible; quote the target cabin listed price minus amount already paid.",
    }


# ---------------------------------------------------------------------------
# Hotel cancellation policy
# ---------------------------------------------------------------------------


def check_hotel_cancellation_policy(
    room_type: str,
    check_in: str,
    now: str,
    nightly_rate: int,
    total_price: int,
) -> dict[str, Any]:
    """Check hotel cancellation eligibility and fee.

    Rules:
    - Suite bookings: non-refundable (full charge)
    - Standard rooms:
      - 48h+ before check-in: free cancellation
      - 24-48h before check-in: 50% of first night
      - <24h before check-in: full first night charge
    """
    now_dt = datetime.fromisoformat(now)
    check_in_dt = datetime.fromisoformat(check_in + "T15:00:00")  # assume 3pm check-in
    hours_until = (check_in_dt - now_dt).total_seconds() / 3600

    if room_type == "suite":
        return {
            "eligible": True,
            "fee": total_price,
            "refund": 0,
            "reason": "Suite bookings are non-refundable.",
        }

    if hours_until >= 48:
        return {
            "eligible": True,
            "fee": 0,
            "refund": total_price,
            "reason": "Free cancellation (48+ hours before check-in).",
        }
    elif hours_until >= 24:
        fee = nightly_rate // 2
        return {
            "eligible": True,
            "fee": fee,
            "refund": total_price - fee,
            "reason": f"50% of first night charge (24-48h before check-in): ${fee}.",
        }
    else:
        fee = nightly_rate
        return {
            "eligible": True,
            "fee": fee,
            "refund": total_price - fee,
            "reason": f"Full first night charge (<24h before check-in): ${fee}.",
        }


# ---------------------------------------------------------------------------
# Car rental cancellation policy
# ---------------------------------------------------------------------------


def check_car_rental_cancellation_policy(
    car_class: str,
    pickup_date: str,
    now: str,
    daily_rate: int,
    total_price: int,
) -> dict[str, Any]:
    """Check car rental cancellation eligibility and fee.

    Rules:
    - 24h+ before pickup: free cancellation
    - <24h before pickup: one day charge
    - Luxury/SUV: additional $50 surcharge at all times
    """
    now_dt = datetime.fromisoformat(now)
    pickup_dt = datetime.fromisoformat(pickup_date + "T10:00:00")  # assume 10am pickup
    hours_until = (pickup_dt - now_dt).total_seconds() / 3600

    surcharge = 50 if car_class in ("luxury", "suv") else 0

    if hours_until >= 24:
        fee = surcharge
        return {
            "eligible": True,
            "fee": fee,
            "refund": total_price - fee,
            "reason": f"Free cancellation (24+ hours before pickup){f' + ${surcharge} {car_class} surcharge' if surcharge else ''}.",
        }
    else:
        fee = daily_rate + surcharge
        return {
            "eligible": True,
            "fee": fee,
            "refund": total_price - fee,
            "reason": f"One day charge (<24h before pickup): ${daily_rate}{f' + ${surcharge} {car_class} surcharge' if surcharge else ''}.",
        }
