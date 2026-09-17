

from models import ParkingSpot, db


GARAGE_CONFIG = [
    {"floor": 1, "compact": 4, "standard": 4, "ev": 2},
    {"floor": 2, "compact": 4, "standard": 4, "ev": 2},
    {"floor": 3, "compact": 4, "standard": 4, "ev": 2},
]


def init_db(app):
  
    with app.app_context():
        db.create_all()

        if ParkingSpot.query.count() > 0:
            return

        for floor_cfg in GARAGE_CONFIG:
            floor = floor_cfg["floor"]
            counter = 1
            for spot_type in ("compact", "standard", "ev"):
                for _ in range(floor_cfg.get(spot_type, 0)):
                    prefix = spot_type[0].upper()
                    spot_number = f"{prefix}{floor}-{counter:02d}"
                    db.session.add(
                        ParkingSpot(
                            spot_number=spot_number,
                            floor=floor,
                            spot_type=spot_type,
                            is_occupied=False,
                        )
                    )
                    counter += 1

        db.session.commit()
