#!/usr/bin/env python3
"""
detect_platform.py

- Reads sites.json
- Fetches each site (HTTP GET)
- Uses heuristics to detect platform
- Writes results into a single JSON file `data.json`

Intended to be run inside GitHub Actions (Docker) or locally.
"""
import json
import os
from datetime import datetime
import asyncio
from playwright.async_api import async_playwright

ROOT = os.path.dirname(__file__) or '.'
SITES_FILE = os.path.join(ROOT, 'sites.json')
DATA_FILE = os.path.join(ROOT, 'data.json')

TIMEOUT = 15  # Increased timeout for browser automation

# -------------------------
# Site loading & fetching
# -------------------------
def load_sites(path=SITES_FILE):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

async def fetch_site(browser, url):
    """Return tuple (html_text or None, headers dict)"""
    page = None
    try:
        page = await browser.new_page()
        response = await page.goto(url, timeout=TIMEOUT * 1000, wait_until='domcontentloaded')
        
        if not response:
            print(f"[WARN] Failed to fetch {url}, no response received.")
            await page.close()
            return None, {}

        if response.status >= 400:
            print(f"[WARN] Failed to fetch {url} with status {response.status}")
            await page.close()
            return None, {}

        html = await page.content()
        headers = await response.all_headers()
        await page.close()
        return html, headers
    except Exception as e:
        print(f"[WARN] Failed to fetch {url} : {e}")
        if page and not page.is_closed():
            await page.close()
        return None, {}

# -------------------------
# Heuristic detection
# -------------------------
def detect_platform_from_text(html_text, headers, url):
    """Return platform name or 'Unidentified'"""
    html_text_orig = html_text or ''
    text = html_text_orig.lower()
    hdr_keys = ' '.join([k.lower() for k in (headers.keys() if headers else [])])
    hdr_vals = ' '.join([str(v).lower() for v in (headers.values() if headers else [])])

    # Shopify
    # More specific checks to avoid false positives from plugins on other platforms.
    if ('cdn.shopify.com' in text or '.myshopify.com' in text or 'Shopify.theme' in html_text_orig or
            'content="Shopify"' in text or 'x-shopify-' in hdr_keys or 'x-shopify-' in hdr_vals):
        return 'Shopify'
    # WooCommerce / WordPress e-commerce plugin patterns
    if 'woocommerce' in text or '/wp-content/plugins/woocommerce' in text or 'woocommerce' in hdr_keys or 'woocommerce' in hdr_vals:
        return 'WooCommerce'
    # Magento / Adobe Commerce
    if 'mage.js' in text or 'var mage' in text or 'magento' in text or '/skin/frontend/' in text:
        return 'Magento'
    # Salesforce Commerce Cloud (Demandware)
    if 'demandware' in text or 'bmcdn.net' in text or 'salesforce' in text or 'sfcc' in text or 'dwstatic' in text:
        return 'Salesforce Commerce Cloud'
    # SAP Commerce Cloud (Hybris / Spartacus / OCC)
    # Common indicators: 'hybris', 'yaccelerator', 'spartacus', 'occ/v', '/occ/v2/', '/rest/v2/', 'sap-commerce'
    if ('hybris' in text or 'yaccelerator' in text or 'spartacus' in text or
        '/occ/v' in text or '/rest/v' in text or 'sap-commerce' in text or 'sap commerce' in text):
        return 'SAP Commerce Cloud'
    # Oracle Commerce Cloud
    if 'oracle' in text or 'occ-commercestore' in text or 'oraclecloud' in text:
        return 'Oracle Commerce Cloud'
    # BigCommerce
    if 'bigcommerce' in text:
        return 'BigCommerce'
    # Commercetools
    if 'commercetools' in text:
        return 'Commercetools'
    # PrestaShop
    if 'prestashop' in text or 'prestashop' in hdr_vals:
        return 'PrestaShop'
    # Wix
    if 'wix.com' in text or 'wixstatic' in text:
        return 'Wix'
    # Squarespace
    if 'squarespace' in text:
        return 'Squarespace'
    # OpenCart
    if 'opencart' in text or 'index.php?route=' in (url or ''):
        return 'OpenCart'
    # WordPress (non-Woo)
    if 'wp-content' in text or 'wp-include' in text:
        return 'WordPress'
    # Fallback
    return 'Unidentified'

# -------------------------
# Main run
# -------------------------
async def main():
    # load sites
    sites = load_sites()
    
    # load data
    data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

    # use UTC date for consistent long-term tracking
    date_str = datetime.utcnow().date().isoformat()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for s in sites:
            name = s.get('name') or s.get('url') or 'unidentified'
            url = s.get('url')
            if not url:
                print(f"[WARN] Site entry missing 'url': {s}")
                continue
            print(f"Checking {name} -> {url}")
            html, headers = await fetch_site(browser, url)
            if not html:
                continue
            platform = detect_platform_from_text(html, headers, url)
            print(f"  -> Detected: {platform}")

            # Update data only if the platform has changed
            if name not in data:
                data[name] = []
            
            history = data[name]
            if not history or list(history[-1].values())[0] != platform:
                history.append({date_str: platform})
                print(f"  -> New platform detected. Updating data.")
            else:
                print(f"  -> Platform remains the same. No update.")
        await browser.close()

    # save data
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"Data saved to {DATA_FILE}")

if __name__ == '__main__':
    asyncio.run(main())
