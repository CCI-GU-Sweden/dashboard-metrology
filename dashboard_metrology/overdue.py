"""Shared overdue rule for microscope cards and the dashboard overview."""
from calendar import monthrange
from zoneinfo import ZoneInfo

from django.utils import timezone


def is_overdue(last_measurement, now=None):
    if last_measurement is None:
        return False
    zone = ZoneInfo('Europe/Stockholm')
    current = (now or timezone.now()).astimezone(zone)
    year, month = (current.year - 1, 12) if current.month == 1 else (current.year, current.month - 1)
    day = min(current.day, monthrange(year, month)[1])
    cutoff = current.replace(year=year, month=month, day=day)
    return last_measurement < cutoff
