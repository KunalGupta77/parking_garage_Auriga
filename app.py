import math
import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, jsonify, render_template, request, session
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

from fees import ADDITIONAL_HOUR_RATE, DAILY_CAP, FIRST_HOUR_RATE, calculate_fee
from models import ParkingSession, ParkingSpot, User, VEHICLE_TYPES, db, utcnow
from rates import load_rate_card
from seed import init_db
from validators import is_valid_plate, normalize_plate, password_strength_error

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Cleaned per-spot-type rate card (assessment twist T4 — see rates.py and
# rate_card_raw.csv). A spot type missing from the imported card (or the
# file being absent entirely) falls back to the flat default rates.
DEFAULT_RATES = {
    "first_hour": FIRST_HOUR_RATE,
    "additional_hour": ADDITIONAL_HOUR_RATE,
    "daily_cap": DAILY_CAP,
}
RATE_CARD_PATH = os.path.join(BASE_DIR, "rate_card_raw.csv")
try:
    RATE_CARD = load_rate_card(RATE_CARD_PATH)
except FileNotFoundError:
    RATE_CARD = {}


def rates_for(spot_type):
    return RATE_CARD.get(spot_type, DEFAULT_RATES)


# A session parked longer than this is auto-closed by the nightly job
# (assessment twist T2 — triggered via POST /clock rather than a real cron).
AUTO_CLOSE_AFTER_HOURS = 24

# Fallback order of spot types a vehicle may use, most-specific first.
# EV vehicles must only ever use an EV spot. A compact car may fall back to
# a standard spot if no compact spot is free (documented assumption — see
# REASONING.md). A standard vehicle only fits a standard spot.
SPOT_FALLBACK = {
    "ev": ["ev"],
    "compact": ["compact", "standard"],
    "standard": ["standard"],
}

SORTABLE_FIELDS = {
    "check_in": ParkingSession.check_in,
    "check_out": ParkingSession.check_out,
    "fee": ParkingSession.fee,
    "plate_number": ParkingSession.plate_number,
    "status": ParkingSession.status,
}


def create_app(db_uri=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri or "sqlite:///" + os.path.join(BASE_DIR, "parking.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    db.init_app(app)
    CORS(app, supports_credentials=True)

    register_routes(app)

    @app.errorhandler(Exception)
    def handle_unexpected_error(err):
        from werkzeug.exceptions import HTTPException

        if isinstance(err, HTTPException):
            return jsonify({"error": err.description or err.name}), err.code
        app.logger.exception("Unhandled error")
        return jsonify({"error": "Internal server error"}), 500

    return app


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return wrapper


def find_available_spot(vehicle_type):
    for spot_type in SPOT_FALLBACK.get(vehicle_type, []):
        spot = (
            ParkingSpot.query.filter_by(spot_type=spot_type, is_occupied=False)
            .order_by(ParkingSpot.floor.asc(), ParkingSpot.spot_number.asc())
            .first()
        )
        if spot:
            return spot
    return None


def register_routes(app):
    # ---------------------------------------------------------------- pages
    @app.get("/")
    def index_page():
        return render_template("index.html")

    @app.get("/register")
    def register_page():
        return render_template("register.html")

    @app.get("/login")
    def login_page():
        return render_template("login.html")

    @app.get("/dashboard")
    def dashboard_page():
        return render_template("dashboard.html")

    # ---------------------------------------------------------------- auth
    @app.post("/api/register")
    def register():
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

        if not name or not email or not password:
            return jsonify({"error": "name, email and password are required"}), 400

        pw_error = password_strength_error(password)
        if pw_error:
            return jsonify({"error": pw_error}), 400

        if User.query.filter_by(email=email).first():
            return jsonify({"error": "Email already registered"}), 409

        user = User(name=name, email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        return jsonify(user.to_dict()), 201

    @app.post("/api/login")
    def login():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "Invalid email or password"}), 401

        session["user_id"] = user.id
        return jsonify(user.to_dict()), 200

    @app.post("/api/logout")
    @login_required
    def logout():
        session.clear()
        return jsonify({"message": "Logged out"}), 200

    @app.get("/api/status")
    @login_required
    def status():
        user = db.session.get(User, session["user_id"])
        if not user:
            session.clear()
            return jsonify({"error": "Authentication required"}), 401
        return jsonify(user.to_dict()), 200

    # ------------------------------------------------------------- parking
    @app.post("/api/parking/check-in")
    @login_required
    def check_in():
        data = request.get_json(silent=True) or {}
        plate_number = normalize_plate(data.get("plate_number"))
        vehicle_type = (data.get("vehicle_type") or "").strip().lower()

        if not plate_number or not vehicle_type:
            return jsonify({"error": "plate_number and vehicle_type are required"}), 400
        if vehicle_type not in VEHICLE_TYPES:
            return jsonify({"error": f"vehicle_type must be one of {list(VEHICLE_TYPES)}"}), 400
        if not is_valid_plate(plate_number):
            return jsonify({"error": "plate_number must be a valid Indian format, e.g. KA01AB1234"}), 400

        existing = ParkingSession.query.filter_by(plate_number=plate_number, status="active").first()
        if existing:
            return jsonify({"error": "Vehicle is already parked"}), 409

        spot = find_available_spot(vehicle_type)
        if spot is None:
            return jsonify({"error": "No compatible parking spot available"}), 409

        new_session = ParkingSession(
            plate_number=plate_number,
            vehicle_type=vehicle_type,
            spot_id=spot.id,
            status="active",
        )
        spot.is_occupied = True
        db.session.add(new_session)
        db.session.commit()
        return jsonify(new_session.to_dict()), 201

    @app.post("/api/parking/check-out")
    @login_required
    def check_out():
        data = request.get_json(silent=True) or {}
        plate_number = normalize_plate(data.get("plate_number"))

        if not plate_number:
            return jsonify({"error": "plate_number is required"}), 400

        active_session = ParkingSession.query.filter_by(plate_number=plate_number, status="active").first()
        if active_session is None:
            return jsonify({"error": "No active parking session found for this vehicle"}), 404

        type_rates = rates_for(active_session.spot.spot_type)
        active_session.check_out = utcnow()
        active_session.fee = calculate_fee(
            active_session.check_in,
            active_session.check_out,
            type_rates["first_hour"],
            type_rates["additional_hour"],
            type_rates["daily_cap"],
        )
        active_session.status = "completed"
        active_session.spot.is_occupied = False
        db.session.commit()
        return jsonify(active_session.to_dict()), 200

    @app.get("/api/parking")
    @login_required
    def parking_history():
        search = (request.args.get("search") or "").strip()
        sort_field = request.args.get("sort", "check_in")
        order = request.args.get("order", "desc").lower()

        try:
            page = max(int(request.args.get("page", 1)), 1)
        except ValueError:
            page = 1
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            limit = 10
        limit = min(max(limit, 1), 100)

        if sort_field not in SORTABLE_FIELDS:
            return jsonify({"error": f"sort must be one of {list(SORTABLE_FIELDS)}"}), 400
        if order not in ("asc", "desc"):
            return jsonify({"error": "order must be 'asc' or 'desc'"}), 400

        query = ParkingSession.query
        if search:
            query = query.filter(ParkingSession.plate_number.ilike(f"%{search}%"))

        total = query.count()
        column = SORTABLE_FIELDS[sort_field]
        column = column.desc() if order == "desc" else column.asc()
        query = query.order_by(column)

        items = query.offset((page - 1) * limit).limit(limit).all()
        pages = math.ceil(total / limit) if total else 0

        return jsonify(
            {
                "data": [s.to_dict() for s in items],
                "page": page,
                "limit": limit,
                "total": total,
                "pages": pages,
            }
        ), 200

    @app.get("/api/parking/<plate>")
    @login_required
    def parking_by_plate(plate):
        plate_number = normalize_plate(plate)
        sessions = (
            ParkingSession.query.filter_by(plate_number=plate_number)
            .order_by(ParkingSession.check_in.desc())
            .all()
        )
        if not sessions:
            return jsonify({"error": "No records found for this plate"}), 404

        active = next((s for s in sessions if s.status == "active"), None)
        return jsonify(
            {
                "plate_number": plate_number,
                "active": active.to_dict() if active else None,
                "history": [s.to_dict() for s in sessions],
            }
        ), 200

    # --------------------------------------------------------------- spots
    @app.get("/api/spots")
    @login_required
    def list_spots():
        spots = ParkingSpot.query.order_by(ParkingSpot.floor.asc(), ParkingSpot.spot_number.asc()).all()
        return jsonify([s.to_dict() for s in spots]), 200

    @app.get("/api/spots/available")
    @login_required
    def available_spots():
        spot_type = (request.args.get("type") or "").strip().lower()
        query = ParkingSpot.query.filter_by(is_occupied=False)
        if spot_type:
            if spot_type not in ("compact", "standard", "ev"):
                return jsonify({"error": "type must be one of compact, standard, ev"}), 400
            query = query.filter_by(spot_type=spot_type)
        spots = query.order_by(ParkingSpot.floor.asc(), ParkingSpot.spot_number.asc()).all()
        return jsonify([s.to_dict() for s in spots]), 200

    # ------------------------------------------------------------ dashboard
    @app.get("/api/dashboard-stats")
    @login_required
    def dashboard_stats():
        total_spots = ParkingSpot.query.count()
        available_spots_count = ParkingSpot.query.filter_by(is_occupied=False).count()
        occupied_spots = total_spots - available_spots_count
        total_ev_spots = ParkingSpot.query.filter_by(spot_type="ev").count()
        available_ev_spots = ParkingSpot.query.filter_by(spot_type="ev", is_occupied=False).count()

        return jsonify(
            {
                "total_spots": total_spots,
                "available_spots": available_spots_count,
                "occupied_spots": occupied_spots,
                "total_ev_spots": total_ev_spots,
                "available_ev_spots": available_ev_spots,
            }
        ), 200

    # ------------------------------------------------------- rate card (T4)
    @app.get("/api/rates")
    @login_required
    def rates():
        return jsonify({"rate_card": RATE_CARD, "default": DEFAULT_RATES}), 200

    # ---------------------------------------------------- nightly job (T2)
    @app.post("/clock")
    def clock():
        """Simulates the nightly auto-close job. Not tied to an attendant
        session — it's meant to be triggered by a scheduler (or, for
        grading, called directly), not by a logged-in human.

        Accepts an optional {"now": "<ISO datetime>"} so a caller can
        simulate the clock moving forward without a real 24-hour wait;
        defaults to the real current time.
        """
        data = request.get_json(silent=True) or {}
        now_raw = data.get("now")
        if now_raw:
            try:
                as_of = datetime.fromisoformat(now_raw)
            except ValueError:
                return jsonify({"error": "now must be an ISO-8601 datetime"}), 400
            if as_of.tzinfo is not None:
                # The rest of the app stores naive UTC datetimes (see
                # models.utcnow); normalize any offset-aware input to match.
                as_of = as_of.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            as_of = utcnow()

        cutoff = as_of - timedelta(hours=AUTO_CLOSE_AFTER_HOURS)
        stale_sessions = ParkingSession.query.filter(
            ParkingSession.status == "active", ParkingSession.check_in <= cutoff
        ).all()

        closed = []
        for s in stale_sessions:
            type_rates = rates_for(s.spot.spot_type)
            s.check_out = as_of
            s.fee = calculate_fee(
                s.check_in, s.check_out, type_rates["first_hour"], type_rates["additional_hour"], type_rates["daily_cap"]
            )
            s.status = "completed"
            s.spot.is_occupied = False
            closed.append(s)
        db.session.commit()

        return jsonify({"as_of": as_of.isoformat(), "closed_count": len(closed), "closed": [s.to_dict() for s in closed]}), 200

    # --------------------------------------------------- valet hand-off (T6)
    @app.post("/api/parking/transfer")
    @login_required
    def transfer():
        """Transfers an open session to a different plate (valet hand-off).
        The spot and the original entry time carry over unchanged — this
        mutates the existing active session's plate rather than closing it
        out and opening a new one, since it's the same continuous stay.
        """
        data = request.get_json(silent=True) or {}
        old_plate = normalize_plate(data.get("old_plate"))
        new_plate = normalize_plate(data.get("new_plate"))

        if not old_plate or not new_plate:
            return jsonify({"error": "old_plate and new_plate are required"}), 400
        if old_plate == new_plate:
            return jsonify({"error": "new_plate must differ from old_plate"}), 400
        if not is_valid_plate(new_plate):
            return jsonify({"error": "new_plate must be a valid Indian format, e.g. KA01AB1234"}), 400

        active_session = ParkingSession.query.filter_by(plate_number=old_plate, status="active").first()
        if active_session is None:
            return jsonify({"error": "No active parking session found for old_plate"}), 404

        conflict = ParkingSession.query.filter_by(plate_number=new_plate, status="active").first()
        if conflict is not None:
            return jsonify({"error": "new_plate already has an active parking session"}), 409

        active_session.plate_number = new_plate
        db.session.commit()
        return jsonify(active_session.to_dict()), 200


app = create_app()
init_db(app)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
