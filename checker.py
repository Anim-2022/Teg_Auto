import asyncio
import logging
import os
from playwright.async_api import async_playwright, Page, Frame, TimeoutError as PlaywrightTimeout

from config import TARGET_URL, HEADLESS, TIMEOUT

logger = logging.getLogger(__name__)


async def _navigate_to_calendar(page: Page) -> Frame | None:
    """Navigate through the form to the calendar page. Returns the iframe Frame or None."""
    # Cookie consent
    try:
        cookie_btn = page.locator("text=Das ist ok")
        if await cookie_btn.is_visible(timeout=3000):
            await cookie_btn.click()
            await page.wait_for_timeout(1000)
    except Exception:
        pass

    # Find tempus-termine iframe
    frame = None
    for f in page.frames:
        if "tempus-termine.com" in (f.url or ""):
            frame = f
            break
    if not frame:
        return None

    # Select service + privacy + submit
    await frame.locator("#ErtErw-788-mittermin").select_option("1")
    await page.wait_for_timeout(500)
    await frame.locator("#chkDatenschutz").check()
    await page.wait_for_timeout(500)
    await frame.locator("input[type='submit'][value='Weiter zur Terminauswahl »']").click()
    logger.info("Form submitted, waiting for calendar...")
    await page.wait_for_timeout(5000)

    # Re-find iframe after navigation
    for f in page.frames:
        if "tempus-termine.com" in (f.url or ""):
            return f
    return None


async def _parse_dates(frame: Frame) -> list[dict]:
    """Parse available dates from calendar tables in the frame."""
    available = []
    cal_tables = frame.locator("table.cal")
    table_count = await cal_tables.count()

    for t in range(table_count):
        table = cal_tables.nth(t)
        month_label = (await table.locator("th.monatslabel").inner_text()).strip()
        links = table.locator("td a")
        count = await links.count()
        for i in range(count):
            link = links.nth(i)
            text = (await link.inner_text()).strip()
            href = await link.get_attribute("href") or ""
            if text.isdigit():
                full_link = ""
                if href and not href.startswith("http"):
                    full_link = f"https://tempus-termine.com/termine/{href}"
                elif href.startswith("http"):
                    full_link = href
                available.append({"day": text, "month": month_label, "link": full_link})
    return available


async def check_available_dates() -> dict:
    """Check for available appointment dates. Returns dict with available_dates and error."""
    result = {"available_dates": [], "error": None}

    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await browser.new_context(
                locale="de-DE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT)

            logger.info("Opening %s", TARGET_URL)
            await page.goto(TARGET_URL, wait_until="networkidle")

            frame = await _navigate_to_calendar(page)
            if not frame:
                result["error"] = "Не удалось открыть календарь"
                return result

            result["available_dates"] = await _parse_dates(frame)
            if result["available_dates"]:
                logger.info("Found %d available slots!", len(result["available_dates"]))
            else:
                logger.info("No available dates")

        except PlaywrightTimeout as e:
            result["error"] = f"Таймаут: {e}"
            logger.error("Timeout: %s", e)
        except Exception as e:
            result["error"] = f"Ошибка: {e}"
            logger.error("Error: %s", e, exc_info=True)
        finally:
            if browser:
                await browser.close()

    return result


SCREENSHOT_PATH = "calendar_screenshot.png"


async def screenshot_calendar() -> dict:
    """Take a screenshot of just the calendar area. Returns dict with path and error."""
    result = {"path": None, "error": None}

    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await browser.new_context(
                locale="de-DE",
                viewport={"width": 1200, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT)

            await page.goto(TARGET_URL, wait_until="networkidle")

            frame = await _navigate_to_calendar(page)
            if not frame:
                result["error"] = "Не удалось открыть календарь"
                return result

            # Screenshot only the calendar container (menu_container has the tables)
            calendar_el = frame.locator("#menu_container")
            if await calendar_el.count() == 0:
                # Fallback: screenshot the whole iframe body
                calendar_el = frame.locator("#body_container")

            await calendar_el.screenshot(path=SCREENSHOT_PATH)
            result["path"] = SCREENSHOT_PATH
            logger.info("Calendar screenshot saved")

        except PlaywrightTimeout as e:
            result["error"] = f"Таймаут: {e}"
        except Exception as e:
            result["error"] = f"Ошибка: {e}"
            logger.error("Screenshot error: %s", e, exc_info=True)
        finally:
            if browser:
                await browser.close()

    return result


def cleanup_screenshot():
    """Remove the screenshot file."""
    try:
        os.remove(SCREENSHOT_PATH)
    except OSError:
        pass

