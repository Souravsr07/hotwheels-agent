import asyncio
import json

from playwright.async_api import async_playwright


async def main() -> None:
    with open("config.json", encoding="utf-8-sig") as file:
        config = json.load(file)

    location = config["locations"][0]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            geolocation={"latitude": location["lat"], "longitude": location["lng"]},
            permissions=["geolocation"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={"lat": str(location["lat"]), "lon": str(location["lng"])},
        )
        await context.add_cookies(
            [
                {"name": "gr_1_lat", "value": str(location["lat"]), "domain": "blinkit.com", "path": "/"},
                {"name": "gr_1_lon", "value": str(location["lng"]), "domain": "blinkit.com", "path": "/"},
                {"name": "gr_1_landmark", "value": "undefined", "domain": "blinkit.com", "path": "/"},
            ]
        )
        page = await context.new_page()

        async def on_request(request):
            if "/v1/layout/search" in request.url:
                print("URL:", request.url)
                headers = await request.all_headers()
                for key in sorted(headers):
                    lowered = key.lower()
                    if any(term in lowered for term in ["lat", "lon", "lng", "location", "merchant", "auth"]):
                        print(f"{key}: {headers[key]}")
                print("cookie:", headers.get("cookie", "")[:1000])

        page.on("request", on_request)
        await page.goto(config["scraper"]["search_url"], wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)
        print("final url:", page.url)
        print("title:", await page.title())
        print("cookies:", await context.cookies("https://blinkit.com"))
        location_state = await page.evaluate("window.localStorage.getItem('location')")
        merchant_state = await page.evaluate("window.localStorage.getItem('merchant')")
        print("location localStorage:", location_state)
        if merchant_state:
            merchant = json.loads(merchant_state)
            print("merchant:", {"id": merchant.get("id"), "name": merchant.get("name")})
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
