from collections import defaultdict

from collector import TIER_RANK, normalize


def build_curated_report(products: list[dict], config: dict) -> dict:
    """Condense raw product/location listings into a Telegram-friendly report."""
    collector_cfg = config.get("collector", {})
    immediate_tiers = set(
        collector_cfg.get("immediate_alert_tiers", ["grail", "premium", "real_car"])
    )
    digest_tiers = set(
        collector_cfg.get("digest_include_tiers", ["grail", "premium", "real_car", "maybe", "fantasy"])
    )
    max_priority = int(collector_cfg.get("digest_max_priority_items", 10))
    max_other = int(collector_cfg.get("digest_max_other_items", 14))

    groups = _group_products(products)
    priority_groups = [
        group for group in groups if group["tier"] in immediate_tiers
    ][:max_priority]
    digest_groups = [
        group
        for group in groups
        if group["tier"] in digest_tiers and group["tier"] not in immediate_tiers
    ][:max_other]

    return {
        "priority_groups": priority_groups,
        "digest_groups": digest_groups,
        "counts": _counts(products, groups, priority_groups, digest_groups),
    }


def _group_products(products: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for product in products:
        if product.get("collector_tier") == "ignored":
            continue
        buckets[_group_key(product)].append(product)

    groups = []
    for items in buckets.values():
        best = sorted(items, key=_product_sort_key)[0]
        locations = sorted({item.get("location", "") for item in items if item.get("location")})
        prices = sorted({str(item.get("price", "N/A")) for item in items if item.get("price")})
        groups.append(
            {
                "name": _display_name(best.get("name", "")),
                "raw_name": best.get("name", ""),
                "tier": best.get("collector_tier", "common"),
                "score": int(best.get("collector_score", 0)),
                "reason": best.get("collector_reason", "Available stock"),
                "terms": best.get("collector_terms", []),
                "locations": locations,
                "prices": prices or ["N/A"],
                "count": len(items),
                "products": items,
            }
        )

    return sorted(groups, key=_group_sort_key)


def _group_key(product: dict) -> str:
    return normalize(product.get("name", ""))


def _display_name(name: str) -> str:
    normalized_prefixes = [
        "Hot Wheels ",
    ]
    for prefix in normalized_prefixes:
        if name.startswith(prefix):
            return name[len(prefix):].strip()
    return name.strip()


def _counts(
    products: list[dict],
    groups: list[dict],
    priority_groups: list[dict],
    digest_groups: list[dict],
) -> dict:
    by_tier = defaultdict(int)
    for product in products:
        by_tier[product.get("collector_tier", "common")] += 1

    shown_names = {group["raw_name"] for group in priority_groups + digest_groups}
    hidden_groups = [group for group in groups if group["raw_name"] not in shown_names]

    return {
        "product_location_listings": len(products),
        "unique_castings": len(groups),
        "priority_castings": len([g for g in groups if g["tier"] in {"grail", "premium", "real_car"}]),
        "shown_castings": len(priority_groups) + len(digest_groups),
        "hidden_castings": len(hidden_groups),
        "ignored_listings": by_tier.get("ignored", 0),
        "common_listings": by_tier.get("common", 0),
        "by_tier": dict(sorted(by_tier.items())),
    }


def _product_sort_key(product: dict) -> tuple:
    return (
        -int(product.get("collector_score", 0)),
        product.get("price", ""),
        product.get("name", ""),
        product.get("location", ""),
    )


def _group_sort_key(group: dict) -> tuple:
    return (
        -TIER_RANK.get(group["tier"], 0),
        _price_sort_value(group["prices"][0]),
        group["name"],
    )


def _price_sort_value(price: str) -> int:
    digits = "".join(ch for ch in str(price) if ch.isdigit())
    return int(digits) if digits else 999999
