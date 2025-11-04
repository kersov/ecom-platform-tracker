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
import requests

ROOT = os.path.dirname(__file__) or '.'
SITES_FILE = os.path.join(ROOT, 'sites.json')
DATA_FILE = os.path.join(ROOT, 'data.json')

# Basic request settings
HEADERS = {
    'User-Agent': 'ecom-platform-tracker/1.0 (+https://github.com/kersov/ecom-platform-tracker.git)'
}
TIMEOUT = 20

# -------------------------
# Site loading & fetching
# -------------------------
def load_sites(path=SITES_FILE):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def fetch_site(url):
    """Return tuple (html_text or None, headers dict)"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, verify=True)
        r.raise_for_status()
        return r.text, r.headers
    except Exception as e:
        print(f"[WARN] Failed to fetch {url}: {e}")
        return None, {}

# -------------------------
# Heuristic detection
# -------------------------
def detect_platform_from_text(html_text, headers, url):
    """Return platform name or 'Unknown'"""
    text = (html_text or '').lower()
    hdr_keys = ' '.join([k.lower() for k in (headers.keys() if headers else [])])
    hdr_vals = ' '.join([str(v).lower() for v in (headers.values() if headers else [])])

    # Shopify
    if 'cdn.shopify.com' in text or 'shopify' in text or 'x-shopify-stage' in hdr_keys or 'x-shopify-stage' in hdr_vals:
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
    if 'prestashop' in text or 'ps_' in text:
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
    return 'Unknown'

# -------------------------
# Main run
# -------------------------
def main():
    # load sites
    sites = load_sites()
    
    # load data
    data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

    # use UTC date for consistent long-term tracking
    date_str = datetime.utcnow().date().isoformat()

    for s in sites:
        name = s.get('name') or s.get('url') or 'unknown'
        url = s.get('url')
        if not url:
            print(f"[WARN] Site entry missing 'url': {s}")
            continue
        print(f"Checking {name} -> {url}")
        html, headers = fetch_site(url)
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

    # save data
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"Data saved to {DATA_FILE}")

if __name__ == '__main__':
    main()
