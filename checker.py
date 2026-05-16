import asyncio
import logging
import os
import traceback
import time
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from config import TARGET_URL, DIRECT_URL, HEADLESS, TIMEOUT

logger = logging.getLogger(__name__)

# Type for progress callback: async def(text: str) -> None
ProgressCallback = None  # just for docs


async def _navigate_to_calendar(page: Page, on_progress=None) -> Page | None:
    """Fill form and submit to reach the calendar. Works on DIRECT_URL (no iframe needed)."""
    step = "open_page"

    async def _progress(text):
        if on_progress:
            await on_progress(text)

    try:
        # Step 1: Open the form directly
        await _progress("🌐 Открываю форму записи...")
        logger.info("[nav] Opening %s", DIRECT_URL)
        await page.goto(DIRECT_URL, wait_until="domcontentloaded", timeout=20000)
        logger.info("[nav] Form page loaded")

        # Step 2: Select service
        step = "select_service"
        await _progress("📋 Выбираю: Ersterteilung/Erweiterung...")
        select_el = page.locator("#ErtErw-788-mittermin")
        await select_el.wait_for(state="visible", timeout=10000)
        await select_el.select_option("1")
        await page.wait_for_timeout(500)
        logger.info("[nav] Service selected (ErtErw=1)")

        # Step 3: Check privacy checkbox
        step = "check_privacy"
        await _progress("✅ Принимаю Datenschutz...")
        checkbox = page.locator("#chkDatenschutz")
        await checkbox.check()
        await page.wait_for_timeout(500)
        logger.info("[nav] Privacy checkbox checked")

        # Step 4: Submit form
        step = "submit_form"
        await _progress("🚀 Жму «Weiter zur Terminauswahl»...")
        submit_btn = page.locator("input[type='submit'][value='Weiter zur Terminauswahl »']")
        await submit_btn.click()
        logger.info("[nav] Form submitted, waiting for calendar...")

        # Step 5: Wait for calendar tables to appear
        step = "wait_calendar"
        await _progress("⏳ Жду загрузки календаря...")
        await page.wait_for_selector("table.cal", timeout=15000)
        logger.info("[nav] SUCCESS: Calendar loaded")
        return page

    except PlaywrightTimeout as e:
        logger.error("[nav] TIMEOUT at step '%s': %s", step, e)
        raise
    except Exception as e:
        logger.error("[nav] ERROR at step '%s': %s\n%s", step, e, traceback.format_exc())
        raise


async def _parse_dates(source) -> list[dict]:
    """Parse available dates from calendar tables. source can be Page or Frame."""
    available = []
    cal_tables = source.locator("table.cal")
    table_count = await cal_tables.count()
    logger.info("[parse] Found %d calendar tables", table_count)

    if table_count == 0:
        body_html = await source.locator("body").inner_text()
        logger.warning("[parse] No table.cal found. Body text (first 500): %s", body_html[:500])

    for t in range(table_count):
        table = cal_tables.nth(t)
        month_el = table.locator("th.monatslabel")
        if await month_el.count() == 0:
            logger.warning("[parse] Table %d has no th.monatslabel", t)
            continue
        month_label = (await month_el.inner_text()).strip()
        links = table.locator("td a")
        count = await links.count()
        logger.info("[parse] %s: %d links", month_label, count)
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

    logger.info("[parse] Total available dates: %d", len(available))
    return available


async def _run_with_browser(callback):
    """Run a callback with a Playwright browser, handling cleanup safely."""
    pw = None
    browser = None
    t0 = time.monotonic()
    try:
        logger.info("[browser] Starting Playwright...")
        pw = await async_playwright().start()
        logger.info("[browser] Launching Chromium (headless=%s)...", HEADLESS)
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
            ],
        )
        logger.info("[browser] Chromium launched in %.1fs", time.monotonic() - t0)
        logger.info("[browser] Creating context...")
        context = await browser.new_context(
            locale="de-DE",
            viewport={"width": 1200, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        logger.info("[browser] Creating page...")
        page = await context.new_page()
        page.set_default_timeout(TIMEOUT)
        logger.info("[browser] Page ready (%.1fs)", time.monotonic() - t0)
        result = await callback(page)
        logger.info("[browser] Callback done in %.1fs total", time.monotonic() - t0)
        return result
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if pw:
            try:
                await pw.stop()
            except Exception:
                pass
        logger.info("[browser] Cleanup done (%.1fs total)", time.monotonic() - t0)


async def check_available_dates(on_progress=None) -> dict:
    """Check for available appointment dates. Returns dict with available_dates and error."""
    result = {"available_dates": [], "error": None}

    async def _progress(text):
        if on_progress:
            await on_progress(text)

    async def _do_check(page):
        cal_page = await _navigate_to_calendar(page, on_progress)
        if not cal_page:
            result["error"] = "Не удалось открыть календарь"
            return result

        await _progress("📅 Сканирую календарь...")
        result["available_dates"] = await _parse_dates(cal_page)
        if result["available_dates"]:
            logger.info("[check] FOUND %d available slots!", len(result["available_dates"]))
        else:
            logger.info("[check] No available dates")
        return result

    try:
        return await _run_with_browser(_do_check)
    except PlaywrightTimeout as e:
        result["error"] = f"Таймаут при загрузке: {e}"
        logger.error("[check] TIMEOUT: %s", e)
    except Exception as e:
        result["error"] = f"Ошибка: {type(e).__name__}: {e}"
        logger.error("[check] EXCEPTION: %s", e, exc_info=True)
    return result


SCREENSHOT_PATH = "calendar_screenshot.png"


async def screenshot_calendar(on_progress=None) -> dict:
    """Take a screenshot of just the calendar area. Returns dict with path and error."""
    result = {"path": None, "error": None}

    async def _progress(text):
        if on_progress:
            await on_progress(text)

    async def _do_screenshot(page):
        cal_page = await _navigate_to_calendar(page, on_progress)
        if not cal_page:
            result["error"] = "Не удалось открыть календарь"
            return result

        await _progress("📸 Делаю скриншот...")
        logger.info("[screenshot] Looking for #menu_container...")
        calendar_el = cal_page.locator("#menu_container")
        if await calendar_el.count() == 0:
            logger.warning("[screenshot] #menu_container not found, trying #body_container")
            calendar_el = cal_page.locator("#body_container")
            if await calendar_el.count() == 0:
                logger.error("[screenshot] Neither #menu_container nor #body_container found")
                logger.info("[screenshot] Falling back to full page screenshot")
                await page.screenshot(path=SCREENSHOT_PATH, full_page=True)
                result["path"] = SCREENSHOT_PATH
                return result

        await calendar_el.screenshot(path=SCREENSHOT_PATH)
        result["path"] = SCREENSHOT_PATH
        logger.info("[screenshot] Saved to %s", SCREENSHOT_PATH)
        return result

    try:
        return await _run_with_browser(_do_screenshot)
    except PlaywrightTimeout as e:
        result["error"] = f"Таймаут: {type(e).__name__}: {e}"
        logger.error("[screenshot] TIMEOUT: %s", e)
    except Exception as e:
        result["error"] = f"Ошибка: {type(e).__name__}: {e}"
        logger.error("[screenshot] EXCEPTION: %s", e, exc_info=True)
    return result


def cleanup_screenshot():
    """Remove the screenshot file."""
    try:
        os.remove(SCREENSHOT_PATH)
    except OSError:
        pass

