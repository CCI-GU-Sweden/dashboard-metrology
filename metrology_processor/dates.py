"""Interpret acquisition timestamps recorded by microscope operators."""
from datetime import datetime, timezone
import logging
import os
from zoneinfo import ZoneInfo

LOG = logging.getLogger(__name__)


def acquired_at(metadata):
    value = str(metadata.get("Acquisition date", "")).strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed
    zone = ZoneInfo(os.getenv("METROLOGY_ACQUISITION_TIMEZONE", "Europe/Stockholm"))
    candidates = [parsed.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = [d for d in candidates if d.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == parsed]
    if not valid or valid[0].utcoffset() != valid[-1].utcoffset():
        LOG.warning("Ambiguous or nonexistent acquisition time: %s", value)
        return None
    return valid[0]
