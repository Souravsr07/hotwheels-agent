import asyncio
import json
import logging
import random
import re
import unicodedata
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent


class BlinkitAccessBlocked(Exception):
    """Raised when Blinkit/Cloudflare blocks the current runner before search loads."""

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

IMAGE_SELECTORS = [
    "img[data-test-id='product-image']",
    "img[class*='Product']",
    "img",
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
                geolocation={
                    "latitude": _location_lat(location),
                    "longitude": _location_lng(location),
                },
                permissions=["geolocation"],
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "lat": str(_location_lat(location)),
                    "lon": str(_location_lng(location)),
                },
            )
            await _seed_location_cookies(context, location)
            await context.add_init_script(
                f"""
                Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
                Object.defineProperty(navigator, 'plugins', {{ get: () => [1, 2, 3] }});
                (() => {{
                    const locationState = {json.dumps(_location_state(location))};
                    try {{
                        window.localStorage.setItem('location', JSON.stringify(locationState));
                    }} catch (error) {{}}
                }})();
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
            block_reason = await _blocked_page_reason(page)
            if block_reason:
                if scraper_cfg.get("save_debug_artifacts", True):
                    await _save_debug_artifacts(page, location)
                raise BlinkitAccessBlocked(block_reason)

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


async def _blocked_page_reason(page) -> str:
    try:
        text = (await page.locator("body").inner_text(timeout=2000)).lower()
    except Exception:
        return ""

    blocked_markers = [
        "access denied",
        "sorry, you have been blocked",
        "cloudflare ray id",
        "the page you are trying to access has blocked you",
    ]
    if not any(marker in text for marker in blocked_markers):
        return ""

    try:
        body_text = await page.locator("body").inner_text(timeout=2000)
    except Exception:
        return "Blinkit access denied"

    ray_match = re.search(r"Ray ID\s*-\s*([A-Za-z0-9]+)", body_text)
    ip_match = re.search(r"Your IP\s*-\s*([0-9A-Fa-f:.]+)", body_text)
    pieces = ["Blinkit access denied"]
    if ray_match:
        pieces.append(f"Ray ID {ray_match.group(1)}")
    if ip_match:
        pieces.append(f"IP {ip_match.group(1)}")
    return " | ".join(pieces)


async def _seed_location_cookies(context, location: dict) -> None:
    lat = str(_location_lat(location))
    lng = str(_location_lng(location))
    cookies = [
        {
            "name": "gr_1_lat",
            "value": lat,
            "domain": "blinkit.com",
            "path": "/",
        },
        {
            "name": "gr_1_lon",
            "value": lng,
            "domain": "blinkit.com",
            "path": "/",
        },
        {
            "name": "gr_1_landmark",
            "value": quote(str(location.get("landmark", "undefined")), safe=""),
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


def _location_lat(location: dict) -> float:
    return float(location.get("resolved_lat", location["lat"]))


def _location_lng(location: dict) -> float:
    return float(location.get("resolved_lng", location["lng"]))


def _location_state(location: dict) -> dict:
    return {
        "coords": {
            "isDefault": False,
            "lat": _location_lat(location),
            "lon": _location_lng(location),
            "locality": location.get("city", "Pune"),
            "id": int(location.get("locality", 787)),
            "isTopCity": False,
            "cityName": location.get("city", "Pune"),
            "landmark": location.get("landmark", ""),
            "addressId": None,
        }
    }


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
            image_url = await _extract_image_url(element)

            products.append(
                {
                    "name": _compact_text(name),
                    "price": _clean_price(price),
                    "available": available,
                    "location": location["name"],
                    "source": "dom",
                    "url": url,
                    "image_url": image_url,
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
                            "image_url": "",
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


async def _extract_image_url(element) -> str:
    for selector in IMAGE_SELECTORS:
        try:
            image = element.locator(selector).first
            if await image.count() <= 0:
                continue
            for attr in ["src", "data-src", "data-lazy-src"]:
                value = await image.get_attribute(attr)
                if value:
                    return _absolute_blinkit_url(value)
            srcset = await image.get_attribute("srcset")
            if srcset:
                first = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
                if first:
                    return _absolute_blinkit_url(first)
        except Exception:
            continue
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
            name = _first_text_present(obj, ["name", "product_name", "display_name", "title"])
            price = _first_text_present(
                obj,
                ["price", "selling_price", "discounted_price", "mrp", "unit_price"],
            )
            available = _product_available(obj)
            url = _first_present(obj, ["url", "product_url", "deeplink"], default="")
            image_url = _image_url_from_obj(obj)
            product_id = _first_present(obj, ["product_id", "productId", "id"], default="")

            if isinstance(name, str) and _is_hotwheels_product_name(name):
                if available or include_unavailable:
                    product_url = _absolute_blinkit_url(url) if isinstance(url, str) else ""
                    if not product_url and product_id:
                        product_url = _blinkit_product_url(name, product_id)
                    products.append(
                        {
                            "name": _compact_text(name),
                            "price": _clean_price(str(price) if price else ""),
                            "available": available,
                            "location": location["name"],
                            "source": "api",
                            "url": product_url,
                            "image_url": image_url,
                            "product_id": str(product_id) if product_id else "",
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


def _is_hotwheels_product_name(name: str) -> bool:
    lowered = name.lower()
    if "hot wheels" not in lowered:
        return False
    if lowered.startswith("showing results for"):
        return False
    if lowered.startswith("search instead for"):
        return False
    return True


def _first_text_present(obj: dict, keys: list[str], default=None):
    for key in keys:
        if key not in obj or obj[key] in (None, ""):
            continue
        value = obj[key]
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str) and text:
                return text
    return default


def _image_url_from_obj(obj: dict) -> str:
    direct = _first_present(
        obj,
        [
            "image_url",
            "imageUrl",
            "image",
            "imageUrlLarge",
            "thumbnail",
            "thumbnail_url",
            "media_url",
            "product_image",
        ],
        default="",
    )
    found = _first_image_url(direct)
    if found:
        return found

    return _first_image_url(obj)


def _first_image_url(value) -> str:
    if isinstance(value, str):
        if value.startswith("//"):
            return f"https:{value}"
        if value.startswith(("http://", "https://", "/")):
            return _absolute_blinkit_url(value)
        return ""
    if isinstance(value, dict):
        for item in value.values():
            found = _first_image_url(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _first_image_url(item)
            if found:
                return found
    return ""


def _absolute_blinkit_url(value: str) -> str:
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"https://blinkit.com{value}"
    return value


def _blinkit_product_url(name: str, product_id) -> str:
    slug = _slugify(name)
    return f"https://blinkit.com/prn/{slug}/prid/{product_id}"


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-") or "hot-wheels"


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
    if "unavailable_quantity" in key:
        return False
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
        existing = deduped.get(key)
        if not existing or _richness_score(product) >= _richness_score(existing):
            deduped[key] = product
    return list(deduped.values())


def _richness_score(product: dict) -> int:
    return int(bool(product.get("image_url"))) + int(bool(product.get("url")))


def _compact_text(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def _clean_price(raw: str) -> str:
    if not raw:
        return "N/A"
    match = re.search(r"[\d,]+(?:\.\d+)?", raw)
    if match:
        return "Rs. " + match.group().replace(",", "")
    return _compact_text(raw)
