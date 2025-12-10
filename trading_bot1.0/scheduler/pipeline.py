from __future__ import annotations

import asyncio
from asyncio import QueueEmpty
from datetime import datetime, timezone
from typing import Optional

from config import CONFIG
from logging_utils.logger import get_logger
from storage.address_repo import AddressRecord, AddressRepository
from trading.executor import BinanceTrader
from trading.time_guard import TimeGuard
from wechat_ocr_listener import WeChatOCRListener


logger = get_logger(__name__)


class TradingPipeline:
    """Coordinates OCR listener events with the trading executor."""

    def __init__(self) -> None:
        self._repo = AddressRepository()
        self._time_guard = TimeGuard()
        self._trader = BinanceTrader()
        self._queue: asyncio.Queue[AddressRecord] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listener = WeChatOCRListener(
            repository=self._repo,
            on_new_record=self._handle_new_record,
        )
        self._last_executed_address: Optional[str] = None
        self._last_execution_time: Optional[datetime] = None
        self._config = CONFIG.pipeline
        self._recent_executions: dict[str, datetime] = {}

    def _handle_new_record(self, record: AddressRecord) -> None:
        if not self._loop:
            logger.debug("Event loop not ready, dropping record %s", record.address)
            return
        asyncio.run_coroutine_threadsafe(self._queue.put(record), self._loop)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            self._listener.start()
        except Exception as exc:
            logger.error("Failed to start WeChat OCR listener: %s", exc)
            await self._trader.close()
            return
        logger.info("Trading pipeline started")
        try:
            while True:
                record = await self._queue.get()
                while True:
                    try:
                        record = self._queue.get_nowait()
                    except QueueEmpty:
                        break
                await self._process_record(record)
        except asyncio.CancelledError:
            logger.info("Trading pipeline cancelled")
        finally:
            self._listener.stop()
            await self._trader.close()

    async def _process_record(self, record: AddressRecord) -> None:
        if not self._time_guard.is_recent(record):
            logger.warning("Discarding stale record %s", record)
            return

        latest = self._repo.read_latest()
        if not latest or latest.address != record.address or latest.timestamp != record.timestamp:
            logger.debug("Skipping record %s; not the latest", record.address)
            return

        if self._should_skip(record):
            logger.info("Address %s already processed recently; skipping", record.address)
            return

        self._listener.pause()
        try:
            await self._execute_with_retry(record.address)
        finally:
            self._listener.resume()
        now = datetime.now(timezone.utc)
        self._last_executed_address = record.address
        self._last_execution_time = now
        self._recent_executions[record.address] = now
        self._prune_recent_executions(now)

    def _should_skip(self, record: AddressRecord) -> bool:
        last_exec = self._recent_executions.get(record.address)
        if not last_exec:
            return False
        elapsed = datetime.now(timezone.utc) - last_exec
        return elapsed.total_seconds() < self._config.debounce_seconds

    def _prune_recent_executions(self, reference: datetime | None = None) -> None:
        if not self._recent_executions:
            return
        now = reference or datetime.now(timezone.utc)
        threshold = self._config.debounce_seconds
        stale = [
            address
            for address, ts in self._recent_executions.items()
            if (now - ts).total_seconds() >= threshold
        ]
        for address in stale:
            self._recent_executions.pop(address, None)

    async def _execute_with_retry(self, address: str) -> None:
        attempts = self._config.retry_attempts
        delay = self._config.retry_delay_seconds
        for attempt in range(1, attempts + 1):
            try:
                await self._trader.execute_trade(address)
                logger.info("Trade executed successfully for %s", address)
                return
            except Exception as exc:
                logger.exception(
                    "Trade attempt %s/%s failed for %s: %s",
                    attempt,
                    attempts,
                    address,
                    exc,
                )
                if attempt < attempts:
                    await asyncio.sleep(delay)
        logger.error("All trade attempts failed for %s", address)
