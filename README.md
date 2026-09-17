# ParkFlow — Parking Management System

A web application for a busy multi-level city-centre parking garage. Attendants check
vehicles in, get an appropriate spot assigned automatically, look up vehicles by plate,
check vehicles out, and get a correctly calculated parking fee.

## Overview

ParkFlow is built for garage attendants who need a fast, reliable way to:

- check a vehicle in and have it assigned to a compatible, free spot
- make sure no spot is ever double-booked and no EV ends up in a non-EV spot
- look up any vehicle by license plate to see if/where it's parked
- check EV charger availability before sending a driver to look for one
- check a vehicle out and get a correct, tiered parking fee
- browse full parking history with search, sorting, and pagination

The garage layout (floors, spot counts, spot types) is configurable — the system is not
hardcoded to one specific garage (see `seed.py`).

## Features

- Multi-floor garage with compact / standard / EV spots
- Deterministic, automatic spot assignment on check-in
- EV vehicles are only ever assigned an EV spot
- Prevents a vehicle from having two active sessions, and a spot from being double-assigned
- Tiered, configurable fee calculation with a daily cap (integer-only math, no float rounding issues)
- License plate search across active and historical sessions
- EV spot availability check
- Parking history with search, sorting (whitelisted fields only), and pagination
- User registration/login/logout (hashed passwords, session-cookie auth)
- Landing page, registration, login, and dashboard UI (Tailwind + vanilla JS)

## Technology Stack

- **Backend**: Python, Flask, Flask-SQLAlchemy, Flask-CORS, Werkzeug (password hashing)
- **Database**: SQLite via SQLAlchemy ORM
- **Frontend**: HTML, Tailwind CSS (CDN), vanilla JavaScript (`fetch`)
- **Testing**: pytest

## Project Structure

```
parking-management/
├── app.py                  # Flask app, routes, page + API endpoints
├── models.py                # SQLAlchemy models: User, ParkingSpot, ParkingSession
├── fees.py                  # calculate_fee() — pure function, independently testable
├── rates.py                  # messy rate-card cleaning/import (see "Twists" below)
├── rate_card_raw.csv         # sample messy per-spot-type rate card
├── seed.py                  # DB init + garage seed data (configurable layout)
├── requirements.txt
├── tests/
│   └── test_app.py          # pytest suite (38 tests)
├── templates/
│   ├── index.html            # Landing page
│   ├── register.html
│   ├── login.html
│   └── dashboard.html
├── static/js/
│   ├── auth.js               # register/login form handling
│   └── dashboard.js          # dashboard logic (check-in/out, search, history)
├── README.md
├── REASONING.md
└── AI_LOGS.md
```

## Setup & Installation

Requires Python 3.10+.

```bash
cd parking-management
python -m venv venv

# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

## How to Run

```bash
python app.py
```

The app starts at **http://localhost:5000**. On first run it automatically creates
`parking.db` (SQLite) and seeds it with a sample 3-floor garage (see `seed.py`).

Open `http://localhost:5000` in a browser, register an attendant account, log in, and
use the dashboard.

## Running Tests

```bash
python -m pytest tests/ -v
```

38 tests cover fee calculation, auth, check-in/check-out rules, spot assignment,
search, pagination, sorting, and the three twists below.

## Database

SQLite file `parking.db`, created automatically. Schema:

**User** — `id, name, email (unique), password_hash, created_at`

**ParkingSpot** — `id, spot_number, floor, spot_type (compact/standard/ev), is_occupied`

**ParkingSession** — `id, plate_number, vehicle_type, spot_id (FK), check_in, check_out, fee, status (active/completed)`

A spot can have many historical sessions, but at most one **active** session at a time
(enforced in application logic before insert).

To reset the database, stop the server and delete `parking.db`, then restart — it will
be recreated and reseeded.

## Pricing Assumption

Rates are configurable constants in `fees.py` (not specified by the problem statement):

```python
FIRST_HOUR_RATE = 50
ADDITIONAL_HOUR_RATE = 30
DAILY_CAP = 250
```

Rules: up to 60 minutes = first-hour rate; every additional **started** hour is charged
at the additional rate; the total is capped at `DAILY_CAP`. All math uses integer
seconds/minutes (ceiling division) — no floating point.

| Duration | Fee |
|---|---|
| 30 min | ₹50 |
| 60 min | ₹50 |
| 61 min | ₹80 |
| 120 min | ₹80 |
| 121 min | ₹110 |

See `REASONING.md` for the full explanation and edge cases.

## API Endpoints

All `/api/*` endpoints (except register/login) require an authenticated session
(cookie set on login). Errors are returned as `{"error": "..."}` with an appropriate
HTTP status code.

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/register` | No | Create a new attendant account |
| POST | `/api/login` | No | Log in, starts a session |
| POST | `/api/logout` | Yes | Ends the session |
| GET | `/api/status` | Yes | Returns the current logged-in user |
| POST | `/api/parking/check-in` | Yes | Check a vehicle in, auto-assigns a spot |
| POST | `/api/parking/check-out` | Yes | Check a vehicle out, calculates the fee |
| GET | `/api/parking` | Yes | Parking history — search, sort, paginate |
| GET | `/api/parking/<plate>` | Yes | Active + historical sessions for one plate |
| GET | `/api/spots` | Yes | All spots with occupancy status |
| GET | `/api/spots/available` | Yes | Available spots, optional `?type=` filter |
| GET | `/api/dashboard-stats` | Yes | Spot/EV counts for the dashboard |
| GET | `/api/rates` | Yes | Cleaned per-spot-type rate card (see Twists) |
| POST | `/clock` | No | Triggers the nightly auto-close job (see Twists) |
| POST | `/api/parking/transfer` | Yes | Valet plate hand-off (see Twists) |

### Request / Response Examples

**Register**
```
POST /api/register
{"name": "Jane Doe", "email": "jane@example.com", "password": "secret123"}

201 Created
{"id": 1, "name": "Jane Doe", "email": "jane@example.com"}
```

**Login**
```
POST /api/login
{"email": "jane@example.com", "password": "secret123"}

200 OK
{"id": 1, "name": "Jane Doe", "email": "jane@example.com"}
```
Invalid credentials → `401 {"error": "Invalid email or password"}`

**Check-in**
```
POST /api/parking/check-in
{"plate_number": "KA01AB1234", "vehicle_type": "ev"}

201 Created
{
  "id": 1, "plate_number": "KA01AB1234", "vehicle_type": "ev",
  "spot_id": 9, "spot_number": "E1-09", "floor": 1,
  "check_in": "2024-01-01T10:00:00", "check_out": null,
  "fee": null, "status": "active"
}
```
- Vehicle already parked → `409 {"error": "Vehicle is already parked"}`
- No compatible spot → `409 {"error": "No compatible parking spot available"}`
- Invalid vehicle type → `400 {"error": "vehicle_type must be one of [...]"}`

**Check-out**
```
POST /api/parking/check-out
{"plate_number": "KA01AB1234"}

200 OK
{ "...": "...", "check_out": "2024-01-01T11:05:00", "fee": 80, "status": "completed" }
```
No active session for that plate → `404 {"error": "No active parking session found for this vehicle"}`

**EV availability**
```
GET /api/spots/available?type=ev
200 OK
[{"id": 10, "spot_number": "E1-10", "floor": 1, "spot_type": "ev", "is_occupied": false}, ...]
```

### Search Usage

`GET /api/parking?search=KA01` — case-insensitive substring match on `plate_number`.
Also works for a specific plate: `GET /api/parking/KA01AB1234` (active + full history).

### Pagination Usage

`GET /api/parking?page=2&limit=10` — `page` (default 1), `limit` (default 10, max 100).

Response includes pagination metadata:
```json
{ "data": [...], "page": 2, "limit": 10, "total": 27, "pages": 3 }
```

### Sorting Usage

`GET /api/parking?sort=fee&order=desc` — `sort` is restricted to a whitelist
(`check_in`, `check_out`, `fee`, `plate_number`, `status`) to prevent SQL-injection-style
sort-field abuse; any other value returns `400`. `order` is `asc` or `desc` (default `desc`).

Combined example:
```
GET /api/parking?search=RJ14&page=1&limit=10&sort=check_in&order=desc
```

## Twists

Three additional assessment "twists" are implemented on top of the core spec:

### T4 — Messy rate-card import

Pricing is no longer one flat rate for every spot type. `rate_card_raw.csv` is a
deliberately messy sample rate card (inconsistent casing, currency symbols like `₹`
and `Rs.`, stray whitespace, blank rows, a row with a missing field, and a conflicting
duplicate row) — a stand-in for a real spreadsheet export, since no actual file was
provided for this assessment. `rates.py` cleans it into
`{spot_type: {first_hour, additional_hour, daily_cap}}` (first valid row per spot type
wins; invalid/unparseable rows are skipped rather than crashing the whole import).
`app.py` loads this once at startup and `check_out`/`clock` use the checked-in spot's
own rates instead of the flat default. Inspect the cleaned result at `GET /api/rates`.

### T2 — Nightly auto-close job

`POST /clock` simulates the nightly job that force-closes and bills any session parked
longer than 24 hours. It's intentionally **not** behind login — a cron job/scheduler
has no attendant session — and accepts an optional `{"now": "<ISO datetime>"}` so it
can be graded without an actual 24-hour wait (e.g. check in a vehicle, then call
`/clock` with `now` set to 25 hours after that check-in). Any matching session is
checked out, billed at its spot type's rate (which will hit the daily cap for any
24h+ stay), and its spot is freed.

```
POST /clock
{"now": "2024-01-02T11:00:00"}

200 OK
{"as_of": "2024-01-02T11:00:00", "closed_count": 1, "closed": [{...}]}
```

### T6 — Valet plate transfer

`POST /api/parking/transfer` hands an open session off to a different plate (e.g. a
valet swaps which car is technically "at" a spot). The **same** session row is
updated in place — only `plate_number` changes — so the spot and the original
`check_in` time carry over exactly as parked, rather than closing one session and
opening a new one.

```
POST /api/parking/transfer
{"old_plate": "KA01AB1234", "new_plate": "KA01AB9999"}

200 OK
{ "...": "...", "plate_number": "KA01AB9999", "spot_id": 9, "check_in": "<unchanged>", "status": "active" }
```
- No active session for `old_plate` → `404`
- `new_plate` already has its own active session → `409`
- `old_plate == new_plate` → `400`

## Debugging

- **App won't start / port in use**: another process is bound to port 5000 — either
  stop it or run `app.run(port=5001)`.
- **Stale data / weird state**: stop the server, delete `parking.db`, restart to reseed.
- **401 on every request**: session cookie not being sent — the frontend fetch calls use
  `credentials: "include"`; if calling the API from a separate origin/tool, do the same.
- **500 errors**: check the Flask console output; the API never leaks raw tracebacks to
  the client, only `{"error": "Internal server error"}`.
- Run `python -m pytest tests/ -v` to check core logic is intact after any change.

## Future Improvements

1. **License plate recognition** — camera-based automatic check-in/check-out.
2. **Reserved / monthly passes** — subscription parking with pre-assigned spots.
3. **Online payments** — card/UPI payment at checkout instead of cash-only settlement.
