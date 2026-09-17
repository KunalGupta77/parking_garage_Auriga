from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

VEHICLE_TYPES = ("compact", "standard", "ev")
SPOT_TYPES = ("compact", "standard", "ev")


def utcnow():
    # Naive UTC datetime — SQLite has no timezone-aware type, so we store
    # naive UTC everywhere and keep comparisons consistent.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email}


class ParkingSpot(db.Model):
    __tablename__ = "parking_spots"

    id = db.Column(db.Integer, primary_key=True)
    spot_number = db.Column(db.String(20), nullable=False)
    floor = db.Column(db.Integer, nullable=False)
    spot_type = db.Column(db.String(20), nullable=False)
    is_occupied = db.Column(db.Boolean, nullable=False, default=False)

    sessions = db.relationship("ParkingSession", backref="spot", lazy=True)

    __table_args__ = (db.UniqueConstraint("floor", "spot_number", name="uq_floor_spot_number"),)

    def to_dict(self):
        return {
            "id": self.id,
            "spot_number": self.spot_number,
            "floor": self.floor,
            "spot_type": self.spot_type,
            "is_occupied": self.is_occupied,
        }


class ParkingSession(db.Model):
    __tablename__ = "parking_sessions"

    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(20), nullable=False)
    vehicle_type = db.Column(db.String(20), nullable=False)
    spot_id = db.Column(db.Integer, db.ForeignKey("parking_spots.id"), nullable=False)
    check_in = db.Column(db.DateTime, nullable=False, default=utcnow)
    check_out = db.Column(db.DateTime, nullable=True)
    fee = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")

    def to_dict(self):
        return {
            "id": self.id,
            "plate_number": self.plate_number,
            "vehicle_type": self.vehicle_type,
            "spot_id": self.spot_id,
            "spot_number": self.spot.spot_number if self.spot else None,
            "floor": self.spot.floor if self.spot else None,
            "check_in": self.check_in.isoformat(),
            "check_out": self.check_out.isoformat() if self.check_out else None,
            "fee": self.fee,
            "status": self.status,
        }
