from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_point(name: str, default: tuple[int, int]) -> tuple[int, int]:
    value = os.getenv(name)
    if not value:
        return default
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        return default
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return default


def _env_float_pair(name: str, default: tuple[float, float]) -> tuple[float, float]:
    value = os.getenv(name)
    if not value:
        return default
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != 2:
        return default
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return default


def _env_selectors(name: str, default: str, legacy: str | None = None) -> tuple[str, ...]:
    source = None
    if legacy:
        source = os.getenv(legacy)
    if source is None:
        source = os.getenv(name)
    if source is None:
        source = default
    selectors = [item.strip() for item in source.split(",") if item.strip()]
    return tuple(selectors)


def _resolve_tesseract_cmd() -> str | None:
    env_path = os.getenv("TESSERACT_CMD")
    if env_path:
        return env_path

    guesses = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\{}\AppData\Local\Programs\Tesseract-OCR\tesseract.exe".format(
            os.getenv("USERNAME", "")
        ),
    ]
    for guess in guesses:
        candidate = Path(guess)
        if candidate.exists():
            return str(candidate)

    which_result = shutil.which("tesseract")
    if which_result:
        return which_result

    return None


@dataclass(frozen=True)
class OCRConfig:
    window_title_pattern: str = os.getenv(
        "WECHAT_WINDOW_TITLE_PATTERN",
        r"(锁子密码【禁言群】🚫)|微信",
    )
    window_class_name: str = os.getenv(
        "WECHAT_WINDOW_CLASS_NAME",
        "WeChatMainWndForPC",
    )
    pywinauto_backend: str = os.getenv("WECHAT_PYWINBACKEND", "uia")
    poll_interval_seconds: float = max(1.5, _env_float("OCR_POLL_INTERVAL", 1.5))
    normalize_letter_o: bool = _env_bool("OCR_NORMALIZE_O", True)
    chat_left_ratio: float = _env_float("WECHAT_CHAT_LEFT_RATIO", 0.4)
    chat_top_offset: int = _env_int("WECHAT_CHAT_TOP_OFFSET", 100)
    chat_right_offset: int = _env_int("WECHAT_CHAT_RIGHT_OFFSET", 10)
    chat_bottom_offset: int = _env_int("WECHAT_CHAT_BOTTOM_OFFSET", 80)
    min_capture_width: int = _env_int("WECHAT_MIN_CAPTURE_WIDTH", 120)
    min_capture_height: int = _env_int("WECHAT_MIN_CAPTURE_HEIGHT", 120)
    force_focus: bool = _env_bool("WECHAT_FORCE_FOCUS", True)
    address_regex: str = r"0[xX][a-fA-F0-9]{40}"
    tesseract_cmd: str | None = _resolve_tesseract_cmd()
    tesseract_lang: str = os.getenv("TESSERACT_LANG", "eng")
    use_adaptive_threshold: bool = _env_bool(
        "OCR_USE_ADAPTIVE_THRESHOLD",
        True,
    )
    threshold_block_size: int = _env_int("OCR_THRESHOLD_BLOCK_SIZE", 31)
    threshold_constant: int = _env_int("OCR_THRESHOLD_CONSTANT", 6)
    gaussian_kernel_size: int = _env_int("OCR_GAUSSIAN_KERNEL_SIZE", 3)


@dataclass(frozen=True)
class StorageConfig:
    addresses_file: Path = Path(
        os.getenv("ADDRESSES_FILE", DATA_DIR / "addresses.txt")
    )
    backup_dir: Path = Path(
        os.getenv("ADDRESSES_BACKUP_DIR", DATA_DIR / "backup")
    )
    temp_scan_file: Path = Path(
        os.getenv("TEMP_SCAN_FILE", DATA_DIR / "temp_addresses.txt")
    )


@dataclass(frozen=True)
class TradeConfig:
    binance_trading_url: str = os.getenv(
        "BINANCE_TRADING_URL",
        "https://web3.binance.com/zh-CN/markets/trending?chain=bsc",
    )
    require_time_window_seconds: int = _env_int("TRADE_TIME_WINDOW_SECONDS", 20)
    address_input_selectors: tuple[str, ...] = _env_selectors(
        "BINANCE_ADDRESS_INPUT_SELECTORS",
        "input[data-testid='wallet-address-input'],input[placeholder*='合约地址'],input[placeholder*='地址'],input[aria-label*='地址']",
        legacy="BINANCE_ADDRESS_INPUT_SELECTOR",
    )
    max_buy_button_selectors: tuple[str, ...] = _env_selectors(
        "BINANCE_MAX_BUY_SELECTORS",
        "button[data-testid='max-balance-button'],button:has-text('最大'),button:has-text('Max')",
        legacy="BINANCE_MAX_BUY_SELECTOR",
    )
    confirm_button_selectors: tuple[str, ...] = _env_selectors(
        "BINANCE_CONFIRM_BUY_SELECTORS",
        "button[data-testid='confirm-purchase-button'],button:has-text('确认'),button:has-text('Confirm')",
        legacy="BINANCE_CONFIRM_BUY_SELECTOR",
    )
    trending_search_input_selectors: tuple[str, ...] = _env_selectors(
        "BINANCE_TRENDING_SEARCH_INPUT_SELECTORS",
        "input[placeholder*='搜索'],input[placeholder*='Search'],input[aria-label*='搜索'],input[data-testid*='search'],input[type='search']",
    )
    trending_search_result_selectors: tuple[str, ...] = _env_selectors(
        "BINANCE_TRENDING_RESULT_SELECTORS",
        "a[data-testid*='market'],div[data-testid*='search'][role='button'],div[role='option'],a[href*='/token/'],a[href*='/swap']",
    )
    trending_trade_button_selectors: tuple[str, ...] = _env_selectors(
        "BINANCE_TRENDING_TRADE_BUTTON_SELECTORS",
        "button:has-text('交易'),a:has-text('交易'),button:has-text('Swap'),a:has-text('Swap')",
    )
    swap_url_template: str = os.getenv(
        "BINANCE_SWAP_URL_TEMPLATE",
        "",
    )
    automation_mode: str = os.getenv("TRADE_AUTOMATION_MODE", "gui").lower()
    chrome_window_title_pattern: str = os.getenv(
        "CHROME_WINDOW_TITLE_PATTERN",
        r"(BSC 市场上的热门代币和 Meme 币 \| 币安钱包 - Google Chrome)|Binance|Google Chrome",
    )
    chrome_address_bar_ratio: tuple[float, float] = _env_float_pair(
        "CHROME_ADDRESS_BAR_RATIO",
        (0.32, 0.05),
    )
    chrome_search_icon_ratio: tuple[float, float] = _env_float_pair(
        "CHROME_SEARCH_ICON_RATIO",
        (0.82, 0.12),
    )
    chrome_search_input_ratio: tuple[float, float] = _env_float_pair(
        "CHROME_SEARCH_INPUT_RATIO",
        (0.63, 0.18),
    )
    chrome_result_click_ratio: tuple[float, float] = _env_float_pair(
        "CHROME_RESULT_CLICK_RATIO",
        (0.48, 0.38),
    )
    chrome_price_value_ratio: tuple[float, float] = _env_float_pair(
        "CHROME_PRICE_VALUE_RATIO",
        (0.78, 0.45),
    )
    chrome_quantity_input_ratio: tuple[float, float] = _env_float_pair(
        "CHROME_QUANTITY_INPUT_RATIO",
        (0.78, 0.58),
    )
    chrome_buy_button_ratio: tuple[float, float] = _env_float_pair(
        "CHROME_BUY_BUTTON_RATIO",
        (0.9, 0.82),
    )
    chrome_confirm_button_ratio: tuple[float, float] = _env_float_pair(
        "CHROME_CONFIRM_BUTTON_RATIO",
        (0.85, 0.88),
    )
    chrome_use_absolute_points: bool = _env_bool("CHROME_USE_ABSOLUTE_POINTS", True)
    chrome_address_field_point: tuple[int, int] = _env_point(
        "CHROME_ADDRESS_FIELD_POINT",
        (598, 440),
    )
    chrome_result_row_point: tuple[int, int] = _env_point(
        "CHROME_RESULT_ROW_POINT",
        (612, 650),
    )
    chrome_price_field_point: tuple[int, int] = _env_point(
        "CHROME_PRICE_FIELD_POINT",
        (957, 647),
    )
    chrome_quantity_field_point: tuple[int, int] = _env_point(
        "CHROME_QUANTITY_FIELD_POINT",
        (764, 724),
    )
    chrome_buy_button_point: tuple[int, int] = _env_point(
        "CHROME_BUY_BUTTON_POINT",
        (800, 1151),
    )
    chrome_back_button_point: tuple[int, int] = _env_point(
        "CHROME_BACK_BUTTON_POINT",
        (377, 443),
    )
    chrome_price_offset: float = _env_float("CHROME_PRICE_OFFSET", 0.006)
    chrome_page_load_seconds: float = _env_float("CHROME_PAGE_LOAD_SECONDS", 4.0)
    chrome_result_wait_seconds: float = _env_float("CHROME_RESULT_WAIT_SECONDS", 1.5)
    chrome_trade_wait_seconds: float = _env_float("CHROME_TRADE_WAIT_SECONDS", 2.5)
    play_alert_sound: bool = _env_bool("TRADE_PLAY_ALERT_SOUND", False)
    browser_profile_path: str | None = os.getenv(
        "PLAYWRIGHT_USER_DATA_DIR"
    )
    headless: bool = _env_bool("PLAYWRIGHT_HEADLESS", False)
    browser_channel: str | None = os.getenv(
        "PLAYWRIGHT_BROWSER_CHANNEL",
        "chrome",
    ) or None
    browser_executable_path: str | None = os.getenv(
        "PLAYWRIGHT_BROWSER_EXECUTABLE"
    )


@dataclass(frozen=True)
class LoggingConfig:
    level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: Path = Path(os.getenv("LOG_FILE", DATA_DIR / "bot.log"))


@dataclass(frozen=True)
class PipelineConfig:
    debounce_seconds: float = _env_float("PIPELINE_DEBOUNCE_SECONDS", 1.5)
    retry_attempts: int = _env_int("PIPELINE_RETRY_ATTEMPTS", 3)
    retry_delay_seconds: float = _env_float("PIPELINE_RETRY_DELAY", 2.0)


@dataclass(frozen=True)
class AppConfig:
    ocr: OCRConfig = OCRConfig()
    storage: StorageConfig = StorageConfig()
    trade: TradeConfig = TradeConfig()
    logging: LoggingConfig = LoggingConfig()
    pipeline: PipelineConfig = PipelineConfig()


def load_config() -> AppConfig:
    config = AppConfig()
    config.storage.addresses_file.parent.mkdir(parents=True, exist_ok=True)
    config.storage.backup_dir.mkdir(parents=True, exist_ok=True)
    config.storage.temp_scan_file.parent.mkdir(parents=True, exist_ok=True)
    config.logging.log_file.parent.mkdir(parents=True, exist_ok=True)
    return config


CONFIG = load_config()
