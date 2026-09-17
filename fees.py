
FIRST_HOUR_RATE = 50
ADDITIONAL_HOUR_RATE = 30
DAILY_CAP = 250


def calculate_fee(
    check_in,
    check_out,
    first_hour_rate=FIRST_HOUR_RATE,
    additional_hour_rate=ADDITIONAL_HOUR_RATE,
    daily_cap=DAILY_CAP,
):
   
    total_seconds = int((check_out - check_in).total_seconds())
    if total_seconds <= 0:
        return first_hour_rate

    # Ceil division to minutes, then to hours, using integer arithmetic only.
    total_minutes = (total_seconds + 59) // 60

    if total_minutes <= 60:
        fee = first_hour_rate
    else:
        extra_minutes = total_minutes - 60
        extra_hours = (extra_minutes + 59) // 60
        fee = first_hour_rate + extra_hours * additional_hour_rate

    return min(fee, daily_cap)
