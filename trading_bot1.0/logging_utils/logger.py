from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from config import CONFIG


_LOGGER: Optional[logging.Logger] = None


def _configure_logger() -> logging.Logger:
    log_file: Path = CONFIG.logging.log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("auto_trader")
    logger.setLevel(getattr(logging, CONFIG.logging.level.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    if not logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        file_handler = RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    global _LOGGER
    if _LOGGER is None:
        _LOGGER = _configure_logger()
    if name:
        return _LOGGER.getChild(name)
    return _LOGGER

