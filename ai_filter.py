import json
import logging
import re
from difflib import SequenceMatcher

import httpx

logger = logging.getLogger(__name__)

PLACEHOLDER_KEYS = {"", "YOUR_ANTHROPIC_KEY_HERE", "sk-ant-..."}
SPECIAL_WATCHLIST = {
    "treasure hunt": ["treasure hunt", "t-hunt", " t hunt ", " th "],
    "super treasure hunt": ["super treasure hunt", "sth", "s-th"],
    "premium": ["premium", "car culture", "boulevard", "team transport", "pop culture"],
    "car culture": ["car culture"],
}


async def filter_products(
    products: list[dict], desired_castings: list[str], api_key: str
) -> list[dict]:
    """
    Match scraped products against the collector watchlist.

    The local matcher runs first and is good enough for exact/fuzzy casting names.
    Claude is used only when an API key is configured, then merged with local results.
    """
    if not products:
        return []

    local_matches = _local_filter(products, desired_castings)
    if not api_key or api_key in PLACEHOLDER_KEYS:
        logger.info(
            "Filter: %s products -> %s local matches; Claude skipped",
            len(products),
            len(local_matches),
        )
        return local_matches

    try:
        claude_matches = await _claude_filter(products, desired_castings, api_key)
    except Exception as exc:
        logger.error("Claude API filter error: %s", exc)
        claude_matches = []

    merged = _merge_matches(local_matches + claude_matches)
    logger.info("Filter: %s products -> %s matches", len(products), len(merged))
    return merged


async def _claude_filter(
    products: list[dict], desired_castings: list[str], api_key: str
) -> list[dict]:
    product_names = [p["name"] for p in products]
    prompt = f"""You are an expert Hot Wheels collector assistant.

Given this list of scraped product names from Blinkit:
{json.dumps(product_names, indent=2)}

And this desired castings watchlist:
{json.dumps(desired_castings, indent=2)}

Identify which scraped products match the desired castings. Apply these rules:
1. Fuzzy match names, so "BoneShaker", "Bone-Shaker", and "Bone Shaker" all match.
2. If the product name contains a desired casting name as a substring, it matches.
3. Treasure Hunt, Super Treasure Hunt, Premium, and Car Culture are series keywords.
4. Generic "Hot Wheels" without a specific casting or series should not match.
5. Return only products from the scraped list.

Respond only with JSON:
{{
  "matches": [
    {{
      "product_name": "exact name from scraped list",
      "matched_casting": "watchlist item it matches",
      "confidence": "HIGH / MEDIUM / LOW",
      "reason": "brief explanation"
    }}
  ]
}}"""

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        raw_text = data["content"][0]["text"].strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.removeprefix("json").strip()

    result = json.loads(raw_text)
    matches = result.get("matches", [])
    return _attach_matches(products, matches, source="claude")


def _local_filter(products: list[dict], desired_castings: list[str]) -> list[dict]:
    matches = []
    for product in products:
        name = product.get("name", "")
        normalized_name = _normalize(name)

        if "hot wheels" not in normalized_name and "hw " not in f" {normalized_name} ":
            continue

        for casting in desired_castings:
            if _matches_casting(normalized_name, casting):
                enriched = dict(product)
                enriched["matched_casting"] = casting
                enriched["match_confidence"] = _confidence(normalized_name, casting)
                enriched["match_reason"] = "Local watchlist match"
                enriched["match_source"] = "local"
                matches.append(enriched)
                break

    return _merge_matches(matches)


def _matches_casting(normalized_name: str, casting: str) -> bool:
    normalized_casting = _normalize(casting)
    special_terms = SPECIAL_WATCHLIST.get(normalized_casting)
    if special_terms:
        haystack = f" {normalized_name} "
        return any(f" {_normalize(term)} " in haystack for term in special_terms)

    if normalized_casting in normalized_name:
        return True

    compact_name = normalized_name.replace(" ", "")
    compact_casting = normalized_casting.replace(" ", "")
    if compact_casting and compact_casting in compact_name:
        return True

    return SequenceMatcher(None, compact_name, compact_casting).ratio() >= 0.88


def _confidence(normalized_name: str, casting: str) -> str:
    normalized_casting = _normalize(casting)
    if normalized_casting in normalized_name:
        return "HIGH"
    ratio = SequenceMatcher(
        None, normalized_name.replace(" ", ""), normalized_casting.replace(" ", "")
    ).ratio()
    return "HIGH" if ratio >= 0.94 else "MEDIUM"


def _attach_matches(products: list[dict], matches: list[dict], source: str) -> list[dict]:
    matched_products = []
    by_name = {p["name"]: p for p in products}

    for match in matches:
        product = by_name.get(match.get("product_name", ""))
        if not product:
            continue

        enriched = dict(product)
        enriched["matched_casting"] = match.get("matched_casting", "")
        enriched["match_confidence"] = match.get("confidence", "MEDIUM")
        enriched["match_reason"] = match.get("reason", "")
        enriched["match_source"] = source
        matched_products.append(enriched)

    return matched_products


def _merge_matches(matches: list[dict]) -> list[dict]:
    merged = {}
    for match in matches:
        key = (
            match.get("location", "").lower(),
            match.get("name", "").lower(),
        )
        existing = merged.get(key)
        if existing is None or _confidence_rank(match) > _confidence_rank(existing):
            merged[key] = match
    return list(merged.values())


def _confidence_rank(match: dict) -> int:
    return {"LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(match.get("match_confidence"), 0)


def _normalize(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()
