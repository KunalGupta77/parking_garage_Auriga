import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from app import create_app
from fees import ADDITIONAL_HOUR_RATE, DAILY_CAP, FIRST_HOUR_RATE, calculate_fee
from models import ParkingSpot, db
from rates import clean_rate_card, load_rate_card
from seed import init_db
from validators import is_valid_plate, normalize_plate, password_strength_error

# A password meeting the strength policy (>=8 chars, upper, lower, digit, special),
# reused everywhere a test just needs a valid account rather than testing the policy.
STRONG_PW = "Secur3P@ss"


@pytest.fixture
def app():
    app = create_app(db_uri="sqlite:///:memory:")
    app.config.update(TESTING=True)
    init_db(app)
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def register_and_login(client, email="attendant@example.com"):
    client.post("/api/register", json={"name": "Attendant", "email": email, "password": STRONG_PW})
    client.post("/api/login", json={"email": email, "password": STRONG_PW})


# --------------------------------------------------------------- fee tests
def test_fee_first_hour_partial():
    from datetime import datetime, timedelta

    start = datetime(2024, 1, 1, 10, 0, 0)
    assert calculate_fee(start, start + timedelta(minutes=30)) == FIRST_HOUR_RATE


def test_fee_exactly_first_hour():
    from datetime import datetime, timedelta

    start = datetime(2024, 1, 1, 10, 0, 0)
    assert calculate_fee(start, start + timedelta(minutes=60)) == FIRST_HOUR_RATE


def test_fee_just_over_first_hour():
    from datetime import datetime, timedelta

    start = datetime(2024, 1, 1, 10, 0, 0)
    assert calculate_fee(start, start + timedelta(minutes=61)) == FIRST_HOUR_RATE + ADDITIONAL_HOUR_RATE


def test_fee_exactly_two_hours():
    from datetime import datetime, timedelta

    start = datetime(2024, 1, 1, 10, 0, 0)
    assert calculate_fee(start, start + timedelta(minutes=120)) == FIRST_HOUR_RATE + ADDITIONAL_HOUR_RATE


def test_fee_just_over_two_hours():
    from datetime import datetime, timedelta

    start = datetime(2024, 1, 1, 10, 0, 0)
    assert calculate_fee(start, start + timedelta(minutes=121)) == FIRST_HOUR_RATE + 2 * ADDITIONAL_HOUR_RATE


def test_fee_daily_cap_applies():
    from datetime import datetime, timedelta

    start = datetime(2024, 1, 1, 10, 0, 0)
    fee = calculate_fee(start, start + timedelta(hours=24))
    assert fee == DAILY_CAP


# --------------------------------------------------------- password policy
def test_password_strength_error_too_short():
    assert password_strength_error("Ab1@ab") is not None


def test_password_strength_error_missing_upper():
    assert password_strength_error("secur3p@ss") is not None


def test_password_strength_error_missing_special():
    assert password_strength_error("Secur3pass") is not None


def test_password_strength_error_accepts_strong_password():
    assert password_strength_error(STRONG_PW) is None


# -------------------------------------------------------------- plate format
def test_is_valid_plate_accepts_standard_indian_format():
    assert is_valid_plate("KA01AB1234")
    assert is_valid_plate("MH12CD5678")


def test_is_valid_plate_rejects_junk():
    assert not is_valid_plate("AB1")
    assert not is_valid_plate("12345")
    assert not is_valid_plate("")


def test_normalize_plate_strips_spaces_and_case():
    assert normalize_plate("ka 01-ab 1234") == "KA01AB1234"


# ----------------------------------------------------------------- auth
def test_register_success(client):
    resp = client.post("/api/register", json={"name": "A", "email": "a@x.com", "password": STRONG_PW})
    assert resp.status_code == 201
    assert resp.get_json()["email"] == "a@x.com"


def test_register_weak_password_rejected(client):
    resp = client.post("/api/register", json={"name": "A", "email": "a@x.com", "password": "weak"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_register_duplicate_email(client):
    client.post("/api/register", json={"name": "A", "email": "a@x.com", "password": STRONG_PW})
    resp = client.post("/api/register", json={"name": "A2", "email": "a@x.com", "password": STRONG_PW})
    assert resp.status_code == 409


def test_login_success(client):
    client.post("/api/register", json={"name": "A", "email": "a@x.com", "password": STRONG_PW})
    resp = client.post("/api/login", json={"email": "a@x.com", "password": STRONG_PW})
    assert resp.status_code == 200


def test_login_invalid_password(client):
    client.post("/api/register", json={"name": "A", "email": "a@x.com", "password": STRONG_PW})
    resp = client.post("/api/login", json={"email": "a@x.com", "password": "wrong"})
    assert resp.status_code == 401


# ------------------------------------------------------------- check-in
def test_checkin_requires_auth(client):
    resp = client.post("/api/parking/check-in", json={"plate_number": "KA01AB1234", "vehicle_type": "compact"})
    assert resp.status_code == 401


def test_checkin_compact_success(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "KA01AB1234", "vehicle_type": "compact"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "active"


def test_checkin_standard_success(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "KA01AB2345", "vehicle_type": "standard"})
    assert resp.status_code == 201


def test_checkin_ev_success(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "KA01AB3456", "vehicle_type": "ev"})
    assert resp.status_code == 201


def test_checkin_invalid_plate_format_rejected(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "AB1", "vehicle_type": "compact"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_checkin_normalizes_spaces_and_hyphens(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "ka 01-ab 9999", "vehicle_type": "compact"})
    assert resp.status_code == 201
    assert resp.get_json()["plate_number"] == "KA01AB9999"


def test_ev_never_assigned_non_ev_spot(client, app):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "KA01EV1111", "vehicle_type": "ev"})
    spot_id = resp.get_json()["spot_id"]
    with app.app_context():
        spot = db.session.get(ParkingSpot, spot_id)
        assert spot.spot_type == "ev"


def test_duplicate_active_checkin_rejected(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "KA01AB4567", "vehicle_type": "compact"})
    resp = client.post("/api/parking/check-in", json={"plate_number": "ka01ab4567", "vehicle_type": "compact"})
    assert resp.status_code == 409


def test_spot_never_double_assigned(client):
    register_and_login(client)
    r1 = client.post("/api/parking/check-in", json={"plate_number": "KA01ST0001", "vehicle_type": "standard"})
    r2 = client.post("/api/parking/check-in", json={"plate_number": "KA01ST0002", "vehicle_type": "standard"})
    assert r1.get_json()["spot_id"] != r2.get_json()["spot_id"]


def test_no_compatible_spot_handled(client):
    register_and_login(client)
    # Fill all EV spots (6 total from seed config: 2 per floor x 3 floors).
    for i in range(6):
        resp = client.post(
            "/api/parking/check-in", json={"plate_number": f"KA01EV{1000 + i}", "vehicle_type": "ev"}
        )
        assert resp.status_code == 201
    resp = client.post("/api/parking/check-in", json={"plate_number": "KA01EV1006", "vehicle_type": "ev"})
    assert resp.status_code == 409
    assert "error" in resp.get_json()


def test_invalid_vehicle_type_rejected(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "KA01BD9999", "vehicle_type": "truck"})
    assert resp.status_code == 400


# ------------------------------------------------------------- check-out
def test_checkout_success_and_frees_spot(client, app):
    register_and_login(client)
    checkin = client.post("/api/parking/check-in", json={"plate_number": "KA01CO0001", "vehicle_type": "compact"})
    spot_id = checkin.get_json()["spot_id"]

    resp = client.post("/api/parking/check-out", json={"plate_number": "ka01co0001"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "completed"
    assert body["fee"] is not None

    with app.app_context():
        spot = db.session.get(ParkingSpot, spot_id)
        assert spot.is_occupied is False


def test_checkout_nonexistent_vehicle(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-out", json={"plate_number": "NOPE"})
    assert resp.status_code == 404


# ---------------------------------------------------------------- search
def test_plate_search(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "KA01FD1234", "vehicle_type": "compact"})
    resp = client.get("/api/parking/ka01fd1234")
    assert resp.status_code == 200
    assert resp.get_json()["plate_number"] == "KA01FD1234"


def test_plate_search_not_found(client):
    register_and_login(client)
    resp = client.get("/api/parking/NOPE99")
    assert resp.status_code == 404


# ------------------------------------------------------- pagination/sort
def test_pagination(client):
    register_and_login(client)
    # Seed config provides 12 standard spots, so 12 check-ins all succeed.
    for i in range(12):
        resp = client.post(
            "/api/parking/check-in", json={"plate_number": f"KA02PG{4000 + i}", "vehicle_type": "standard"}
        )
        assert resp.status_code == 201
    resp = client.get("/api/parking?page=2&limit=10")
    body = resp.get_json()
    assert body["page"] == 2
    assert len(body["data"]) == 2
    assert body["total"] == 12
    assert body["pages"] == 2


def test_sorting(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "ZZ09ZZ0009", "vehicle_type": "compact"})
    client.post("/api/parking/check-in", json={"plate_number": "AA01AA0001", "vehicle_type": "standard"})
    resp = client.get("/api/parking?sort=plate_number&order=asc")
    plates = [row["plate_number"] for row in resp.get_json()["data"]]
    assert plates == sorted(plates)


def test_invalid_sort_field_rejected(client):
    register_and_login(client)
    resp = client.get("/api/parking?sort=password_hash")
    assert resp.status_code == 400


# ------------------------------------------------------------ EV availability
def test_ev_availability(client):
    register_and_login(client)
    resp = client.get("/api/spots/available?type=ev")
    assert resp.status_code == 200
    body = resp.get_json()
    assert all(s["spot_type"] == "ev" for s in body)
    assert len(body) == 6


# --------------------------------------------------- T4: messy rate card
def test_clean_rate_card_handles_junk():
    rows = [
        {"spot_type": "Compact ", "first_hour": '"₹50"', "additional_hour": "30", "daily_cap": "250"},
        {"spot_type": "STANDARD", "first_hour": "60", "additional_hour": "35", "daily_cap": "300"},
        {"spot_type": "electric vehicle", "first_hour": "100", "additional_hour": "50", "daily_cap": "400"},
        # blank/junk row must be skipped, not crash
        {"spot_type": "", "first_hour": "", "additional_hour": "", "daily_cap": ""},
        # missing field must be skipped
        {"spot_type": "ev", "first_hour": "", "additional_hour": "50", "daily_cap": "400"},
        # conflicting duplicate for standard must be ignored (first wins)
        {"spot_type": "Standard", "first_hour": "999", "additional_hour": "999", "daily_cap": "999"},
        # another EV alias, also ignored since "ev" already resolved above
        {"spot_type": "e.v.", "first_hour": "1", "additional_hour": "1", "daily_cap": "1"},
    ]
    cleaned = clean_rate_card(rows)
    assert cleaned == {
        "compact": {"first_hour": 50, "additional_hour": 30, "daily_cap": 250},
        "standard": {"first_hour": 60, "additional_hour": 35, "daily_cap": 300},
        "ev": {"first_hour": 100, "additional_hour": 50, "daily_cap": 400},
    }


def test_load_rate_card_from_file():
    path = os.path.join(os.path.dirname(__file__), "..", "rate_card_raw.csv")
    cleaned = load_rate_card(path)
    assert set(cleaned) == {"compact", "standard", "ev"}
    assert cleaned["ev"]["first_hour"] == 100


def test_checkout_uses_per_spot_type_rate(client):
    register_and_login(client)
    checkin = client.post("/api/parking/check-in", json={"plate_number": "KA01EV7890", "vehicle_type": "ev"})
    assert checkin.status_code == 201
    resp = client.post("/api/parking/check-out", json={"plate_number": "KA01EV7890"})
    body = resp.get_json()
    # EV's cleaned first-hour rate (100) differs from the flat default (50).
    assert body["fee"] == 100


def test_rates_endpoint(client):
    register_and_login(client)
    resp = client.get("/api/rates")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rate_card"]["ev"]["first_hour"] == 100


# --------------------------------------------------- T2: nightly auto-close
def test_clock_auto_closes_stale_session(client):
    register_and_login(client)
    checkin = client.post("/api/parking/check-in", json={"plate_number": "KA01ST5678", "vehicle_type": "standard"})
    spot_id = checkin.get_json()["spot_id"]
    check_in_iso = checkin.get_json()["check_in"]

    from datetime import datetime, timedelta

    check_in_dt = datetime.fromisoformat(check_in_iso)
    simulated_now = check_in_dt + timedelta(hours=25)

    resp = client.post("/clock", json={"now": simulated_now.isoformat()})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["closed_count"] == 1
    assert body["closed"][0]["plate_number"] == "KA01ST5678"
    assert body["closed"][0]["status"] == "completed"
    # 25 hours parked exceeds the cleaned rate card's cap for "standard" (300).
    assert body["closed"][0]["fee"] == 300

    spots = client.get("/api/spots").get_json()
    freed_spot = next(s for s in spots if s["id"] == spot_id)
    assert freed_spot["is_occupied"] is False


def test_clock_leaves_fresh_sessions_active(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "KA01FR2345", "vehicle_type": "standard"})
    resp = client.post("/clock", json={})
    assert resp.status_code == 200
    assert resp.get_json()["closed_count"] == 0


def test_clock_requires_no_auth(client):
    # No register_and_login call — /clock must work for an unauthenticated
    # scheduler/cron caller.
    resp = client.post("/clock", json={})
    assert resp.status_code == 200


# --------------------------------------------------- T6: valet transfer
def test_transfer_moves_plate_keeps_spot_and_entry_time(client):
    register_and_login(client)
    checkin = client.post("/api/parking/check-in", json={"plate_number": "KA01OL1111", "vehicle_type": "compact"})
    original = checkin.get_json()

    resp = client.post(
        "/api/parking/transfer", json={"old_plate": "KA01OL1111", "new_plate": "KA01NW2222"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["plate_number"] == "KA01NW2222"
    assert body["spot_id"] == original["spot_id"]
    assert body["check_in"] == original["check_in"]
    assert body["status"] == "active"

    # Old plate no longer has an active session.
    old_lookup = client.get("/api/parking/KA01OL1111")
    assert old_lookup.status_code == 404

    new_lookup = client.get("/api/parking/KA01NW2222")
    assert new_lookup.status_code == 200
    assert new_lookup.get_json()["active"]["plate_number"] == "KA01NW2222"


def test_transfer_nonexistent_old_plate(client):
    register_and_login(client)
    resp = client.post("/api/parking/transfer", json={"old_plate": "NOPE", "new_plate": "KA01NW2222"})
    assert resp.status_code == 404


def test_transfer_conflicting_new_plate(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "KA01OL3333", "vehicle_type": "compact"})
    client.post("/api/parking/check-in", json={"plate_number": "KA01TK4444", "vehicle_type": "standard"})

    resp = client.post(
        "/api/parking/transfer", json={"old_plate": "KA01OL3333", "new_plate": "KA01TK4444"}
    )
    assert resp.status_code == 409


def test_transfer_same_plate_rejected(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "KA01SM5555", "vehicle_type": "compact"})
    resp = client.post(
        "/api/parking/transfer", json={"old_plate": "KA01SM5555", "new_plate": "ka01sm5555"}
    )
    assert resp.status_code == 400


def test_transfer_invalid_new_plate_format_rejected(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "KA01VL6666", "vehicle_type": "compact"})
    resp = client.post("/api/parking/transfer", json={"old_plate": "KA01VL6666", "new_plate": "NOTAPLATE"})
    assert resp.status_code == 400
