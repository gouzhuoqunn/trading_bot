from __future__ import annotations

import asyncio

from logging_utils.logger import get_logger
from scheduler.pipeline import TradingPipeline


logger = get_logger(__name__)


def main() -> None:
    pipeline = TradingPipeline()
    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        logger.info(
            "Interrupted by user. Run `python -m scripts.clear_bot_log` after exiting if you need a fresh bot.log."
        )


if __name__ == "__main__":
    main()
