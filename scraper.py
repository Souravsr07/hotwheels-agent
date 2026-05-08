import asyncio
import json
import logging
import random
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent

PRODUCT_SELECTORS = [
    "[data-test-id='plp-product']",
    ".product__info",
    "div[class*='Product__']",
    "div[class*='plp-product']",
    "a[href*='/prn/']",
]

NAME_SELECTORS = [
    "[data-test-id='product-name']",
    ".product__name",
    "div[class*='ProductName']",
    "h6",
    "div[class*='name']",
]

PRICE_SELECTORS = [
    "[data-test-id='product-price']",
    ".product__price",
    "div[class*='Price']",
    "span[class*='price']",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


async def scrape_location(location: dict, config: dict) -> list[dict]:
    """
    Scrape Blinkit for Hot Wheels at a given lat/lng.

    Returns product dicts with name, price, availability, location, source, and url.
    """
    scraper_cfg = config.get("scraper", {})
    timeout = int(scraper_cfg.get("page_timeout_ms", 35000))
    max_retries = int(scraper_cfg.get("max_retries", 2))

    for attempt in range(1, max_retries + 1):
        try:
            products = await _run_scraper(location, timeout, scraper_cfg)
            if products is not None:
                products = _dedupe_products(products)
                logger.info("[%s] Found %s Hot Wheels products", location["name"], len(products))
                return products
        except Exception as exc:
            logger.warning("[%s] Attempt %s failed: %s", location["name"], attempt, exc)
            await asyncio.sleep(5)

    logger.error("[%s] All attempts failed, returning empty", location["name"])
    return []


async def _run_scraper(location: dict, timeout: int, scraper_cfg: dict) -> Optional[list[dict]]:
    intercepted_products: list[dict] = []
    api_urls_seen: set[str] = set()
    browser = None

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                headless=bool(scraper_cfg.get("headless", True)),
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                ],
            )

            context = await browser.new_context(
                geolocation={"latitude": location["lat"], "longitude": location["lng"]},
                permissions=["geolocation"],
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "lat": str(location["lat"]),
                    "lon": str(location["lng"]),
                },
            )
            await _seed_location_cookies(context, location)
            await context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                """
            )

            page = await context.new_page()

            async def on_response(response):
                url = response.url
                if not _is_candidate_api_url(url, scraper_cfg):
                    return

                api_urls_seen.add(url)
                if response.status != 200:
                    return

                try:
                    content_type = response.headers.get("content-type", "")
                    if "json" not in content_type:
                        return
                    data = await response.json()
                    products = _parse_api_response(data, location, scraper_cfg)
                    if products:
                        intercepted_products.extend(products)
                except Exception as exc:
                    logger.debug("Could not parse API response %s: %s", url, exc)

            page.on("response", on_response)

            search_url = scraper_cfg.get("search_url", "https://blinkit.com/s/?q=hot+wheels")
            logger.info("[%s] Navigating to %s", location["name"], search_url)

            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout)
            except PlaywrightTimeout:
                logger.warning("[%s] Page load timeout; trying to parse anyway", location["name"])

            await asyncio.sleep(random.uniform(4, 6))
            await _dismiss_popups(page)
            await _trigger_more_results(page, scraper_cfg)
            await asyncio.sleep(float(scraper_cfg.get("post_load_wait_seconds", 2)))

            if scraper_cfg.get("debug_api_urls", True):
                _log_api_urls(location, api_urls_seen)

            if intercepted_products:
                return _dedupe_products(intercepted_products)

            logger.info("[%s] Falling back to DOM scraping", location["name"])
            dom_products = await _scrape_dom(page, location)

            if not dom_products and scraper_cfg.get("save_debug_artifacts", True):
                await _save_debug_artifacts(page, location)

            return dom_products
        finally:
            if browser:
                await browser.close()


async def _dismiss_popups(page) -> None:
    popup_selectors = [
        "button[aria-label='Close']",
        "button:has-text('Allow')",
        "button:has-text('Skip')",
        "button:has-text('Later')",
        "button:has-text('Deny')",
        "[data-test-id='modal-close']",
    ]
    for selector in popup_selectors:
        try:
            button = page.locator(selector).first
            if await button.is_visible(timeout=1500):
                await button.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass


async def _trigger_more_results(page, scraper_cfg: dict) -> None:
    scrolls = int(scraper_cfg.get("result_scrolls", 3))
    pause_ms = int(scraper_cfg.get("scroll_pause_ms", 900))
    for _ in range(max(0, scrolls)):
        try:
            await page.mouse.wheel(0, 900)
            await page.wait_for_timeout(pause_ms)
        except Exception:
            return


async def _seed_location_cookies(context, location: dict) -> None:
    cookies = [
        {
            "name": "gr_1_lat",
            "value": str(location["lat"]),
            "domain": "blinkit.com",
            "path": "/",
        },
        {
            "name": "gr_1_lon",
            "value": str(location["lng"]),
            "domain": "blinkit.com",
            "path": "/",
        },
        {
            "name": "gr_1_landmark",
            "value": location.get("landmark", "undefined"),
            "domain": "blinkit.com",
            "path": "/",
        },
    ]
    if location.get("locality"):
        cookies.append(
            {
                "name": "gr_1_locality",
                "value": str(location["locality"]),
                "domain": "blinkit.com",
                "path": "/",
            }
        )
    await context.add_cookies(cookies)


async def _scrape_dom(page, location: dict) -> list[dict]:
    products = []
    container_selector = None

    for selector in PRODUCT_SELECTORS:
        try:
            count = await page.locator(selector).count()
            if count > 0:
                container_selector = selector
                logger.info(
                    "[%s] Found %s product elements with selector: %s",
                    location["name"],
                    count,
                    selector,
                )
                break
        except Exception:
            continue

    if not container_selector:
        logger.warning("[%s] No product containers found via DOM", location["name"])
        return await _scrape_text_fallback(page, location)

    product_elements = page.locator(container_selector)
    count = await product_elements.count()

    for index in range(count):
        element = product_elements.nth(index)
        try:
            name = await _extract_text(element, NAME_SELECTORS)
            if not name or "hot wheels" not in name.lower():
                continue

            price = await _extract_text(element, PRICE_SELECTORS)
            available = await _check_availability(element)
            url = await _extract_url(element)

            products.append(
                {
                    "name": _compact_text(name),
                    "price": _clean_price(price),
                    "available": available,
                    "location": location["name"],
                    "source": "dom",
                    "url": url,
                }
            )
        except Exception as exc:
            logger.debug("Element parse error: %s", exc)

    return _dedupe_products(products)


async def _scrape_text_fallback(page, location: dict) -> list[dict]:
    products = []
    seen = set()
    try:
        elements = await page.query_selector_all("*:has-text('Hot Wheels')")
        for element in elements[:50]:
            text = await element.inner_text()
            lines = [_compact_text(line) for line in text.split("\n") if line.strip()]
            for line in lines:
                key = line.lower()
                if "hot wheels" in key and key not in seen and len(line) < 200:
                    seen.add(key)
                    products.append(
                        {
                            "name": line,
                            "price": "N/A",
                            "available": True,
                            "location": location["name"],
                            "source": "text_fallback",
                            "url": "",
                        }
                    )
    except Exception as exc:
        logger.error("Text fallback failed: %s", exc)
    return _dedupe_products(products)


async def _extract_text(element, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            child = element.locator(selector).first
            if await child.count() > 0:
                text = await child.inner_text(timeout=1000)
                if text and text.strip():
                    return text.strip()
        except Exception:
            continue

    try:
        return await element.inner_text(timeout=1000)
    except Exception:
        return ""


async def _extract_url(element) -> str:
    try:
        href = await element.get_attribute("href")
        if href:
            return href if href.startswith("http") else f"https://blinkit.com{href}"
    except Exception:
        pass

    try:
        link = element.locator("a[href]").first
        if await link.count() > 0:
            href = await link.get_attribute("href")
            if href:
                return href if href.startswith("http") else f"https://blinkit.com{href}"
    except Exception:
        pass

    return ""


async def _check_availability(element) -> bool:
    try:
        text = (await element.inner_text(timeout=1000)).lower()
        if any(term in text for term in ["out of stock", "sold out", "unavailable"]):
            return False

        button_selectors = [
            "button:has-text('Add')",
            "button:has-text('+')",
            "[data-test-id='add-to-cart']",
            "button[class*='add']",
        ]
        for selector in button_selectors:
            button = element.locator(selector).first
            if await button.count() > 0:
                disabled = await button.get_attribute("disabled")
                return disabled is None
        return True
    except Exception:
        return True


def _parse_api_response(data: dict, location: dict, scraper_cfg: dict | None = None) -> list[dict]:
    products = []
    include_unavailable = bool((scraper_cfg or {}).get("include_unavailable", False))

    def walk(obj):
        if isinstance(obj, dict):
            name = _first_present(obj, ["name", "product_name", "display_name", "title"])
            price = _first_present(
                obj,
                ["price", "selling_price", "discounted_price", "mrp", "unit_price"],
            )
            available = _product_available(obj)
            url = _first_present(obj, ["url", "product_url", "deeplink"], default="")

            if isinstance(name, str) and "hot wheels" in name.lower():
                if available or include_unavailable:
                    products.append(
                        {
                            "name": _compact_text(name),
                            "price": _clean_price(str(price) if price else ""),
                            "available": available,
                            "location": location["name"],
                            "source": "api",
                            "url": url if isinstance(url, str) else "",
                        }
                    )

            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return _dedupe_products(products)


def _first_present(obj: dict, keys: list[str], default=None):
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return default


def _is_candidate_api_url(url: str, scraper_cfg: dict) -> bool:
    lowered = url.lower()
    if not lowered.startswith("https://blinkit.com/"):
        return False
    if any(asset in lowered for asset in [".js", ".css", ".png", ".jpg", ".webp", ".svg"]):
        return False

    paths = scraper_cfg.get(
        "api_url_paths",
        ["/v1/layout/search", "/v1/layout/empty_search", "/v2/search/deeplink"],
    )
    if any(path.lower() in lowered for path in paths):
        return True

    keywords = scraper_cfg.get("api_url_keywords", [])
    return any(keyword.lower() in lowered for keyword in keywords)


def _coerce_available(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        normalized_words = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
        if normalized in {"false", "0", "no", "n"}:
            return False
        if normalized_words in {"false", "0", "no", "n", "out of stock", "sold out", "unavailable"}:
            return False
        if any(
            term in normalized_words
            for term in [
                "out of stock",
                "sold out",
                "unavailable",
                "notify me",
                "currently unavailable",
                "coming soon",
            ]
        ):
            return False
        if any(
            term in normalized_words
            for term in ["in stock", "available", "add", "add to cart"]
        ):
            return True
        return True
    if isinstance(value, dict):
        return _product_available(value)
    if isinstance(value, list):
        values = [_coerce_available(item) for item in value]
        return any(values) if values else True
    return bool(value)


def _product_available(product_obj: dict) -> bool:
    signals = list(_availability_signals(product_obj))
    if not signals:
        return True

    saw_positive = False
    for value in signals:
        available = _coerce_available(value)
        if available is False:
            return False
        if available is True:
            saw_positive = True
    return saw_positive or True


def _availability_signals(obj, depth: int = 0):
    if depth > 4:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_text = str(key).lower()
            if _is_availability_key(key_text):
                yield value
            if isinstance(value, (dict, list)):
                yield from _availability_signals(value, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                yield from _availability_signals(item, depth + 1)


def _is_availability_key(key: str) -> bool:
    return any(
        marker in key
        for marker in [
            "available",
            "availability",
            "in_stock",
            "stock",
            "inventory",
            "quantity",
            "qty",
            "sold",
            "cta",
            "button",
            "cart",
            "status",
            "state",
        ]
    )


def _log_api_urls(location: dict, urls: set[str]) -> None:
    if not urls:
        logger.info("[%s] No candidate API URLs observed", location["name"])
        return

    debug_path = BASE_DIR / "api_hits.log"
    with open(debug_path, "a", encoding="utf-8") as file:
        for url in sorted(urls):
            file.write(json.dumps({"location": location["name"], "url": url}) + "\n")
    logger.info("[%s] Logged %s candidate API URLs to %s", location["name"], len(urls), debug_path)


async def _save_debug_artifacts(page, location: dict) -> None:
    safe_name = re.sub(r"[^a-z0-9]+", "_", location["name"].lower()).strip("_")
    debug_dir = BASE_DIR / "debug"
    debug_dir.mkdir(exist_ok=True)

    try:
        await page.screenshot(path=debug_dir / f"{safe_name}.png", full_page=True)
        html = await page.content()
        (debug_dir / f"{safe_name}.html").write_text(html, encoding="utf-8")
        logger.info("[%s] Saved debug screenshot/html to %s", location["name"], debug_dir)
    except Exception as exc:
        logger.debug("[%s] Could not save debug artifacts: %s", location["name"], exc)


def _dedupe_products(products: list[dict]) -> list[dict]:
    deduped = {}
    for product in products:
        key = (
            product.get("location", "").lower(),
            product.get("name", "").lower(),
            str(product.get("price", "")).lower(),
        )
        deduped[key] = product
    return list(deduped.values())


def _compact_text(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def _clean_price(raw: str) -> str:
    if not raw:
        return "N/A"
    match = re.search(r"[\d,]+(?:\.\d+)?", raw)
    if match:
        return "Rs. " + match.group().replace(",", "")
    return _compact_text(raw)
