"""Travel domain data models.

Domain-specific database records and environment data for the travel benchmark.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from state_bench.schemas import DictMixin

# ---------------------------------------------------------------------------
# Database records
# ---------------------------------------------------------------------------


@dataclass
class Flight(DictMixin):
    flight_id: str  # primary key, e.g. "DL401"
    airline_code: str
    origin: str
    destination: str
    departure_time: str  # ISO format
    arrival_time: str
    duration_minutes: int
    stops: int
    cabin_prices: dict[str, int] = field(default_factory=dict)  # e.g. {"economy": 350, "business": 875}
    status: str = "scheduled"  # scheduled | delayed | cancelled
    delay_minutes: int = 0
    route_type: str = "domestic"  # domestic | international


@dataclass
class Booking(DictMixin):
    booking_id: str
    user_id: str
    flight_id: str
    status: str = "confirmed"  # confirmed | cancelled | changed
    cabin_class: str | None = None
    seat_type: str | None = None
    meal_preference: str | None = None
    add_wifi: bool | None = None
    add_extra_legroom: bool | None = None
    add_insurance: bool | None = None
    price_paid: int = 0
    payment_method: str = "credit_card"  # credit_card | points | points_plus_cash
    points_used: int = 0
    cash_amount: int = 0
    booked_at: str = ""  # ISO format
    cancellation_fee: int | None = None
    refund_amount: int | None = None
    change_fee: int | None = None
    fare_difference: int | None = None
    delay_compensation: str | None = None  # none | meal_voucher | full
    paid_checked_bags: int = 0


@dataclass
class User(DictMixin):
    user_id: str
    name: str
    email: str
    loyalty_tier: str = "basic"  # basic | silver | gold | platinum
    loyalty_points: int = 0
    budget: int = 1000
    preferences: dict[str, Any] = field(
        default_factory=lambda: {
            "meal_preference": "standard",
            "seat_type": "aisle",
            "add_wifi": False,
            "add_extra_legroom": False,
            "add_insurance": False,
        }
    )


@dataclass
class HotelInventoryItem(DictMixin):
    hotel_id: str  # inventory key, e.g. "HOTEL-0001"
    hotel_name: str
    city: str  # destination city / airport area code
    check_in: str  # ISO date YYYY-MM-DD
    check_out: str  # ISO date YYYY-MM-DD
    room_type: str  # "standard" | "suite"
    nightly_rate: int
    total_price: int


@dataclass
class HotelReservation(DictMixin):
    reservation_id: str  # e.g. "HR-0001"
    user_id: str
    hotel_name: str
    city: str  # destination city (maps to airport code area)
    check_in: str  # ISO date YYYY-MM-DD
    check_out: str  # ISO date YYYY-MM-DD
    room_type: str  # "standard" | "suite"
    nightly_rate: int
    total_price: int
    hotel_id: str | None = None
    status: str = "confirmed"  # confirmed | cancelled
    booked_at: str = ""  # ISO format
    cancellation_fee: int | None = None
    refund_amount: int | None = None


@dataclass
class CarInventoryItem(DictMixin):
    car_id: str  # inventory key, e.g. "CAR-0001"
    company: str  # "Hertz" | "Enterprise" | "Avis"
    pickup_location: str  # airport code
    dropoff_location: str  # airport code (same or different)
    pickup_date: str  # ISO date YYYY-MM-DD
    dropoff_date: str  # ISO date YYYY-MM-DD
    car_class: str  # "economy" | "midsize" | "compact" | "suv" | "luxury"
    daily_rate: int
    total_price: int
    insurance_included: bool = False


@dataclass
class CarRental(DictMixin):
    rental_id: str  # e.g. "CR-0001"
    user_id: str
    company: str  # "Hertz" | "Enterprise" | "Avis"
    pickup_location: str  # airport code
    dropoff_location: str  # airport code (same or different)
    pickup_date: str  # ISO date YYYY-MM-DD
    dropoff_date: str  # ISO date YYYY-MM-DD
    car_class: str  # "economy" | "midsize" | "suv" | "luxury"
    daily_rate: int
    total_price: int
    car_id: str | None = None
    status: str = "confirmed"  # confirmed | cancelled
    insurance_included: bool = False
    booked_at: str = ""  # ISO format
    cancellation_fee: int | None = None
    refund_amount: int | None = None


# ---------------------------------------------------------------------------
# Environment snapshot (loaded from JSON, deep-copied per task run)
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentData:
    """Full environment state: flights, bookings, users, hotels, car rentals."""

    flights: list[Flight]
    bookings: list[Booking]
    users: list[User]
    hotel_inventory: list[HotelInventoryItem] = field(default_factory=list)
    hotels: list[HotelReservation] = field(default_factory=list)
    car_inventory: list[CarInventoryItem] = field(default_factory=list)
    car_rentals: list[CarRental] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flights": [f.to_dict() for f in self.flights],
            "bookings": [b.to_dict() for b in self.bookings],
            "users": [u.to_dict() for u in self.users],
            "hotel_inventory": [h.to_dict() for h in self.hotel_inventory],
            "hotels": [h.to_dict() for h in self.hotels],
            "car_inventory": [c.to_dict() for c in self.car_inventory],
            "car_rentals": [c.to_dict() for c in self.car_rentals],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnvironmentData:
        return cls(
            flights=[Flight.from_dict(f) for f in data["flights"]],
            bookings=[Booking.from_dict(b) for b in data["bookings"]],
            users=[User.from_dict(u) for u in data["users"]],
            hotel_inventory=[HotelInventoryItem.from_dict(h) for h in data.get("hotel_inventory", [])],
            hotels=[HotelReservation.from_dict(h) for h in data.get("hotels", [])],
            car_inventory=[CarInventoryItem.from_dict(c) for c in data.get("car_inventory", [])],
            car_rentals=[CarRental.from_dict(c) for c in data.get("car_rentals", [])],
        )

    def deep_copy(self) -> EnvironmentData:
        return EnvironmentData.from_dict(copy.deepcopy(self.to_dict()))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        print(
            f"Saved environment: {len(self.flights)} flights, {len(self.bookings)} bookings, {len(self.users)} users → {path}"
        )

    @classmethod
    def load(cls, path: Path) -> EnvironmentData:
        with open(path) as f:
            return cls.from_dict(json.load(f))
