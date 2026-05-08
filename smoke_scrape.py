import asyncio
import json

from collector import classify_products, priority_products
from scraper import scrape_location


async def main() -> None:
    with open("config.json", encoding="utf-8-sig") as file:
        config = json.load(file)

    config["scraper"]["headless"] = True
    config["scraper"]["max_retries"] = 1

    for location in config["locations"]:
        products = await scrape_location(location, config)
        classified = classify_products(products, config)
        matches = priority_products(classified, config)
        preview = ", ".join(product["name"] for product in products[:2])
        print(f"{location['name']}: {len(products)} products, {len(matches)} matches")
        if preview:
            print(f"  preview: {preview}")
        for match in matches:
            print(f"  PICK: {match['name']} -> {match['collector_reason']}")


if __name__ == "__main__":
    asyncio.run(main())
