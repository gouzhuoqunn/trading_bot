from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from config import CONFIG
from logging_utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class AddressRecord:
    timestamp: datetime
    address: str

    @classmethod
    def from_line(cls, line: str) -> Optional["AddressRecord"]:
        parts = line.strip().split("|", maxsplit=1)
        if len(parts) != 2:
            return None
        ts_part, address_part = parts
        try:
            timestamp = datetime.fromisoformat(ts_part)
        except ValueError:
            return None
        return cls(timestamp=timestamp, address=address_part.strip())

    def to_line(self) -> str:
        return f"{self.timestamp.isoformat()}|{self.address}"


class AddressRepository:
    def __init__(self, file_path: Path | None = None) -> None:
        self._file_path = file_path or CONFIG.storage.addresses_file
        self._lock = threading.Lock()
        self._ensure_file()
        logger.debug("Address repository initialized at %s", self._file_path)

    def _ensure_file(self) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._file_path.exists():
            self._file_path.write_text("", encoding="utf-8")

    def append(self, record: AddressRecord) -> None:
        with self._lock:
            lines = self._file_path.read_text(encoding="utf-8").splitlines()
            records_by_address: dict[str, AddressRecord] = {}
            for line in lines:
                existing = AddressRecord.from_line(line)
                if not existing:
                    continue
                current = records_by_address.get(existing.address)
                if not current or existing.timestamp > current.timestamp:
                    records_by_address[existing.address] = existing

            previous = records_by_address.get(record.address)
            records_by_address[record.address] = record

            sorted_records = sorted(
                records_by_address.values(),
                key=lambda r: r.timestamp,
            )
            serialized = "\n".join(item.to_line() for item in sorted_records)
            if serialized:
                serialized += "\n"
            self._file_path.write_text(serialized, encoding="utf-8")

        if previous:
            logger.info(
                "Updated timestamp for address %s (old=%s new=%s)",
                record.address,
                previous.timestamp.isoformat(),
                record.timestamp.isoformat(),
            )
        else:
            logger.info("Appended address %s", record.address)

    def read_all(self) -> List[AddressRecord]:
        with self._lock:
            lines = self._file_path.read_text(encoding="utf-8").splitlines()
        records: List[AddressRecord] = []
        for line in lines:
            record = AddressRecord.from_line(line)
            if record:
                records.append(record)
        return records

    def read_latest(self) -> Optional[AddressRecord]:
        with self._lock:
            lines = self._file_path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            record = AddressRecord.from_line(line)
            if record:
                return record
        return None

    def backup(self) -> Optional[Path]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_dir = CONFIG.storage.backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"addresses_{timestamp}.txt"
        try:
            with self._lock:
                data = self._file_path.read_bytes()
            target.write_bytes(data)
            logger.info("Created backup file at %s", target)
            return target
        except OSError as exc:
            logger.error("Failed to create backup file: %s", exc)
            return None

    def iter_latest(self, limit: int = 10) -> Iterable[AddressRecord]:
        with self._lock:
            lines = self._file_path.read_text(encoding="utf-8").splitlines()
        count = 0
        for line in reversed(lines):
            if count >= limit:
                break
            record = AddressRecord.from_line(line)
            if record:
                count += 1
                yield record

    def clear(self) -> None:
        with self._lock:
            self._file_path.write_text("", encoding="utf-8")
        logger.warning("Address repository cleared")


def create_record(address: str, timestamp: datetime | None = None) -> AddressRecord:
    ts = timestamp or datetime.now(timezone.utc)
    return AddressRecord(timestamp=ts, address=address)
