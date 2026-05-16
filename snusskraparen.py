#!/usr/bin/python3
import asyncio, aiohttp, re, json, html
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from time import time

_script_location_ = Path(__file__).parent.resolve()
_output_location_ = _script_location_ / "output"
_url_rgx_ = re.compile(r"\.(\w+)$")
_name_rgx_ = re.compile(r"(\d+)\s+dosor", re.IGNORECASE)

async def make_soup(session: aiohttp.ClientSession, url: str, type: str, timeout: int=10) -> BeautifulSoup:
    async with session.get(url, timeout=timeout) as response:
        response.raise_for_status()
        return BeautifulSoup(await response.text(errors="ignore"), type)

async def fetch_urls(session: aiohttp.ClientSession) -> list[str]:
    url = "https://www.snusbolaget.se/sitemap/sitemap-products.xml"
    soup = await make_soup(session, url, "xml")
    texts = [loc.get_text(strip=True) for loc in soup.find_all("loc")]

    return list(set(filter(lambda text: not _url_rgx_.search(text), texts)))

def parse_product(product: dict[str, str]) -> dict[str, any] | None:
    best_offer = None
    name = product.get("name", "")
    match_multiplier = _name_rgx_.findall(name)
    name_multiplier = 1 if len(match_multiplier) == 0 else int(match_multiplier[0])

    for offer in product.get("offers"):
        if type(offer) is str:
            continue

        if not offer.get("availability", "").endswith("InStock"):
            continue

        quantity = int(offer.get("eligibleQuantity", {}).get("value"))
        adjusted_quantity = quantity * name_multiplier
        price = float(offer.get("price"))
        current_offer = {
            "antal": quantity,
            "pris": price,
            "dospris": round(price / adjusted_quantity, 2),
            "valuta": offer.get("priceCurrency"),
        }

        if best_offer is None or current_offer.get("dospris") < best_offer.get("dospris"):
            best_offer = current_offer
    
    if best_offer is None:
        return None
    
    return {
        "namn": product.get("name"),
        "märke": product.get("brand", {}).get("name"),
        "antal": best_offer.get("antal"),
        "pris": best_offer.get("pris"),
        "dospris": best_offer.get("dospris"),
        "valuta": best_offer.get("valuta"),
    }

async def parse_site(session: aiohttp.ClientSession, url: str) -> dict[str, any] | None:
    soup = await make_soup(session, url, "lxml")
    product = None

    for script in soup.find_all("script", type="application/ld+json"):
        data = json.loads(script.get_text(strip=True))
        if type(data) is not dict:
            continue

        if data.get("@type", "") == "Product":
            product = parse_product(data)
            if product:
                product["url"] = url
    
    return product

def generate_html(products: list[dict[str, any]]) -> str:
    products.sort(key=lambda x: x["dospris"])
    generated_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    table_rows = []

    count = 0
    for product in products:
        count += 1
        row = f"""<tr>
    <td>{count}</td>
    <td>
        <a href="{html.escape(product["url"])}" target="_blank">
            {html.escape(product["namn"])}
        </a>
    </td>
    <td>{html.escape(product["märke"])}</td>
    <td>{product["antal"]}</td>
    <td>{product["pris"]}</td>
    <td>{product["dospris"]}</td>
    <td>{html.escape(product["valuta"])}</td>
</tr>
"""
        table_rows.append(row)

    doc = f"""<!DOCTYPE html>
<html lang="sv">
    <head>
        <meta charset="utf-8">
        <title>Snusbolaget PPD</title>
        <style>
            body {{
                font-family: Arial, sans-serif; 
                margin: 2rem;
                background: #fafafa;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                background: white;
            }}
            th, td {{
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }}
            th {{
                background: #eee;
            }}
            tr:nth-child(even) {{
                background: #f7f7f7;
            }}
            a {{
                color: #0645ad;
            }}
        </style>
    </head>
    <body>
        <h1>Snusbolaget pris per dosa</h1>
        <p>Genererad: {generated_time}, antal träffar: {len(products)}</p>
        <table>
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Namn</th>
                    <th>Märke</th>
                    <th>Antal</th>
                    <th>Pris</th>
                    <th>Pris per dosa</th>
                    <th>Valuta</th>
                </tr>
                <tbody>
                    {"".join(table_rows)}
                </tbody>
            </thead>
        </table>
    </body>
</html>
"""
    
    return doc

async def bounded(sem: asyncio.Semaphore, session: aiohttp.ClientSession, url: str) -> list[dict[str, any]]:
    async with sem:
        return await parse_site(session, url)

async def fetch_products(headers: dict[str, str]) -> list[dict[str, any]]:
    sem = asyncio.Semaphore(10)

    async with aiohttp.ClientSession(headers=headers) as session:
        urls = await fetch_urls(session)
        return await asyncio.gather(*(bounded(sem, session, url) for url in urls))

async def main() -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"
    }

    print("Script start...")
    start = time()
    products = [product for product in await fetch_products(headers) if product is not None]

    if len(products) == 0:
        return False

    with open(_output_location_ / "produkter.json", 'w', encoding="utf-8") as w_json:
        json.dump(products, w_json, indent=2, ensure_ascii=False)

    with open(_output_location_ / "snusbolaget_ppd.html", 'w', encoding="utf-8") as w_html:
        w_html.write(generate_html(products))

    end = time()
    total = round(end - start, 2)
    print(f"Script finished in {total} seconds!")

    return True

if __name__ == "__main__":
    asyncio.run(main())