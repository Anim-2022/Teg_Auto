import asyncio
import logging
import os
import traceback
import time
from playwright.async_api import async_playwright, Page, Frame, TimeoutError as PlaywrightTimeout

from config import TARGET_URL, HEADLESS, TIMEOUT

logger = logging.getLogger(__name__)

# Type for progress callback: async def(text: str) -> None
ProgressCallback = None  # just for docs


async def _navigate_to_calendar(page: Page, on_progress=None) -> Frame | None:
    """Navigate through the form to the calendar page. Returns the iframe Frame or None."""
    step = "cookie_consent"

    async def _progress(text):
        if on_progress:
            await on_progress(text)

    try:
        # Step 1: Cookie consent
        await _progress("🍪 Закрываю cookie-баннер...")
        try:
            cookie_btn = page.locator("text=Das ist ok")
            if await cookie_btn.is_visible(timeout=3000):
                await cookie_btn.click()
                await page.wait_for_timeout(1000)
                logger.info("[nav] Cookie consent accepted")
            else:
                logger.info("[nav] No cookie banner found")
        except Exception as e:
            logger.info("[nav] Cookie consent skipped: %s", e)

        # Step 2: Find tempus-termine iframe
        step = "find_iframe"
        await _progress("🔍 Ищу форму записи (iframe)...")
        frame = None
        all_frames = page.frames
        logger.info("[nav] Total frames on page: %d", len(all_frames))
        for f in all_frames:
            logger.debug("[nav]   frame url: %s", f.url)
            if "tempus-termine.com" in (f.url or ""):
                frame = f
                break
        if not frame:
            logger.error("[nav] FAIL: tempus-termine iframe NOT found. Frame URLs: %s",
                         [f.url for f in all_frames])
            return None
        logger.info("[nav] Found iframe: %s", frame.url)

        # Step 3: Select service
        step = "select_service"
        await _progress("📋 Выбираю: Ersterteilung/Erweiterung...")
        select_el = frame.locator("#ErtErw-788-mittermin")
        if await select_el.count() == 0:
            logger.error("[nav] FAIL: #ErtErw-788-mittermin not found in iframe")
            return None
        await select_el.select_option("1")
        await page.wait_for_timeout(500)
        logger.info("[nav] Service selected (ErtErw=1)")

        # Step 4: Check privacy checkbox
        step = "check_privacy"
        await _progress("✅ Принимаю Datenschutz...")
        checkbox = frame.locator("#chkDatenschutz")
        if await checkbox.count() == 0:
            logger.error("[nav] FAIL: #chkDatenschutz not found in iframe")
            return None
        await checkbox.check()
        await page.wait_for_timeout(500)
        logger.info("[nav] Privacy checkbox checked")

        # Step 5: Submit form
        step = "submit_form"
        await _progress("🚀 Жму «Weiter zur Terminauswahl»...")
        submit_btn = frame.locator("input[type='submit'][value='Weiter zur Terminauswahl »']")
        if await submit_btn.count() == 0:
            logger.error("[nav] FAIL: Submit button not found in iframe")
            return None
        await submit_btn.click()
        logger.info("[nav] Form submitted, waiting 5s for calendar...")
        await _progress("⏳ Жду загрузки календаря...")
        await page.wait_for_timeout(5000)

        # Step 6: Re-find iframe after navigation
        step = "refind_iframe"
        for f in page.frames:
            if "tempus-termine.com" in (f.url or ""):
                logger.info("[nav] SUCCESS: Calendar iframe found after submit: %s", f.url)
                return f

        logger.error("[nav] FAIL: iframe lost after form submit. Frames: %s",
                     [f.url for f in page.frames])
        return None

    except PlaywrightTimeout as e:
        logger.error("[nav] TIMEOUT at step '%s': %s", step, e)
        raise
    except Exception as e:
        logger.error("[nav] ERROR at step '%s': %s\n%s", step, e, traceback.format_exc())
        raise


async def _parse_dates(frame: Frame) -> list[dict]:
    """Parse available dates from calendar tables in the frame."""
    available = []
    cal_tables = frame.locator("table.cal")
    table_count = await cal_tables.count()
    logger.info("[parse] Found %d calendar tables", table_count)

    if table_count == 0:
        # Debug: log what's in the frame
        body_html = await frame.locator("body").inner_text()
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
        browser = await pw.chromium.launch(headless=HEADLESS)
        logger.info("[browser] Chromium launched in %.1fs", time.monotonic() - t0)
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
        logger.info("[check] Opening %s", TARGET_URL)
        await _progress("🌐 Открываю сайт Gelsenkirchen...")
        await page.goto(TARGET_URL, wait_until="domcontentloaded")
        # Wait for iframe to appear
        await page.wait_for_timeout(3000)
        logger.info("[check] Page loaded, navigating to calendar...")

        frame = await _navigate_to_calendar(page, on_progress)
        if not frame:
            result["error"] = "Не удалось открыть календарь (iframe или форма не найдены)"
            return result

        await _progress("📅 Сканирую календарь...")
        result["available_dates"] = await _parse_dates(frame)
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
        logger.info("[screenshot] Opening %s", TARGET_URL)
        await _progress("🌐 Открываю сайт Gelsenkirchen...")
        await page.goto(TARGET_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        logger.info("[screenshot] Page loaded, navigating to calendar...")

        frame = await _navigate_to_calendar(page, on_progress)
        if not frame:
            result["error"] = "Не удалось открыть календарь (iframe или форма не найдены)"
            return result

        await _progress("📸 Делаю скриншот...")
        logger.info("[screenshot] Looking for #menu_container...")
        calendar_el = frame.locator("#menu_container")
        if await calendar_el.count() == 0:
            logger.warning("[screenshot] #menu_container not found, trying #body_container")
            calendar_el = frame.locator("#body_container")
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

