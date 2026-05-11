import json
import logging
from pathlib import Path

from collector import TIER_RANK, normalize

logger = logging.getLogger(__name__)

COLLECTION_PATH = Path(__file__).resolve().parent / "collection.json"
WISHLIST_TIER_FLOORS = {
    "GRAIL": "grail",
    "HIGH": "premium",
    "MEDIUM": "real_car",
}


def load_collection() -> dict:
    if not COLLECTION_PATH.exists():
        return {"owned": [], "owned_keywords": [], "wishlist_priority": {}}

    try:
        with open(COLLECTION_PATH, encoding="utf-8-sig") as file:
            collection = json.load(file)
    except Exception as exc:
        logger.warning("Could not read collection.json; collection filters disabled: %s", exc)
        return {"owned": [], "owned_keywords": [], "wishlist_priority": {}}

    collection.setdefault("owned", [])
    collection.setdefault("owned_keywords", [])
    collection.setdefault("wishlist_priority", {})
    return collection


def apply_collection_preferences(products: list[dict], collection: dict) -> list[dict]:
    """Remove owned castings and raise wishlist matches without weakening existing rules."""
    kept = []
    skipped = 0
    for product in products:
        if _is_owned(product.get("name", ""), collection):
            skipped += 1
            continue
        kept.append(_apply_wishlist(product, collection))

    if skipped:
        logger.info("Skipped %s owned product/location listing(s)", skipped)
    return kept


def _is_owned(name: str, collection: dict) -> bool:
    normalized = normalize(name)
    compact = normalized.replace(" ", "")
    if not normalized:
        return False

    for item in collection.get("owned", []):
        owned = normalize(str(item))
        if not owned:
            continue
        owned_compact = owned.replace(" ", "")
        if compact == owned_compact:
            return True
        if len(owned.split()) > 1 and owned in normalized:
            return True

    for keyword in collection.get("owned_keywords", []):
        owned_keyword = normalize(str(keyword))
        if owned_keyword and owned_keyword in normalized:
            return True

    return False


def _apply_wishlist(product: dict, collection: dict) -> dict:
    match = _wishlist_match(product.get("name", ""), collection)
    if not match:
        return product

    term, priority = match
    enriched = dict(product)
    label = str(priority).upper()
    enriched["wishlist_priority"] = label
    enriched["wishlist_term"] = term

    floor_tier = WISHLIST_TIER_FLOORS.get(label)
    if floor_tier and TIER_RANK[floor_tier] > int(enriched.get("collector_score", 0)):
        enriched["collector_tier"] = floor_tier
        enriched["collector_score"] = TIER_RANK[floor_tier]

    reason = enriched.get("collector_reason", "Available stock")
    enriched["collector_reason"] = f"Wishlist {label}: {term} | {reason}"
    return enriched


def _wishlist_match(name: str, collection: dict) -> tuple[str, str] | None:
    normalized = normalize(name)
    if not normalized:
        return None

    for term, priority in collection.get("wishlist_priority", {}).items():
        normalized_term = normalize(str(term))
        if normalized_term and normalized_term in normalized:
            return str(term), str(priority)
    return None
