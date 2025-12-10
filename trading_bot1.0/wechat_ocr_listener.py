from __future__ import annotations

import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

import cv2
import numpy as np
import pyautogui
import re
from pywinauto import Application, Desktop
from pywinauto.base_wrapper import BaseWrapper
from pywinauto.findwindows import ElementNotFoundError
from pytesseract import TesseractError

from config import CONFIG
from logging_utils.logger import get_logger
from storage.address_repo import AddressRepository, AddressRecord, create_record
from utils.ocr_engine import OcrEngine


logger = get_logger(__name__)
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0


class WindowNotFoundError(RuntimeError):
    pass


class WeChatOCRListener:
    """Continuously captures a region of the WeChat window and extracts BSC addresses."""

    def __init__(
        self,
        repository: AddressRepository,
        on_new_record: Callable[[AddressRecord], None],
        ocr_engine: OcrEngine | None = None,
    ) -> None:
        self._config = CONFIG.ocr
        self._repo = repository
        self._on_new_record = on_new_record
        self._ocr_engine = ocr_engine or self._build_ocr_engine()
        self._log_tesseract_path()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_address: Optional[str] = None
        self._window: Optional[BaseWrapper] = None
        self._scan_interval = max(1.5, self._config.poll_interval_seconds)
        self._last_feedback_address: Optional[str] = None
        self._temp_file: Path = CONFIG.storage.temp_scan_file
        self._temp_file.parent.mkdir(parents=True, exist_ok=True)
        self._clear_temp_addresses()
        self._paused = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("WeChat OCR listener already running")
            return
        try:
            self._ocr_engine.ensure_ready()
        except RuntimeError as exc:
            logger.error("%s", exc)
            raise
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="WeChatOCR", daemon=True)
        self._thread.start()
        logger.info("WeChat OCR listener started")

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)
            logger.info("WeChat OCR listener stopped")

    def _loop(self) -> None:
        interval = self._scan_interval
        while self._running.is_set():
            started = time.perf_counter()
            try:
                if self._paused.is_set():
                    time.sleep(0.2)
                    continue
                frame = self._capture_frame()
                addresses = self._process_frame(frame)
                temp_record = self._write_temp_addresses(addresses)
                latest = temp_record.address if temp_record else None
                self._report_latest(latest)
                self._log_scan_result(latest, addresses)
                self._handle_latest_record(temp_record)
            except WindowNotFoundError as exc:
                logger.error("Target WeChat window not found: %s", exc)
                self._window = None
                time.sleep(5.0)
            except TesseractError as exc:
                self._handle_ocr_failure(exc)
            except Exception as exc:
                logger.exception("Unexpected error in OCR loop: %s", exc)
                time.sleep(2.0)
            else:
                elapsed = time.perf_counter() - started
                remaining = interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
                else:
                    logger.debug(
                        "OCR loop took %.3fs (interval %.3fs)",
                        elapsed,
                        interval,
                    )
            finally:
                self._clear_temp_addresses()

    def _capture_frame(self) -> np.ndarray:
        window = self._locate_window()
        if self._config.force_focus:
            self._focus_window(window, ensure_foreground=True)
        rect = window.rectangle()
        try:
            logger.debug(
                "WeChat window title=%s rect=(%s,%s,%s,%s)",
                window.window_text(),
                rect.left,
                rect.top,
                rect.right,
                rect.bottom,
            )
        except Exception:
            pass
        region = self._get_chat_region(rect.left, rect.top, rect.right, rect.bottom)
        logger.debug(
            "Chat capture region (x=%s, y=%s, w=%s, h=%s)",
            region[0],
            region[1],
            region[2],
            region[3],
        )
        snapshot = window.capture_as_image()
        if snapshot is None:
            fallback = pyautogui.screenshot(region=region)
            image = cv2.cvtColor(np.array(fallback), cv2.COLOR_RGB2GRAY)
            processed = self._preprocess_frame(image)
            self._maybe_save_debug_frame(processed)
            return processed

        left, top = rect.left, rect.top
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        rel_left = max(0, min(width, region[0] - left))
        rel_top = max(0, min(height, region[1] - top))
        rel_right = max(rel_left + 1, min(width, rel_left + region[2]))
        rel_bottom = max(rel_top + 1, min(height, rel_top + region[3]))
        crop_box = (rel_left, rel_top, rel_right, rel_bottom)
        cropped = snapshot.crop(crop_box)
        image = cv2.cvtColor(np.array(cropped), cv2.COLOR_RGB2GRAY)
        processed = self._preprocess_frame(image)
        self._maybe_save_debug_frame(processed)
        return processed

    def _preprocess_frame(self, image: np.ndarray) -> np.ndarray:
        cfg = self._config
        processed = image
        kernel = max(1, cfg.gaussian_kernel_size)
        if kernel % 2 == 0:
            kernel += 1
        if kernel >= 3:
            processed = cv2.GaussianBlur(processed, (kernel, kernel), 0)

        if cfg.use_adaptive_threshold:
            block_size = cfg.threshold_block_size
            if block_size % 2 == 0:
                block_size += 1
            block_size = max(3, block_size)
            processed = cv2.adaptiveThreshold(
                processed,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                block_size,
                cfg.threshold_constant,
            )
        return processed

    def _locate_window(self) -> BaseWrapper:
        if self._window is not None:
            try:
                if self._window.exists() and self._window.is_visible():
                    if self._config.force_focus:
                        self._focus_window(self._window)
                    return self._window
            except Exception:
                self._window = None

        backend = self._config.pywinauto_backend
        errors: list[str] = []
        requested_title = self._config.window_title_pattern.strip()
        for idx, title in enumerate(self._candidate_title_patterns()):
            try:
                app = Application(backend=backend).connect(title_re=title)
                window = app.window(title_re=title)
                if self._config.force_focus:
                    self._focus_window(window)
                if idx > 0 and requested_title:
                    logger.warning(
                        "Configured WeChat title pattern %s did not match; fell back to default %s",
                        requested_title,
                        title,
                    )
                self._window = window
                return window
            except ElementNotFoundError:
                errors.append(f"title={title!r}")

        requested_class = self._config.window_class_name.strip()
        for idx, class_name in enumerate(self._candidate_class_names()):
            try:
                app = Application(backend=backend).connect(class_name=class_name)
                window = app.window(class_name=class_name)
                if self._config.force_focus:
                    self._focus_window(window)
                if idx > 0 and requested_class:
                    logger.warning(
                        "Configured WeChat class name %s did not match; fell back to %s",
                        requested_class,
                        class_name,
                    )
                self._window = window
                return window
            except ElementNotFoundError:
                errors.append(f"class={class_name!r}")

        fallback = self._scan_desktop_for_window(backend)
        if fallback:
            logger.warning(
                "Fell back to desktop scan; using WeChat window titled %s",
                fallback.window_text(),
            )
            self._window = fallback
            return fallback

        detail = " / ".join(errors) if errors else "unknown"
        raise WindowNotFoundError(detail)

    def _candidate_title_patterns(self) -> tuple[str, ...]:
        requested = self._config.window_title_pattern.strip()
        defaults = (
            r".*锁子密码.*禁言群.*",
            "锁子密码【禁言群】🚫",
            "微信",
            r".*微信.*",
            r"WeChat",
            r"Weixin",
        )
        candidates: list[str] = []
        if requested:
            candidates.append(requested)
        for pattern in defaults:
            if pattern and pattern not in candidates:
                candidates.append(pattern)
        return tuple(candidates)

    def _candidate_class_names(self) -> tuple[str, ...]:
        requested = self._config.window_class_name.strip()
        defaults = ("WeChatMainWndForPC", "ChatWnd")
        candidates: list[str] = []
        if requested:
            candidates.append(requested)
        for class_name in defaults:
            if class_name and class_name not in candidates:
                candidates.append(class_name)
        return tuple(candidates)

    def _scan_desktop_for_window(self, backend: str) -> Optional[BaseWrapper]:
        try:
            desktop = Desktop(backend=backend)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Unable to access desktop for fallback scan: %s", exc)
            return None

        title_patterns = self._candidate_title_patterns()
        class_names = self._candidate_class_names()
        for win in desktop.windows():
            title = win.window_text()
            cls = ""
            try:
                cls = win.friendly_class_name()
            except Exception:  # noqa: BLE001
                cls = ""
            if self._matches_any_pattern(title, title_patterns) or cls in class_names:
                try:
                    top = win.top_level_parent()
                except Exception:  # noqa: BLE001
                    top = win
                if self._config.force_focus:
                    self._focus_window(top)
                return top
        return None

    def _matches_any_pattern(self, title: str, patterns: Sequence[str]) -> bool:
        for pattern in patterns:
            if not pattern:
                continue
            try:
                if re.search(pattern, title):
                    return True
            except re.error:
                if pattern == title:
                    return True
        return False

    def _focus_window(self, window: BaseWrapper, *, ensure_foreground: bool = False) -> None:
        try:
            window.set_focus()
        except Exception as exc:
            logger.debug("Unable to focus WeChat window: %s", exc)
        if ensure_foreground:
            self._ensure_foreground(window)

    def _ensure_foreground(self, window: BaseWrapper) -> None:
        try:
            window.restore()
        except Exception:
            pass
        try:
            top = window.top_level_parent()
            top.set_focus()
        except Exception:
            try:
                window.set_focus()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Unable to bring WeChat window to foreground: %s", exc)

    def _get_chat_region(self, left: int, top: int, right: int, bottom: int) -> Tuple[int, int, int, int]:
        width = right - left
        height = bottom - top
        chat_left = left + int(width * self._config.chat_left_ratio)
        chat_top = top + self._config.chat_top_offset
        chat_right = right - self._config.chat_right_offset
        chat_bottom = bottom - self._config.chat_bottom_offset

        chat_left = max(chat_left, left)
        chat_top = max(chat_top, top)
        chat_right = max(chat_right, chat_left + self._config.min_capture_width)
        chat_bottom = max(chat_bottom, chat_top + self._config.min_capture_height)

        region = (
            chat_left,
            chat_top,
            chat_right - chat_left,
            chat_bottom - chat_top,
        )
        return region

    def _process_frame(self, frame: np.ndarray) -> Sequence[str]:
        text = self._ocr_engine.run_ocr(frame)
        if logger.isEnabledFor(10):  # DEBUG
            preview = text.replace("\n", " ")[:200]
            logger.debug("OCR raw text preview: %s", preview)
        text = unicodedata.normalize("NFKC", text)
        if self._config.normalize_letter_o:
            text = text.replace("O", "0").replace("o", "0")
        text = text.replace("X", "x")
        addresses = self._ocr_engine.extract_addresses(text)
        if logger.isEnabledFor(10):
            logger.debug("Extracted addresses: %s", addresses)
        return addresses

    def _handle_latest_record(self, record: Optional[AddressRecord]) -> None:
        if not record:
            return
        history = self._repo.read_all()
        should_trade = self._should_execute_trade(record, history)
        self._repo.append(record)
        self._last_address = record.address
        if should_trade:
            logger.info(
                "Captured tradable address %s at %s",
                record.address,
                record.timestamp.isoformat(),
            )
            try:
                self._on_new_record(record)
            except Exception as exc:
                logger.exception("on_new_record callback failed: %s", exc)
        else:
            logger.info(
                "Captured address %s at %s but suppressed trade",
                record.address,
                record.timestamp.isoformat(),
            )

    def _log_scan_result(
        self,
        latest: Optional[str],
        addresses: Sequence[str],
    ) -> None:
        if latest:
            logger.info(
                "OCR scan detected %s candidate(s); latest=%s",
                len(addresses),
                latest,
            )
        else:
            logger.info("OCR scan found no valid address")

    def _report_latest(self, latest: Optional[str]) -> None:
        if not latest:
            return
        if latest == self._last_feedback_address:
            return
        self._last_feedback_address = latest
        logger.info("Realtime latest address: %s", latest)

    def _write_temp_addresses(
        self,
        addresses: Sequence[str],
    ) -> Optional[AddressRecord]:
        if not addresses:
            self._clear_temp_addresses()
            return None
        records: list[AddressRecord] = []
        for raw in addresses:
            normalized = self._normalize_address(raw)
            if not normalized:
                continue
            timestamp = datetime.now(timezone.utc)
            records.append(create_record(normalized, timestamp=timestamp))
        if not records:
            self._clear_temp_addresses()
            return None
        data = "\n".join(record.to_line() for record in records) + "\n"
        try:
            self._temp_file.write_text(data, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to write temp address file: %s", exc)
        return records[-1]

    def _clear_temp_addresses(self) -> None:
        try:
            if self._temp_file.exists():
                self._temp_file.write_text("", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to clear temp address file: %s", exc)

    def _normalize_address(self, candidate: Optional[str]) -> Optional[str]:
        if not candidate:
            return None
        text = unicodedata.normalize("NFKC", candidate)
        text = text.replace(" ", "").replace("\n", "").replace("\r", "")
        text = text.lower()
        if not text.startswith("0x"):
            return None
        if len(text) != 42:
            return None
        hex_part = text[2:]
        if not all(ch in "0123456789abcdef" for ch in hex_part):
            return None
        return text

    def _should_execute_trade(
        self,
        record: AddressRecord,
        history: Sequence[AddressRecord],
    ) -> bool:
        if not history:
            return True
        if all(existing.address != record.address for existing in history):
            return True
        sorted_history = sorted(history, key=lambda r: r.timestamp, reverse=True)
        rank: Optional[int] = None
        for idx, existing in enumerate(sorted_history):
            if existing.address == record.address:
                rank = idx + 1
                break
        if rank is None:
            return True
        return rank > 3

    def _maybe_save_debug_frame(self, frame: np.ndarray) -> None:
        if not logger.isEnabledFor(10):  # DEBUG level
            return
        debug_path = self._temp_file.parent / "debug_capture.png"
        try:
            cv2.imwrite(str(debug_path), frame)
            logger.debug("Saved debug capture to %s", debug_path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to save debug capture: %s", exc)

    def _build_ocr_engine(self) -> OcrEngine:
        return OcrEngine(
            address_pattern=self._config.address_regex,
            tesseract_cmd=self._config.tesseract_cmd,
            language=self._config.tesseract_lang,
        )

    def _handle_ocr_failure(self, exc: TesseractError) -> None:
        logger.error("Tesseract OCR failed: %s", exc)
        logger.info("Reinitializing OCR engine after failure")
        try:
            self._ocr_engine = self._build_ocr_engine()
        except Exception as rebuild_exc:  # noqa: BLE001
            logger.exception("Failed to rebuild OCR engine: %s", rebuild_exc)
        time.sleep(2.0)

    def _log_tesseract_path(self) -> None:
        path = self._config.tesseract_cmd
        if path:
            logger.info("Using Tesseract executable at %s", path)
        else:
            logger.warning(
                "Tesseract executable path not resolved; relying on system PATH lookup."
            )

    def pause(self) -> None:
        if not self._paused.is_set():
            logger.info("Pausing WeChat OCR listener")
            self._paused.set()

    def resume(self) -> None:
        if self._paused.is_set():
            logger.info("Resuming WeChat OCR listener")
            self._paused.clear()
