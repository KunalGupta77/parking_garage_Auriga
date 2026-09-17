

FIRST_HOUR_RATE = 50
ADDITIONAL_HOUR_RATE = 30
DAILY_CAP = 250


def calculate_fee(check_in, check_out):
   
    total_seconds = int((check_out - check_in).total_seconds())
    if total_seconds <= 0:
        return FIRST_HOUR_RATE

    # Ceil division to minutes, then to hours, using integer arithmetic only.
    total_minutes = (total_seconds + 59) // 60

    if total_minutes <= 60:
        fee = FIRST_HOUR_RATE
    else:
        extra_minutes = total_minutes - 60
        extra_hours = (extra_minutes + 59) // 60
        fee = FIRST_HOUR_RATE + extra_hours * ADDITIONAL_HOUR_RATE

    return min(fee, DAILY_CAP)
