import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent


def _restart_inside_venv() -> None:
    """Let `python main.py` work even when the shell did not activate .venv."""
    venv_python = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    current_python = Path(sys.executable).resolve()
    if os.environ.get("HOTWHEELS_SKIP_VENV_RESTART") == "1":
        return
    if venv_python.exists() and current_python != venv_python.resolve():
        os.environ["HOTWHEELS_SKIP_VENV_RESTART"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_restart_inside_venv()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from collector import classify_products, priority_products
from curator import build_curated_report
from notifier import (
    send_curated_priority_alert,
    send_curated_stock_digest,
    send_heartbeat,
    send_startup_message,
)
from scraper import scrape_location

STATE_PATH = BASE_DIR / "state.json"
LOCK_PATH = BASE_DIR / "run.lock"
TIMEZONE = ZoneInfo("Asia/Kolkata")
LOCK_STALE_SECONDS = 3 * 60 * 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("hotwheels.main")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def load_config() -> dict:
    _load_env_file()
    config_path = BASE_DIR / "config.json"
    with open(config_path, encoding="utf-8-sig") as f:
        config = json.load(f)

    config["anthropic_api_key"] = os.getenv(
        "ANTHROPIC_API_KEY", config.get("anthropic_api_key", "")
    )
    telegram = config.setdefault("telegram", {})
    telegram["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", telegram.get("bot_token", ""))
    telegram["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", telegram.get("chat_id", ""))
    return config


def validate_config(config: dict) -> list[str]:
    warnings = []
    if not config.get("locations"):
        warnings.append("No locations configured.")

    telegram = config.get("telegram", {})
    if _is_placeholder(telegram.get("bot_token"), "YOUR_BOT_TOKEN_HERE"):
        warnings.append("Telegram bot_token is not set; alerts will be logged but not sent.")
    if _is_placeholder(telegram.get("chat_id"), "YOUR_CHAT_ID_HERE"):
        warnings.append("Telegram chat_id is not set; alerts will be logged but not sent.")

    collector = config.get("collector", {})
    if not collector.get("priority_keywords"):
        warnings.append("Collector priority_keywords not set; default collector rules will be used.")

    return warnings


def _load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _is_placeholder(value: str | None, placeholder: str) -> bool:
    return not value or value.strip() == placeholder


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"alerts": {}, "last_stock_digest_at": 0}
    try:
        with open(STATE_PATH, encoding="utf-8-sig") as file:
            state = json.load(file)
        state.setdefault("alerts", {})
        state.setdefault("last_stock_digest_at", 0)
        return state
    except Exception as exc:
        logger.warning("Could not read state.json, starting fresh: %s", exc)
        return {"alerts": {}, "last_stock_digest_at": 0}


def _save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)


def _acquire_run_lock() -> bool:
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - LOCK_PATH.stat().st_mtime
        except OSError:
            age = 0
        if age > LOCK_STALE_SECONDS:
            logger.warning("Removing stale run lock older than %s seconds.", LOCK_STALE_SECONDS)
            try:
                LOCK_PATH.unlink()
            except OSError as exc:
                logger.warning("Could not remove stale run lock: %s", exc)
                return False
            return _acquire_run_lock()
        logger.warning("Another collector run appears to be active; skipping this launch.")
        return False

    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(f"pid={os.getpid()}\nstarted_at={datetime.now(TIMEZONE).isoformat()}\n")
    return True


def _release_run_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not remove run lock: %s", exc)


def _alert_key(product: dict) -> str:
    return f"{product.get('location', '')}:{product.get('name', '')}".lower()


def _is_already_alerted(product: dict, state: dict, cooldown_minutes: int) -> bool:
    last_alert = float(state.get("alerts", {}).get(_alert_key(product), 0))
    return (time.time() - last_alert) < (cooldown_minutes * 60)


def _mark_alerted(products: list[dict], state: dict) -> None:
    now = time.time()
    alerts = state.setdefault("alerts", {})
    for product in products:
        alerts[_alert_key(product)] = now


def _stock_digest_due(config: dict, state: dict) -> bool:
    minutes = int(config.get("stock_digest_interval_minutes", 240))
    last_digest = float(state.get("last_stock_digest_at", 0))
    return (time.time() - last_digest) >= minutes * 60


def _mark_stock_digest_sent(state: dict) -> None:
    state["last_stock_digest_at"] = time.time()


def _products_in_report(report: dict, section: str = "priority_groups") -> list[dict]:
    products = []
    for group in report.get(section, []):
        products.extend(group.get("products", []))
    return products


def _within_active_hours(config: dict, now: datetime | None = None) -> bool:
    schedule = config.get("schedule", {})
    active_hours = schedule.get("active_hours", {})
    if not active_hours.get("enabled", False):
        return True

    now = now or datetime.now(TIMEZONE)
    current_minutes = now.hour * 60 + now.minute
    start = _parse_hhmm(active_hours.get("start", "06:00"))
    end = _parse_hhmm(active_hours.get("end", "00:00"))
    if end == 0 and start != 0:
        end = 24 * 60

    if start < end:
        return start <= current_minutes < end
    if start > end:
        return current_minutes >= start or current_minutes < end
    return True


def _parse_hhmm(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


async def check_all_locations(
    force_stock_digest: bool = False,
    ignore_active_hours: bool = False,
) -> dict:
    config = load_config()
    for warning in validate_config(config):
        logger.warning(warning)

    if not ignore_active_hours and not _within_active_hours(config):
        logger.info("Outside active monitoring hours; skipping this cycle.")
        return {"checked": False, "priority_count": 0, "product_count": 0}

    state = _load_state()
    locations = config.get("locations", [])
    telegram_cfg = config.get("telegram", {})
    priority_cooldown = int(config.get("priority_alert_cooldown_minutes", 720))
    delay = float(config.get("scraper", {}).get("request_delay_seconds", 4))

    started_at = datetime.now(TIMEZONE).strftime("%H:%M:%S")
    logger.info("Collector cycle started at %s", started_at)

    all_products: list[dict] = []

    for index, location in enumerate(locations):
        logger.info("Checking %s...", location["name"])
        try:
            raw_products = await scrape_location(location, config)
            if not config.get("scraper", {}).get("include_unavailable", False):
                raw_products = [
                    product for product in raw_products if product.get("available", True)
                ]
            classified = classify_products(raw_products, config)
            all_products.extend(classified)
            picks = priority_products(classified, config)

            logger.info(
                "[%s] %s products, %s collector-priority picks",
                location["name"],
                len(classified),
                len(picks),
            )
        except Exception as exc:
            logger.error("[%s] Unexpected error: %s", location["name"], exc, exc_info=True)

        if index < len(locations) - 1:
            await asyncio.sleep(delay)

    priority = priority_products(all_products, config)
    new_priority = [
        product
        for product in priority
        if not _is_already_alerted(product, state, priority_cooldown)
    ]

    if new_priority:
        priority_report = build_curated_report(new_priority, config)
        await send_curated_priority_alert(priority_report, telegram_cfg)
        alerted_products = _products_in_report(priority_report)
        _mark_alerted(alerted_products, state)
        state["quiet_runs"] = 0
        logger.info(
            "Priority alert sent for %s displayed products (%s eligible before curation)",
            len(alerted_products),
            len(new_priority),
        )
    else:
        logger.info("No new collector-priority products this cycle.")

    digest_due = force_stock_digest or _stock_digest_due(config, state)
    stock_digest_sent = False
    if digest_due and all_products:
        digest_report = build_curated_report(all_products, config)
        await send_curated_stock_digest(digest_report, telegram_cfg)
        _mark_stock_digest_sent(state)
        stock_digest_sent = True
        logger.info("Stock digest sent for %s products", len(all_products))

    if not new_priority and not stock_digest_sent:
        heartbeat_every = int(config.get("heartbeat_every_runs", 0))
        if heartbeat_every > 0:
            state["quiet_runs"] = int(state.get("quiet_runs", 0)) + 1
            if state["quiet_runs"] >= heartbeat_every:
                await send_heartbeat(telegram_cfg, state["quiet_runs"], locations)
                state["quiet_runs"] = 0

    _save_state(state)
    logger.info("Collector cycle finished\n")
    return {
        "checked": True,
        "priority_count": len(priority),
        "new_priority_count": len(new_priority),
        "product_count": len(all_products),
        "stock_digest_sent": stock_digest_sent,
    }


async def run_scheduler(args: argparse.Namespace) -> None:
    config = load_config()
    for warning in validate_config(config):
        logger.warning(warning)

    telegram_cfg = config.get("telegram", {})
    schedule_cfg = config.get("schedule", {})

    logger.info("Hot Wheels Blinkit Agent starting up...")
    if not args.no_startup_message:
        await send_startup_message(telegram_cfg, config.get("locations", []))

    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    if schedule_cfg.get("use_custom_times"):
        for time_str in schedule_cfg.get("custom_times", []):
            hour, minute = map(int, time_str.split(":"))
            scheduler.add_job(
                check_all_locations,
                CronTrigger(hour=hour, minute=minute, timezone="Asia/Kolkata"),
                id=f"check_{time_str}",
                name=f"Check at {time_str}",
                misfire_grace_time=300,
                coalesce=True,
                max_instances=1,
            )
        logger.info("Scheduled at: %s", schedule_cfg.get("custom_times", []))
    else:
        interval_minutes = int(
            schedule_cfg.get(
                "interval_minutes",
                float(schedule_cfg.get("interval_hours", 1)) * 60,
            )
        )
        scheduler.add_job(
            check_all_locations,
            IntervalTrigger(minutes=interval_minutes),
            id="check_interval",
            name=f"Check every {interval_minutes}m",
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )
        logger.info("Scheduled every %s minute(s)", interval_minutes)

    active_hours = schedule_cfg.get("active_hours", {})
    if active_hours.get("enabled"):
        logger.info(
            "Active monitoring window: %s-%s Asia/Kolkata",
            active_hours.get("start"),
            active_hours.get("end"),
        )

    scheduler.start()

    if schedule_cfg.get("run_on_start", True):
        await check_all_locations(force_stock_digest=args.force_digest)

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Agent shutting down...")
        scheduler.shutdown()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hot Wheels Blinkit collector agent")
    parser.add_argument("--once", action="store_true", help="Run one check cycle and exit.")
    parser.add_argument(
        "--force-digest",
        action="store_true",
        help="Send stock digest even if the 4-hour digest window is not due.",
    )
    parser.add_argument(
        "--ignore-active-hours",
        action="store_true",
        help="Run even outside the configured active monitoring window.",
    )
    parser.add_argument(
        "--no-startup-message",
        action="store_true",
        help="Do not send Telegram startup confirmation.",
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    if not _acquire_run_lock():
        return

    try:
        if args.once:
            await check_all_locations(
                force_stock_digest=args.force_digest,
                ignore_active_hours=args.ignore_active_hours,
            )
        else:
            await run_scheduler(args)
    finally:
        _release_run_lock()


if __name__ == "__main__":
    asyncio.run(async_main())
