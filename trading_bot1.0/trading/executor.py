from __future__ import annotations

import asyncio
import re
import time
from typing import Optional, Sequence

import pyautogui
import pyperclip
from playwright.async_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)
from pywinauto import Application, Desktop
from pywinauto.base_wrapper import BaseWrapper
from pywinauto.findwindows import ElementNotFoundError

from config import CONFIG
from logging_utils.logger import get_logger


logger = get_logger(__name__)
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


class BinanceTrader:
    """Executes a full-balance buy on Binance Web3 for the supplied address."""

    def __init__(self) -> None:
        self._config = CONFIG.trade
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._lock = asyncio.Lock()

    async def _ensure_playwright_started(self) -> None:
        if self._playwright:
            return
        self._playwright = await async_playwright().start()

        launch_kwargs: dict[str, object] = {
            "headless": self._config.headless,
        }
        channel = self._config.browser_channel
        executable = self._config.browser_executable_path
        if executable:
            launch_kwargs["executable_path"] = executable
            channel = None
        if channel:
            launch_kwargs["channel"] = channel

        if self._config.browser_profile_path:
            self._context = await self._playwright.chromium.launch_persistent_context(
                self._config.browser_profile_path,
                **launch_kwargs,
            )
        else:
            self._browser = await self._playwright.chromium.launch(
                **launch_kwargs,
            )
            self._context = await self._browser.new_context()

        self._page = await self._context.new_page()
        logger.info("Playwright browser launched")

    async def close(self) -> None:
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Trading executor shutdown complete")

    async def execute_trade(self, address: str) -> None:
        async with self._lock:
            mode = self._config.automation_mode
            if mode == "gui":
                logger.info("Executing GUI-based trade flow for %s", address)
                await asyncio.to_thread(self._execute_gui_flow, address)
                logger.info("GUI trade flow finished for %s", address)
                return

            await self._ensure_playwright_started()
            assert self._page is not None
            await self._navigate()
            await self._prepare_trade(address)
            await self._complete_trade(address)

    async def _navigate(self) -> None:
        assert self._page is not None
        url = self._config.binance_trading_url
        logger.info("Navigating to %s", url)
        await self._page.goto(url, wait_until="networkidle")

    async def _prepare_trade(self, address: str) -> None:
        if not self._page:
            raise RuntimeError("No active browser page")
        if "markets/trending" not in self._config.binance_trading_url:
            return
        logger.info("Attempting trending page search flow for %s", address)
        await self._page.wait_for_load_state("networkidle")
        search_input = await self._locate_first_visible(
            self._config.trending_search_input_selectors,
            timeout=6000,
        )
        if search_input:
            try:
                await self._fill_locator(search_input, address)
                await self._page.keyboard.press("Enter")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to type address into search input: %s", exc)
        else:
            logger.warning(
                "Trending search input not found using selectors %s",
                self._config.trending_search_input_selectors,
            )

        if await self._wait_for_swap_url():
            return

        result = await self._locate_first_visible(
            self._config.trending_search_result_selectors,
            timeout=5000,
        )
        if result:
            logger.info("Clicking trending search result for %s", address)
            await result.click()
            await self._switch_to_last_page()
            if await self._wait_for_swap_url():
                return
        else:
            logger.debug(
                "No visible search result found for selectors %s",
                self._config.trending_search_result_selectors,
            )

        trade_button = await self._locate_first_visible(
            self._config.trending_trade_button_selectors,
            timeout=5000,
        )
        if trade_button:
            logger.info("Clicking trade button for %s", address)
            await trade_button.click()
            await self._switch_to_last_page()
            if await self._wait_for_swap_url():
                return
        else:
            logger.debug(
                "No trade button located via selectors %s",
                self._config.trending_trade_button_selectors,
            )

        if self._config.swap_url_template:
            target = self._config.swap_url_template.format(address=address)
            logger.info("Falling back to direct swap URL %s", target)
            await self._page.goto(target, wait_until="networkidle")
            await self._switch_to_last_page()
            await self._wait_for_swap_url()
        else:
            logger.warning(
                "Trending flow did not reach swap interface; continuing with current page %s",
                self._page.url,
            )

    async def _complete_trade(self, address: str) -> None:
        if not self._page:
            raise RuntimeError("No active browser page")
        await self._ensure_on_swap_page(address)

        logger.info("Submitting trade for %s", address)
        address_input = await self._locate_first_visible(
            self._config.address_input_selectors,
            timeout=15_000,
        )
        if not address_input:
            raise RuntimeError(
                f"Address input not found using selectors {self._config.address_input_selectors}"
            )
        await self._fill_locator(address_input, address)

        await self._click_first_available(
            self._config.max_buy_button_selectors,
            "max buy button",
        )
        await self._page.wait_for_timeout(500)
        await self._click_first_available(
            self._config.confirm_button_selectors,
            "confirm purchase button",
        )
        logger.info("Trade confirmation clicked for %s", address)

    async def _locate_first_visible(
        self,
        selectors: Sequence[str],
        *,
        timeout: int = 5000,
    ) -> Optional[Locator]:
        if not selectors:
            return None
        if not self._page:
            return None
        for selector in selectors:
            locator = self._page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=timeout)
                return locator
            except PlaywrightTimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001
                logger.debug("Selector %s raised %s", selector, exc)
                continue
        return None

    async def _fill_locator(self, locator: Locator, value: str) -> None:
        if not self._page:
            return
        try:
            await locator.fill("")
        except Exception:
            try:
                await locator.click()
                await self._page.keyboard.press("Control+A")
                await self._page.keyboard.press("Delete")
            except Exception:
                logger.debug("Unable to clear input before typing")
        try:
            await locator.fill(value)
        except Exception:
            await locator.type(value, delay=30)

    async def _click_first_available(
        self,
        selectors: Sequence[str],
        description: str,
    ) -> None:
        locator = await self._locate_first_visible(selectors, timeout=10_000)
        if not locator:
            raise RuntimeError(
                f"Failed to locate {description} using selectors {selectors}"
            )
        await locator.click()
        await self._switch_to_last_page()

    async def _wait_for_swap_url(self, timeout: int = 8000) -> bool:
        if not self._page:
            return False
        pattern = re.compile(r"/swap", re.IGNORECASE)
        try:
            await self._page.wait_for_url(pattern, timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False

    async def _ensure_on_swap_page(self, address: str) -> None:
        if await self._wait_for_swap_url(timeout=5000):
            return
        if self._config.swap_url_template:
            target = self._config.swap_url_template.format(address=address)
            logger.info("Navigating directly to swap page %s", target)
            await self._page.goto(target, wait_until="networkidle")
            await self._switch_to_last_page()
            await self._wait_for_swap_url(timeout=5000)

    async def _switch_to_last_page(self) -> Optional[Page]:
        if not self._context:
            return self._page
        pages = self._context.pages
        if not pages:
            return self._page
        current = pages[-1]
        if current is not self._page:
            self._page = current
            try:
                await current.wait_for_load_state()
            except PlaywrightTimeoutError:
                pass
            try:
                await current.bring_to_front()
            except Exception:
                logger.debug("Unable to bring new page to front")
        return self._page

    def _execute_gui_flow(self, address: str) -> None:
        window = self._focus_chrome_window()
        if not window:
            raise RuntimeError("Unable to resolve Chrome window for GUI flow")
        self._run_fixed_click_sequence(address)

    def _run_fixed_click_sequence(self, address: str) -> None:
        cfg = self._config
        self._copy_to_clipboard(address)
        logger.info("Starting fixed click sequence for address %s", address)

        # Step 1: click address field and paste
        self._click_absolute_point(
            cfg.chrome_address_field_point,
            "address field",
            clicks=1,
            pause=0.1,
        )
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
        logger.info("Pasted address into Binance search input")
        time.sleep(4.5)

        # Step 2: click search result row
        self._click_absolute_point(
            cfg.chrome_result_row_point,
            "search result row",
            clicks=1,
            pause=0.1,
        )
        logger.info("Selected token via fixed search row")
        time.sleep(2.5)

        # Step 3: copy price, adjust, copy back
        self._click_absolute_point(
            cfg.chrome_price_field_point,
            "price field",
            clicks=2,
            pause=0.1,
        )
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.05)
        raw_value = pyperclip.paste()
        adjusted_value = self._adjust_price_value(raw_value)
        self._copy_to_clipboard(adjusted_value)
        logger.info("Copied price %s and adjusted to %s", raw_value, adjusted_value)

        # Step 4: paste adjusted value into quantity field
        self._click_absolute_point(
            cfg.chrome_quantity_field_point,
            "quantity input",
            clicks=1,
            pause=0.1,
        )
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
        logger.info("Pasted adjusted quantity %s", adjusted_value)
        time.sleep(0.5)

        # Step 5: click buy button
        self._click_absolute_point(
            cfg.chrome_buy_button_point,
            "buy button",
            clicks=1,
            pause=0.2,
        )
        logger.info("Clicked buy button via fixed sequence")
        time.sleep(5.0)
        self._click_absolute_point(
            cfg.chrome_back_button_point,
            "back button",
            clicks=1,
            pause=0.2,
        )
        logger.info("Clicked back button point")
        pyautogui.hotkey("alt", "left")
        logger.info("Triggered browser back shortcut")

    def _navigate_existing_chrome(self, window: BaseWrapper, url: str) -> None:
        self._copy_to_clipboard(url)
        self._click_window_ratio(
            window,
            self._config.chrome_address_bar_ratio,
            "address bar",
            clicks=2,
            pause=0.3,
        )
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
        pyautogui.press("enter")
        logger.info("Chrome navigation triggered for %s", url)
        time.sleep(max(0.8, self._config.chrome_page_load_seconds))

    def _open_search_drawer(self, window: BaseWrapper) -> None:
        if self._config.chrome_use_absolute_points:
            return
        self._click_window_ratio(
            window,
            self._config.chrome_search_icon_ratio,
            "search icon",
            pause=0.3,
        )

    def _perform_search(self, window: BaseWrapper, address: str) -> None:
        self._copy_to_clipboard(address)
        if self._config.chrome_use_absolute_points:
            time.sleep(0.5)
            self._click_absolute_point(
                self._config.chrome_address_field_point,
                "address field",
                clicks=1,
                pause=0.1,
            )
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "v")
            logger.info("Address pasted via absolute field")
            time.sleep(0.2)
            self._click_absolute_point(
                self._config.chrome_result_row_point,
                "search result row",
                clicks=1,
                pause=0.2,
            )
            logger.info("Selected token via absolute row")
            time.sleep(0.2)
            return

        self._click_window_ratio(
            window,
            self._config.chrome_search_input_ratio,
            "search input",
            clicks=2,
            pause=0.2,
        )
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
        logger.info("Address pasted into search field")
        time.sleep(max(0.7, self._config.chrome_result_wait_seconds))
        self._click_window_ratio(
            window,
            self._config.chrome_result_click_ratio,
            "search result",
            pause=0.4,
        )
        logger.info("Clicked token result")
        time.sleep(max(1.0, self._config.chrome_trade_wait_seconds))

    def _copy_price_and_fill_quantity(self, window: BaseWrapper) -> None:
        if self._config.chrome_use_absolute_points:
            self._click_absolute_point(
                self._config.chrome_price_field_point,
                "price value",
                clicks=2,
                pause=0.1,
            )
            pyautogui.hotkey("ctrl", "c")
            logger.debug("Copied current price via absolute point")
            time.sleep(0.05)
            adjusted = self._adjust_price_value(pyperclip.paste())
            pyperclip.copy(adjusted)
            self._click_absolute_point(
                self._config.chrome_quantity_field_point,
                "quantity input",
                clicks=1,
                pause=0.1,
            )
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "v")
            logger.info("Pasted adjusted price %s into quantity input", adjusted)
            time.sleep(0.1)
            return

        self._click_window_ratio(
            window,
            self._config.chrome_price_value_ratio,
            "price value",
            clicks=2,
            pause=0.2,
        )
        pyautogui.hotkey("ctrl", "c")
        logger.info("Copied current price")
        time.sleep(0.2)
        self._click_window_ratio(
            window,
            self._config.chrome_quantity_input_ratio,
            "quantity input",
            clicks=2,
            pause=0.2,
        )
        pyautogui.hotkey("ctrl", "v")
        logger.info("Pasted price into quantity input")
        time.sleep(0.3)

    def _submit_buy(self, window: BaseWrapper) -> None:
        if self._config.chrome_use_absolute_points:
            self._click_absolute_point(
                self._config.chrome_buy_button_point,
                "buy button",
                pause=0.2,
            )
            logger.info("Clicked buy button (absolute)")
            return

        self._click_window_ratio(
            window,
            self._config.chrome_buy_button_ratio,
            "buy button",
            pause=0.4,
        )
        logger.info("Clicked buy button")
        self._click_window_ratio(
            window,
            self._config.chrome_confirm_button_ratio,
            "confirm button",
            pause=0.5,
        )
        logger.info("Clicked confirm button")

    def _focus_chrome_window(self) -> BaseWrapper:
        try:
            last_error: ElementNotFoundError | None = None
            for pattern in self._candidate_chrome_title_patterns():
                try:
                    return self._connect_window(title_re=pattern)
                except ElementNotFoundError as exc:
                    last_error = exc
                    logger.debug("Chrome window not found via pattern %s", pattern)

            titles = self._list_chrome_windows()
            logger.error("Chrome windows currently visible: %s", titles or "none")
            for title in titles:
                normalized = title.lower()
                if "bsc" in normalized and ("甯佸畨" in title or "binance" in normalized):
                    logger.info("Falling back to Chrome window titled %s", title)
                    return self._connect_window(title=title)
            pattern = self._config.chrome_window_title_pattern
            raise RuntimeError(
                f"Chrome window matching pattern {pattern!r} not found"
            ) from last_error
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Failed to focus Chrome window") from exc

    def _connect_window(self, *, title: str | None = None, title_re: str | None = None) -> BaseWrapper:
        kwargs: dict[str, str] = {}
        if title:
            kwargs["title"] = title
        if title_re:
            kwargs["title_re"] = title_re
        app = Application(backend="uia").connect(**kwargs)
        window = app.window(**kwargs)
        window.set_focus()
        window.set_focus()
        time.sleep(0.2)
        return window

    def _list_chrome_windows(self) -> list[str]:
        try:
            desktop = Desktop(backend="uia")
            titles = []
            for win in desktop.windows():
                title = win.window_text()
                if "chrome" in title.lower() or "binance" in title.lower():
                    titles.append(title)
            return titles
        except Exception:
            return []

    def _click_window_ratio(
        self,
        window: BaseWrapper,
        ratio: tuple[float, float],
        description: str,
        *,
        clicks: int = 1,
        pause: float = 0.2,
    ) -> None:
        try:
            window.set_focus()
        except Exception:
            logger.debug("Unable to refocus Chrome window before %s", description)
        rect = window.rectangle()
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        x = rect.left + int(width * ratio[0])
        y = rect.top + int(height * ratio[1])
        pyautogui.moveTo(x, y, duration=0.1)
        pyautogui.click(x=x, y=y, clicks=clicks, interval=0.05)
        logger.debug("Clicked %s at (%s, %s)", description, x, y)
        time.sleep(pause)

    def _click_absolute_point(
        self,
        point: tuple[int, int],
        description: str,
        *,
        clicks: int = 1,
        pause: float = 0.1,
    ) -> None:
        x, y = point
        pyautogui.moveTo(x, y, duration=0.05)
        pyautogui.click(x=x, y=y, clicks=clicks, interval=0.04)
        logger.debug("Clicked %s at absolute point (%s, %s)", description, x, y)
        time.sleep(pause)

    def _adjust_price_value(self, raw_value: str) -> str:
        cleaned = raw_value.replace(",", "").strip()
        digits = "".join(ch for ch in cleaned if ch.isdigit() or ch in ".-")
        try:
            value = float(digits)
        except ValueError:
            value = 0.0
        adjusted = max(0.0, value - self._config.chrome_price_offset)
        return f"{adjusted:.6f}"

    def _copy_to_clipboard(self, text: str) -> None:
        for _ in range(3):
            pyperclip.copy(text)
            if pyperclip.paste() == text:
                return
            time.sleep(0.1)
            logger.warning("Clipboard content mismatch while setting %s", text[:8])

    def _candidate_chrome_title_patterns(self) -> tuple[str, ...]:
        requested = self._config.chrome_window_title_pattern.strip()
        defaults = (
            r"(BSC 甯傚満涓婄殑鐑棬浠ｅ竵鍜?Meme 甯?\| 甯佸畨閽卞寘 - Google Chrome)",
            r"(BSC 甯傚満涓婄殑鐑棬浠ｅ竵)|Binance Web3",
            r"Binance Web3",
            r"Binance",
            r"Google Chrome",
        )
        patterns: list[str] = []
        if requested:
            patterns.append(requested)
        for pattern in defaults:
            if pattern and pattern not in patterns:
                patterns.append(pattern)
        return tuple(patterns)

