"""Direct test of checker functions."""
import asyncio
import logging
import sys
import os

# Setup logging to see everything
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

from checker import check_available_dates, screenshot_calendar, cleanup_screenshot


async def test_check():
    print("=" * 60)
    print("TEST 1: check_available_dates()")
    print("=" * 60)
    result = await check_available_dates()
    print(f"  available_dates: {result['available_dates']}")
    print(f"  error: {result['error']}")
    print(f"  RESULT: {'PASS' if result['error'] is None else 'FAIL'}")
    return result['error'] is None


async def test_screenshot():
    print("\n" + "=" * 60)
    print("TEST 2: screenshot_calendar()")
    print("=" * 60)
    result = await screenshot_calendar()
    print(f"  path: {result['path']}")
    print(f"  error: {result['error']}")
    if result['path']:
        size = os.path.getsize(result['path'])
        print(f"  file size: {size} bytes")
        cleanup_screenshot()
        print(f"  cleanup: OK")
    print(f"  RESULT: {'PASS' if result['error'] is None and result['path'] else 'FAIL'}")
    return result['error'] is None and result['path'] is not None


async def main():
    r1 = await test_check()
    r2 = await test_screenshot()
    print("\n" + "=" * 60)
    print(f"check_available_dates: {'PASS' if r1 else 'FAIL'}")
    print(f"screenshot_calendar:   {'PASS' if r2 else 'FAIL'}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
