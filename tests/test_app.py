import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from app import create_app
from fees import ADDITIONAL_HOUR_RATE, DAILY_CAP, FIRST_HOUR_RATE, calculate_fee
from models import ParkingSpot, db
from seed import init_db


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
    client.post("/api/register", json={"name": "Attendant", "email": email, "password": "secret123"})
    client.post("/api/login", json={"email": email, "password": "secret123"})


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


# ----------------------------------------------------------------- auth
def test_register_success(client):
    resp = client.post(
        "/api/register", json={"name": "A", "email": "a@x.com", "password": "pw123456"}
    )
    assert resp.status_code == 201
    assert resp.get_json()["email"] == "a@x.com"


def test_register_duplicate_email(client):
    client.post("/api/register", json={"name": "A", "email": "a@x.com", "password": "pw123456"})
    resp = client.post("/api/register", json={"name": "A2", "email": "a@x.com", "password": "pw123456"})
    assert resp.status_code == 409


def test_login_success(client):
    client.post("/api/register", json={"name": "A", "email": "a@x.com", "password": "pw123456"})
    resp = client.post("/api/login", json={"email": "a@x.com", "password": "pw123456"})
    assert resp.status_code == 200


def test_login_invalid_password(client):
    client.post("/api/register", json={"name": "A", "email": "a@x.com", "password": "pw123456"})
    resp = client.post("/api/login", json={"email": "a@x.com", "password": "wrong"})
    assert resp.status_code == 401


# ------------------------------------------------------------- check-in
def test_checkin_requires_auth(client):
    resp = client.post("/api/parking/check-in", json={"plate_number": "AB1", "vehicle_type": "compact"})
    assert resp.status_code == 401


def test_checkin_compact_success(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "AB1", "vehicle_type": "compact"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["status"] == "active"


def test_checkin_standard_success(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "AB2", "vehicle_type": "standard"})
    assert resp.status_code == 201


def test_checkin_ev_success(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "AB3", "vehicle_type": "ev"})
    assert resp.status_code == 201


def test_ev_never_assigned_non_ev_spot(client, app):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "EV1", "vehicle_type": "ev"})
    spot_id = resp.get_json()["spot_id"]
    with app.app_context():
        spot = db.session.get(ParkingSpot, spot_id)
        assert spot.spot_type == "ev"


def test_duplicate_active_checkin_rejected(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "AB4", "vehicle_type": "compact"})
    resp = client.post("/api/parking/check-in", json={"plate_number": "ab4", "vehicle_type": "compact"})
    assert resp.status_code == 409


def test_spot_never_double_assigned(client):
    register_and_login(client)
    r1 = client.post("/api/parking/check-in", json={"plate_number": "S1", "vehicle_type": "standard"})
    r2 = client.post("/api/parking/check-in", json={"plate_number": "S2", "vehicle_type": "standard"})
    assert r1.get_json()["spot_id"] != r2.get_json()["spot_id"]


def test_no_compatible_spot_handled(client):
    register_and_login(client)
    # Fill all EV spots (6 total from seed config: 2 per floor x 3 floors).
    for i in range(6):
        resp = client.post("/api/parking/check-in", json={"plate_number": f"EV{i}", "vehicle_type": "ev"})
        assert resp.status_code == 201
    resp = client.post("/api/parking/check-in", json={"plate_number": "EVX", "vehicle_type": "ev"})
    assert resp.status_code == 409
    assert "error" in resp.get_json()


def test_invalid_vehicle_type_rejected(client):
    register_and_login(client)
    resp = client.post("/api/parking/check-in", json={"plate_number": "BAD1", "vehicle_type": "truck"})
    assert resp.status_code == 400


# ------------------------------------------------------------- check-out
def test_checkout_success_and_frees_spot(client, app):
    register_and_login(client)
    checkin = client.post("/api/parking/check-in", json={"plate_number": "CO1", "vehicle_type": "compact"})
    spot_id = checkin.get_json()["spot_id"]

    resp = client.post("/api/parking/check-out", json={"plate_number": "co1"})
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
    client.post("/api/parking/check-in", json={"plate_number": "FIND1", "vehicle_type": "compact"})
    resp = client.get("/api/parking/find1")
    assert resp.status_code == 200
    assert resp.get_json()["plate_number"] == "FIND1"


def test_plate_search_not_found(client):
    register_and_login(client)
    resp = client.get("/api/parking/NOPE99")
    assert resp.status_code == 404


# ------------------------------------------------------- pagination/sort
def test_pagination(client):
    register_and_login(client)
    # Seed config provides 12 standard spots, so 12 check-ins all succeed.
    for i in range(12):
        resp = client.post("/api/parking/check-in", json={"plate_number": f"PG{i}", "vehicle_type": "standard"})
        assert resp.status_code == 201
    resp = client.get("/api/parking?page=2&limit=10")
    body = resp.get_json()
    assert body["page"] == 2
    assert len(body["data"]) == 2
    assert body["total"] == 12
    assert body["pages"] == 2


def test_sorting(client):
    register_and_login(client)
    client.post("/api/parking/check-in", json={"plate_number": "ZZZ", "vehicle_type": "compact"})
    client.post("/api/parking/check-in", json={"plate_number": "AAA", "vehicle_type": "standard"})
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
