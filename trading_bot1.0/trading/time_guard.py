from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import CONFIG
from storage.address_repo import AddressRecord


class TimeGuard:
    """Validates whether an address record is recent enough for trading."""

    def __init__(self, max_age_seconds: int | None = None) -> None:
        self._max_age = (
            max_age_seconds
            if max_age_seconds is not None
            else CONFIG.trade.require_time_window_seconds
        )

    def is_recent(self, record: AddressRecord, *, reference: datetime | None = None) -> bool:
        if not record:
            return False
        now = reference or datetime.now(timezone.utc)
        age = now - record.timestamp
        return age <= timedelta(seconds=self._max_age)

