import html
import logging

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_PHOTO_API = "https://api.telegram.org/bot{token}/sendPhoto"
PLACEHOLDER_TOKENS = {"", "YOUR_BOT_TOKEN_HERE"}
PLACEHOLDER_CHAT_IDS = {"", "YOUR_CHAT_ID_HERE"}
MAX_TELEGRAM_CHARS = 3800
BLINKIT_SEARCH_URL = "https://blinkit.com/s/?q=hot%20wheels"


async def send_curated_priority_alert(
    report: dict,
    telegram_cfg: dict,
    config: dict | None = None,
) -> None:
    groups = report.get("priority_groups", [])
    if not groups:
        return

    counts = report.get("counts", {})
    alert_cfg = (config or {}).get("telegram_alerts", {})
    max_images = int(alert_cfg.get("max_priority_images", 1))
    photo_groups = [group for group in groups if group.get("image_url")][:max_images]
    photo_group_ids = {id(group) for group in photo_groups}

    for index, group in enumerate(photo_groups, start=1):
        caption = "\n".join(_format_group(group, index=index, compact=True))
        await _send_telegram_photo(
            telegram_cfg,
            group.get("image_url", ""),
            caption,
            reply_markup=_button_markup(_group_url(group)),
        )

    remaining_groups = [
        group for group in groups if id(group) not in photo_group_ids
    ]

    lines = [
        "<b>HOT WHEELS ALERT | Pune Blinkit</b>",
        f"<b>{len(groups)} new collector pick(s)</b> worth opening Blinkit for.",
        f"Scanned: {counts.get('product_location_listings', 0)} listings | "
        f"Unique: {counts.get('unique_castings', 0)}",
        "",
    ]

    if report.get("quiet_hours_grail_override"):
        lines.append("<b>Quiet-hours grail override:</b> sending only urgent grail-level finds now.")
        lines.append("")

    for index, group in enumerate(remaining_groups, start=len(photo_groups) + 1):
        lines.extend(_format_group(group, index=index))

    if photo_groups and not remaining_groups:
        lines.append("Top pick sent above with image preview.")

    hidden = counts.get("hidden_castings", 0)
    ignored = counts.get("ignored_listings", 0)
    if hidden or ignored:
        lines.append("")
        lines.append(f"Not in alert: {hidden} lower-priority, {ignored} skipped/noise.")

    lines.append("")
    lines.append(f"<a href=\"{BLINKIT_SEARCH_URL}\">Open Blinkit Hot Wheels search</a>")
    await _send_telegram(
        telegram_cfg,
        "\n".join(lines),
        reply_markup=_button_markup(BLINKIT_SEARCH_URL, text="Open Blinkit search"),
    )
    logger.info("Telegram curated priority alert handled for %s groups", len(groups))


async def send_curated_stock_digest(
    report: dict,
    telegram_cfg: dict,
    config: dict | None = None,
) -> None:
    counts = report.get("counts", {})
    priority_groups = report.get("priority_groups", [])
    digest_groups = report.get("digest_groups", [])
    if not priority_groups and not digest_groups:
        return

    alert_cfg = (config or {}).get("telegram_alerts", {})
    max_images = int(alert_cfg.get("max_digest_images", alert_cfg.get("max_priority_images", 1)))
    digest_photo_groups = [
        group for group in priority_groups + digest_groups if group.get("image_url")
    ][:max_images]

    for index, group in enumerate(digest_photo_groups, start=1):
        caption = "\n".join(
            [
                "<b>Digest Preview</b>",
                *_format_group(group, index=index, compact=True),
            ]
        )
        await _send_telegram_photo(
            telegram_cfg,
            group.get("image_url", ""),
            caption,
            reply_markup=_button_markup(_group_url(group)),
        )

    lines = [
        "<b>Hot Wheels Digest | Pune Blinkit</b>",
        f"Collector-grade: <b>{counts.get('priority_castings', 0)}</b> | "
        f"Unique seen: <b>{counts.get('unique_castings', 0)}</b> | "
        f"Listings: <b>{counts.get('product_location_listings', 0)}</b>",
        "",
    ]

    if priority_groups:
        lines.append("<b>Open Blinkit For These</b>")
        for index, group in enumerate(priority_groups, start=1):
            lines.extend(_format_group(group, index=index, compact=True))
        lines.append("")

    if digest_groups:
        lines.append("<b>Watchlist / Nice-To-Know</b>")
        for index, group in enumerate(digest_groups, start=1):
            lines.extend(_format_group(group, index=index, compact=True))
        lines.append("")

    lines.append(
        f"Filtered out: {counts.get('common_listings', 0)} common, "
        f"{counts.get('ignored_listings', 0)} fantasy/generic/playset."
    )
    lines.append(f"<a href=\"{BLINKIT_SEARCH_URL}\">Open Blinkit Hot Wheels search</a>")

    await _send_telegram(
        telegram_cfg,
        "\n".join(lines),
        reply_markup=_button_markup(BLINKIT_SEARCH_URL, text="Open Blinkit search"),
    )
    logger.info("Telegram curated stock digest handled")


async def send_priority_alert(priority_products: list[dict], telegram_cfg: dict) -> None:
    """Send an urgent Telegram alert for collector-grade products."""
    if not priority_products:
        return

    by_location: dict[str, list[dict]] = {}
    for product in priority_products:
        by_location.setdefault(product["location"], []).append(product)

    lines = ["<b>Collector Alert - Blinkit Pune</b>", ""]

    for location, products in by_location.items():
        lines.append(f"<b>{html.escape(location)}</b>")
        for product in products:
            lines.extend(_format_product(product, include_tier=True))
        lines.append("")

    lines.append("Open Blinkit quickly if you want one of these.")
    await _send_telegram(telegram_cfg, "\n".join(lines))
    logger.info("Telegram priority alert handled for %s products", len(priority_products))


async def send_stock_digest(
    all_products: list[dict],
    priority_products: list[dict],
    telegram_cfg: dict,
    digest_max_items_per_location: int = 24,
) -> None:
    """Send a quieter digest of available stock across all locations."""
    if not all_products:
        return

    lines = [
        "<b>Hot Wheels Stock Digest - Blinkit Pune</b>",
        f"Collector picks right now: <b>{len(priority_products)}</b>",
        f"Total product/location listings: <b>{len(all_products)}</b>",
        "",
    ]

    if priority_products:
        lines.append("<b>Collector picks first</b>")
        for product in priority_products:
            lines.extend(_format_product(product, include_location=True, include_tier=True))
        lines.append("")

    by_location: dict[str, list[dict]] = {}
    for product in all_products:
        by_location.setdefault(product["location"], []).append(product)

    lines.append("<b>All available castings</b>")
    for location, products in by_location.items():
        lines.append("")
        lines.append(f"<b>{html.escape(location)}</b>")
        for product in products[:digest_max_items_per_location]:
            tier = product.get("collector_tier", "common")
            marker = "" if tier == "common" else f" [{tier}]"
            name = html.escape(product.get("name", "Unknown product"))
            price = html.escape(str(product.get("price", "N/A")))
            lines.append(f"- <code>{name}</code>{html.escape(marker)} - {price}")
        remaining = len(products) - digest_max_items_per_location
        if remaining > 0:
            lines.append(f"...and {remaining} more")

    await _send_telegram(telegram_cfg, "\n".join(lines))
    logger.info("Telegram stock digest handled for %s products", len(all_products))


async def send_alert(matched_products: list[dict], telegram_cfg: dict) -> None:
    """Backward-compatible alias for older callers."""
    await send_priority_alert(matched_products, telegram_cfg)


async def send_startup_message(telegram_cfg: dict, locations: list) -> None:
    """Send a confirmation message when the agent starts."""
    loc_names = ", ".join(location["name"] for location in locations) or "no locations"
    msg = (
        "<b>Hot Wheels Agent Started</b>\n\n"
        f"Monitoring: {html.escape(loc_names)}\n"
        "Urgent alerts are collector-grade only. Stock digests are quieter."
    )
    await _send_telegram(telegram_cfg, msg)


async def send_heartbeat(telegram_cfg: dict, run_count: int, locations: list) -> None:
    """Optional heartbeat so you know the agent is alive."""
    loc_names = ", ".join(location["name"] for location in locations) or "no locations"
    msg = (
        f"<b>Agent Heartbeat</b> (Run #{run_count})\n"
        f"Checked: {html.escape(loc_names)}\n"
        "No desired castings found this cycle."
    )
    await _send_telegram(telegram_cfg, msg)


async def _send_telegram(
    telegram_cfg: dict,
    text: str,
    reply_markup: dict | None = None,
) -> None:
    await _send_telegram_message(telegram_cfg, text, reply_markup=reply_markup)


async def _send_telegram_message(
    telegram_cfg: dict,
    text: str,
    reply_markup: dict | None = None,
) -> None:
    token = telegram_cfg.get("bot_token", "")
    chat_id = telegram_cfg.get("chat_id", "")
    if token in PLACEHOLDER_TOKENS or chat_id in PLACEHOLDER_CHAT_IDS:
        logger.warning("Telegram is not configured; message was not sent:\n%s", text)
        return

    url = TELEGRAM_MESSAGE_API.format(token=token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in _split_message(text):
                payload = {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                response = await client.post(
                    url,
                    json=payload,
                )
                response.raise_for_status()
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)


async def _send_telegram_photo(
    telegram_cfg: dict,
    photo_url: str,
    caption: str,
    reply_markup: dict | None = None,
) -> None:
    token = telegram_cfg.get("bot_token", "")
    chat_id = telegram_cfg.get("chat_id", "")
    if token in PLACEHOLDER_TOKENS or chat_id in PLACEHOLDER_CHAT_IDS:
        logger.warning("Telegram is not configured; photo alert was not sent:\n%s", caption)
        return
    if not photo_url:
        return

    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    url = TELEGRAM_PHOTO_API.format(token=token)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Telegram photo alert sent")
    except Exception as exc:
        logger.warning("Telegram photo send failed; falling back to text: %s", exc)
        await _send_telegram_message(telegram_cfg, caption, reply_markup=reply_markup)


def _format_product(
    product: dict,
    include_location: bool = False,
    include_tier: bool = False,
) -> list[str]:
    status = "In stock" if product.get("available") else "May be out of stock"
    name = html.escape(product.get("name", "Unknown product"))
    price = html.escape(str(product.get("price", "N/A")))
    tier = html.escape(product.get("collector_tier", "common"))
    reason = html.escape(product.get("collector_reason", "Available stock"))
    prefix = f"{html.escape(product.get('location', ''))}: " if include_location else ""
    tier_text = f" | Tier: {tier}" if include_tier else ""
    return [
        f"- {prefix}<code>{name}</code>",
        f"  Price: {price} | {status}{tier_text}",
        f"  Why: {reason}",
    ]


def _format_group(group: dict, index: int | None = None, compact: bool = False) -> list[str]:
    name = html.escape(group.get("name", "Unknown casting"))
    tier = html.escape(_tier_label(group.get("tier", "common")))
    reason = html.escape(group.get("reason", "Available stock"))
    price = html.escape(_price_text(group.get("prices", [])))
    locations = html.escape(_location_text(group.get("locations", [])))
    wishlist = group.get("products", [{}])[0].get("wishlist_priority", "")
    wishlist_text = f" | Wishlist: {html.escape(wishlist)}" if wishlist else ""
    prefix = f"{index}. " if index is not None else ""

    if compact:
        return [
            f"<b>{prefix}{name}</b>",
            f"{price} | {tier}{wishlist_text} | {locations}",
        ]

    return [
        f"<b>{prefix}{name}</b>",
        f"Price: {price}",
        f"Where: {locations}",
        f"Signal: {tier}{wishlist_text} | {reason}",
        "",
    ]


def _group_url(group: dict) -> str:
    url = group.get("url", "")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url
    for product in group.get("products", []):
        product_url = product.get("url", "")
        if isinstance(product_url, str) and product_url.startswith(("http://", "https://")):
            return product_url
    return BLINKIT_SEARCH_URL


def _button_markup(url: str, text: str = "Open on Blinkit") -> dict:
    safe_url = url if url.startswith(("http://", "https://")) else BLINKIT_SEARCH_URL
    return {"inline_keyboard": [[{"text": text, "url": safe_url}]]}


def _price_text(prices: list[str]) -> str:
    clean = [price for price in prices if price and price != "N/A"]
    if not clean:
        return "N/A"
    if len(clean) == 1:
        return clean[0]
    return f"{clean[0]}-{clean[-1]}"


def _location_text(locations: list[str]) -> str:
    if not locations:
        return "location unknown"
    if len(locations) <= 3:
        return ", ".join(locations)
    return f"{', '.join(locations[:3])} +{len(locations) - 3} more"


def _tier_label(tier: str) -> str:
    return {
        "grail": "GRAIL",
        "premium": "PREMIUM",
        "real_car": "LICENSED",
        "maybe": "MAYBE",
        "fantasy": "FANTASY",
        "common": "COMMON",
        "ignored": "SKIPPED",
    }.get(tier, tier.upper())


def _split_message(text: str) -> list[str]:
    chunks = []
    current = []
    current_length = 0

    for line in text.splitlines():
        line_length = len(line) + 1
        if current and current_length + line_length > MAX_TELEGRAM_CHARS:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += line_length

    if current:
        chunks.append("\n".join(current))
    return chunks
