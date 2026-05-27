import json
from datetime import date, datetime, timedelta
from pathlib import Path

from state_bench.protocol import load_default_protocol, load_split_manifest


def _domain_tasks(domain: str) -> list[Path]:
    return sorted(Path(f"state_bench/domains/{domain}/tasks").glob("*.json"))


def _domain_envs(domain: str) -> list[Path]:
    return sorted(Path(f"state_bench/domains/{domain}/task_envs").glob("*.json"))


def test_all_domains_have_task_env_and_state_requirements_metadata() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        for task_path in _domain_tasks(domain):
            task = json.loads(task_path.read_text())
            assert task.get("task_env_path") == f"state_bench/domains/{domain}/task_envs/{task_path.stem}.json", (
                task_path.name
            )
            assert "state_requirements" in task, task_path.name
            assert task["state_requirements"] is not None, task_path.name


def test_all_domains_have_matching_task_and_env_sets() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        task_ids = [path.stem for path in _domain_tasks(domain)]
        env_ids = [path.stem for path in _domain_envs(domain)]
        split_version = load_default_protocol().split_version
        manifest = load_split_manifest(domain, split_version)
        all_split_ids = set(manifest["splits"]["train"]) | set(manifest["splits"]["test"])

        assert set(task_ids) == all_split_ids, domain
        assert set(env_ids) == all_split_ids, domain


def test_public_task_and_env_ids_match_test_split() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        split_version = load_default_protocol().split_version
        manifest = load_split_manifest(domain, split_version)
        all_split_ids = set(manifest["splits"]["train"]) | set(manifest["splits"]["test"])

        assert {path.stem for path in _domain_tasks(domain)} == all_split_ids, domain
        assert {path.stem for path in _domain_envs(domain)} == all_split_ids, domain


def test_split_manifests_only_contain_train_test_task_ids() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        split_version = load_default_protocol().split_version
        raw_manifest = json.loads(Path(f"state_bench/domains/{domain}/splits/{split_version}.json").read_text())
        manifest = load_split_manifest(domain, split_version)
        task_ids = {path.stem for path in _domain_tasks(domain)}
        env_ids = {path.stem for path in _domain_envs(domain)}
        train = manifest["splits"]["train"]
        test = manifest["splits"]["test"]

        assert set(raw_manifest) == {"splits"}
        assert set(manifest) == {"splits", "version"}
        assert set(manifest["splits"]) == {"train", "test"}
        assert len(train) == 100
        assert len(test) == 50
        assert set(train).isdisjoint(test)
        assert set(train) | set(test) == task_ids
        assert set(train) | set(test) == env_ids


def test_split_entries_have_checked_in_task_and_env_files() -> None:
    for domain in ("travel", "customer_support", "shopping_assistant"):
        split_version = load_default_protocol().split_version
        manifest = load_split_manifest(domain, split_version)
        root = Path("state_bench/domains") / domain

        for task_id in [*manifest["splits"]["train"], *manifest["splits"]["test"]]:
            task_path = root / "tasks" / f"{task_id}.json"
            assert task_path.is_file(), f"{domain} split missing task file: {task_id}"

        for task_id in [*manifest["splits"]["train"], *manifest["splits"]["test"]]:
            env_path = root / "task_envs" / f"{task_id}.json"
            assert env_path.is_file(), f"{domain} split missing task env file: {task_id}"


def test_travel_task_env_dates_are_chronological() -> None:
    for env_path in _domain_envs("travel"):
        env = json.loads(env_path.read_text())
        flights_by_id = {flight["flight_id"]: flight for flight in env.get("flights", [])}

        for flight in env.get("flights", []):
            flight_id = flight["flight_id"]
            departure = datetime.fromisoformat(flight["departure_time"])
            arrival = datetime.fromisoformat(flight["arrival_time"])
            assert arrival > departure, f"{env_path.name}: {flight_id} arrives before departure"

        for booking in env.get("bookings", []):
            flight = flights_by_id[booking["flight_id"]]
            booked_at = datetime.fromisoformat(booking["booked_at"])
            departure = datetime.fromisoformat(flight["departure_time"])
            assert booked_at <= departure, f"{env_path.name}: {booking['booking_id']} booked after departure"

        for hotel in env.get("hotels", []):
            reservation_id = hotel["reservation_id"]
            check_in = date.fromisoformat(hotel["check_in"])
            check_out = date.fromisoformat(hotel["check_out"])
            assert check_out > check_in, f"{env_path.name}: {reservation_id} checks out before check-in"
            if hotel.get("booked_at"):
                assert datetime.fromisoformat(hotel["booked_at"]).date() <= check_in, (
                    f"{env_path.name}: {reservation_id} booked after check-in"
                )

        for rental in env.get("car_rentals", []):
            rental_id = rental["rental_id"]
            pickup = date.fromisoformat(rental["pickup_date"])
            dropoff = date.fromisoformat(rental["dropoff_date"])
            assert dropoff > pickup, f"{env_path.name}: {rental_id} drops off before pickup"
            if rental.get("booked_at"):
                assert datetime.fromisoformat(rental["booked_at"]).date() <= pickup, (
                    f"{env_path.name}: {rental_id} booked after pickup"
                )


def test_travel_exact_seven_day_boundary_tasks_match_task_text() -> None:
    for task_path in _domain_tasks("travel"):
        task = json.loads(task_path.read_text())
        task_text = json.dumps(task).lower()
        if "exactly seven days" not in task_text:
            continue

        env = json.loads(Path(task["task_env_path"]).read_text())
        flights_by_id = {flight["flight_id"]: flight for flight in env.get("flights", [])}
        original_booking = next(booking for booking in env.get("bookings", []) if booking["user_id"] == task["user_id"])
        departure = datetime.fromisoformat(flights_by_id[original_booking["flight_id"]]["departure_time"])
        now = datetime.fromisoformat(task["now"])
        assert departure - now == timedelta(days=7), f"{task_path.name}: task text says exactly seven days"


def test_shopping_task_env_dates_are_policy_coherent() -> None:
    for env_path in _domain_envs("shopping_assistant"):
        task_path = Path("state_bench/domains/shopping_assistant/tasks") / env_path.name
        task = json.loads(task_path.read_text())
        env = json.loads(env_path.read_text())
        now = datetime.fromisoformat(task["now"])
        task_text = json.dumps(task).lower()

        for product in env.get("products", []):
            shipping_days = product.get("shipping_days")
            assert isinstance(shipping_days, int) and shipping_days > 0, (
                f"{env_path.name}: {product['product_id']} has invalid shipping_days"
            )

        for promo in env.get("promotions", []):
            promo_code = promo["promo_code"]
            expiry_raw = promo.get("expiry_date", "")
            assert expiry_raw, f"{env_path.name}: {promo_code} missing expiry_date"
            expiry = datetime.fromisoformat(expiry_raw if "T" in expiry_raw else f"{expiry_raw}T23:59:59")

            promo_text_marker = f"{promo_code.lower()} expired"
            if promo_code.lower().startswith("expired") or promo_text_marker in task_text:
                assert now > expiry, f"{env_path.name}: {promo_code} is described as expired but is usable"
