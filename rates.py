import csv
import re

SPOT_TYPE_ALIASES = {
    "compact": "compact",
    "standard": "standard",
    "ev": "ev",
    "e.v.": "ev",
    "electric": "ev",
    "electric vehicle": "ev",
}

_CURRENCY_JUNK = re.compile(r"[₹$]|rs\.?|inr", re.IGNORECASE)


def _clean_spot_type(raw):
    if raw is None:
        return None
    key = raw.strip().lower()
    return SPOT_TYPE_ALIASES.get(key)


def _clean_number(raw):
    if raw is None:
        return None
    text = _CURRENCY_JUNK.sub("", raw).strip().strip('"').strip()
    if not text:
        return None
    try:
        return round(float(text))
    except ValueError:
        return None


def clean_rate_card(rows):
    """rows: iterable of raw dict rows with keys spot_type/first_hour/
    additional_hour/daily_cap (any casing/junk). Returns
    {spot_type: {"first_hour": int, "additional_hour": int, "daily_cap": int}}.
    """
    cleaned = {}
    for row in rows:
        spot_type = _clean_spot_type(row.get("spot_type"))
        if spot_type is None or spot_type in cleaned:
            continue

        first_hour = _clean_number(row.get("first_hour"))
        additional_hour = _clean_number(row.get("additional_hour"))
        daily_cap = _clean_number(row.get("daily_cap"))
        if None in (first_hour, additional_hour, daily_cap):
            continue

        cleaned[spot_type] = {
            "first_hour": first_hour,
            "additional_hour": additional_hour,
            "daily_cap": daily_cap,
        }
    return cleaned


def load_rate_card(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = [h.strip().lower() for h in next(reader)]
        # Map the messy header names to our canonical keys positionally,
        # since header spelling/spacing is exactly the kind of junk we're
        # cleaning: expected order is spot type, first hour, additional
        # hour, daily cap.
        rows = []
        for raw_row in reader:
            if len(raw_row) < 4:
                continue
            rows.append(
                {
                    "spot_type": raw_row[0],
                    "first_hour": raw_row[1],
                    "additional_hour": raw_row[2],
                    "daily_cap": raw_row[3],
                }
            )
    return clean_rate_card(rows)
