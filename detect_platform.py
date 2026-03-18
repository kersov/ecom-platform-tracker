#!/usr/bin/env python3
"""
detect_platform.py

- Reads sites.json
- Fetches each site with SeleniumBase (UC mode) to bypass bot detection
- Uses heuristics to detect platform
- Writes results into data.json

Intended to be run inside GitHub Actions (Docker) or locally.
"""
import json
import os
from datetime import datetime

from seleniumbase import SB
from selenium.common.exceptions import TimeoutException, WebDriverException

ROOT = os.path.dirname(os.path.abspath(__file__))
SITES_FILE = os.path.join(ROOT, 'sites.json')
DATA_FILE = os.path.join(ROOT, 'data.json')

TIMEOUT = 15


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
    return 'Unidentified'


# -------------------------
# Fetcher
# -------------------------
def fetch_all_sites(sites):
    """Navigate each site with a single reused Chrome instance, return name -> platform dict."""
    results = {}
    with SB(uc=True, headless=True,
            chromium_arg="--no-sandbox --disable-gpu --disable-dev-shm-usage") as sb:
        sb.driver.set_page_load_timeout(TIMEOUT)
        for site in sites:
            name = site.get('name') or site.get('url') or 'unidentified'
            url = site.get('url')
            if not url:
                print(f"[WARN] Site entry missing 'url': {site}")
                continue
            try:
                sb.open(url)
                html = sb.get_page_source()
                platform = detect_platform_from_text(html, {}, url)
                print(f"Checked {name} -> {url}  =>  {platform}")
                results[name] = platform
            except TimeoutException:
                print(f"[WARN] Timeout fetching {url}")
                sb.open("about:blank")
            except WebDriverException as e:
                msg = str(e)[:120]
                print(f"[WARN] WebDriverException {url}: {msg}")
                sb.open("about:blank")
            except Exception as e:
                msg = str(e)[:120]
                print(f"[WARN] Unexpected error {url}: {msg}")
                sb.open("about:blank")
    return results


# -------------------------
# Main
# -------------------------
def main():
    with open(SITES_FILE, 'r', encoding='utf-8') as f:
        sites = json.load(f)

    data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

    date_str = datetime.utcnow().date().isoformat()

    results = fetch_all_sites(sites)

    for name, platform in results.items():
        if name not in data:
            data[name] = []
        history = data[name]
        if not history or list(history[-1].values())[0] != platform:
            history.append({date_str: platform})
            print(f"  -> {name}: updated to {platform}")
        else:
            print(f"  -> {name}: unchanged ({platform})")

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Data saved to {DATA_FILE}")


if __name__ == '__main__':
    main()
