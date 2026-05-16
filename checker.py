import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from config import TARGET_URL, HEADLESS, TIMEOUT

logger = logging.getLogger(__name__)


async def check_available_dates() -> dict:
    """
    Opens the Führerscheinstelle appointment page, selects
    'Ersterteilung oder Erweiterung einer Fahrerlaubnis' = 1,
    accepts privacy, submits, and parses the calendar.

    Returns dict:
        - "available_dates": list of {"day": str, "month": str, "link": str}
        - "error": str or None
    """
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

            # Cookie consent
            try:
                cookie_btn = page.locator("text=Das ist ok")
                if await cookie_btn.is_visible(timeout=3000):
                    await cookie_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # Find the tempus-termine iframe
            frame = None
            for f in page.frames:
                if "tempus-termine.com" in (f.url or ""):
                    frame = f
                    break

            if not frame:
                result["error"] = "Iframe tempus-termine не найден"
                return result

            # Select "Ersterteilung oder Erweiterung" = 1
            await frame.locator("#ErtErw-788-mittermin").select_option("1")
            await page.wait_for_timeout(500)

            # Check privacy checkbox
            await frame.locator("#chkDatenschutz").check()
            await page.wait_for_timeout(500)

            # Submit form
            await frame.locator("input[type='submit'][value='Weiter zur Terminauswahl »']").click()
            logger.info("Form submitted, waiting for calendar...")

            # Wait for calendar to load
            await page.wait_for_timeout(5000)

            # Re-find iframe after navigation
            frame = None
            for f in page.frames:
                if "tempus-termine.com" in (f.url or ""):
                    frame = f
                    break

            if not frame:
                result["error"] = "Iframe потерян после отправки формы"
                return result

            # Parse calendar tables
            # Available dates = <a> links inside <td> cells
            # Unavailable = plain text (no link)
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
                        # Build full URL for direct booking
                        full_link = ""
                        if href and not href.startswith("http"):
                            full_link = f"https://tempus-termine.com/termine/{href}"
                        elif href.startswith("http"):
                            full_link = href
                        available.append({
                            "day": text,
                            "month": month_label,
                            "link": full_link,
                        })

            result["available_dates"] = available
            if available:
                logger.info("Found %d available slots!", len(available))
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = asyncio.run(check_available_dates())
    print(r)

