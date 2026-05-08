import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _restart_inside_venv() -> None:
    venv_python = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    current_python = Path(sys.executable).resolve()
    if os.environ.get("HOTWHEELS_SKIP_VENV_RESTART") == "1":
        return
    if venv_python.exists() and current_python != venv_python.resolve():
        os.environ["HOTWHEELS_SKIP_VENV_RESTART"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_restart_inside_venv()

import httpx
from playwright.async_api import async_playwright

import main


async def _check_playwright() -> str:
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            await browser.close()
        return "OK"
    except Exception as exc:
        return f"FAILED: {exc}"


async def run() -> None:
    config = main.load_config()
    warnings = main.validate_config(config)

    print(f"Python: {sys.executable}")
    print(f"Config: {BASE_DIR / 'config.json'}")
    print("Config warnings:", "none" if not warnings else "; ".join(warnings))

    telegram = config.get("telegram", {})
    token = telegram.get("bot_token", "")
    chat_id = telegram.get("chat_id", "")
    if token and token != "YOUR_BOT_TOKEN_HERE" and chat_id and chat_id != "YOUR_CHAT_ID_HERE":
        try:
            url = f"https://api.telegram.org/bot{token}/getMe"
            response = httpx.get(url, timeout=15)
            response.raise_for_status()
            bot = response.json().get("result", {})
            print(f"Telegram: OK ({bot.get('username', 'unknown bot')})")
        except Exception as exc:
            print(f"Telegram: FAILED ({exc})")
    else:
        print("Telegram: not configured")

    print(f"Playwright Chromium: {await _check_playwright()}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
