#!/usr/bin/env python3
"""
detect_platform.py

- Reads sites.json
- Fetches each site with a tiered strategy and records the response code
- Uses heuristics to detect platform
- Writes results into data.json

Fetch tiers (a site only escalates when the cheaper tier is blocked):
  Tier 0 — plain `requests` GET. Fast, handles the majority of sites.
  Tier 1 — `curl_cffi` with Chrome impersonation. Re-run only the 403s and
           timeouts; fixes the TLS/HTTP2 fingerprint mismatch behind most
           edge/WAF blocks (SFCC, Magento, generic CDN edge).
  Tier 2 — real browser (nodriver / Camoufox) for the stubborn tail
           (Akamai-backed luxury sites). NOT YET WIRED — see fetch_tier2().

NOTE: detection is HTTP-only (no browser). Tiers 0/1 cannot render JS, so
JS-only sites may stay Unidentified until the Tier 2 browser path is wired.

Intended to be run inside GitHub Actions (Docker) or locally.
"""
import json
import os
import time
from collections import Counter
from datetime import datetime

import requests
from curl_cffi import requests as cffi_requests

ROOT = os.path.dirname(os.path.abspath(__file__))
SITES_FILE = os.path.join(ROOT, 'sites.json')
DATA_FILE = os.path.join(ROOT, 'data.json')

TIMEOUT = 15          # Tier 0 (plain requests)
TIER1_TIMEOUT = 20    # Tier 1 (curl_cffi impersonation)

# A browser-like UA reduces trivial bot blocks on a plain HTTP fetch.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# TODO(proxies): both tiers should route through residential proxies — several
# targets (luxury especially) block on datacenter IP reputation regardless of
# fingerprint. Wire a proxies dict into the tier fetchers once creds exist.


def _is_blocked(status):
    """A result worth escalating to a stronger fetch tier.

    403 = likely bot/WAF block; None = timeout or connection error.
    Note 429 (rate limit) and 402 (frozen store) are deliberately NOT escalated
    — they aren't fingerprint problems, so a stronger tier won't help.
    """
    return status is None or status == 403


def fetch_tier0(session, url):
    """Plain requests GET. Returns (status, text, headers); status None on error."""
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        return r.status_code, r.text, r.headers
    except requests.exceptions.RequestException:
        return None, None, None


def fetch_tier1(url):
    """curl_cffi GET impersonating Chrome's TLS/HTTP2 fingerprint."""
    try:
        r = cffi_requests.get(
            url, impersonate="chrome", timeout=TIER1_TIMEOUT, allow_redirects=True
        )
        return r.status_code, r.text, r.headers
    except Exception:
        return None, None, None


def fetch_tier2(url):
    """Tier 2 — real browser for the Akamai-backed holdouts.

    NOT YET WIRED. Intended to route only Tier 1 failures through nodriver,
    falling back to Camoufox for the last stubborn few (luxury cluster), both
    behind residential proxies. Returns 'not implemented' for now.
    """
    return None, None, None


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
    """Fetch each site over HTTP with a reused session, return name -> platform dict."""
    results = {}
    total = len(sites)
    status_counts = Counter()
    platform_counts = Counter()
    run_start = time.monotonic()
    print(f"Starting platform detection for {total} site(s)...")
    with requests.Session() as session:
        session.headers.update(REQUEST_HEADERS)
        for index, site in enumerate(sites, start=1):
            name = site.get('name') or site.get('url') or 'unidentified'
            url = site.get('url')
            if not url:
                print(f"[WARN] Site entry missing 'url': {site}")
                continue

            # Tier 0: plain fetch. Escalate to Tier 1 only if it looks blocked.
            tier = 0
            site_start = time.monotonic()
            status, text, headers = fetch_tier0(session, url)
            if _is_blocked(status):
                tier = 1
                status, text, headers = fetch_tier1(url)
            elapsed = time.monotonic() - site_start

            if text is None:
                status_counts['unreachable'] += 1
                print(f"[{index}/{total}] [WARN] {name} -> {url}  =>  "
                      f"unreachable (T{tier}, {elapsed:.2f}s)")
                continue

            platform = detect_platform_from_text(text, headers, url)
            status_counts[status] += 1
            platform_counts[platform] += 1
            print(f"[{index}/{total}] (T{tier}) {name} -> {url}  =>  "
                  f"[{status}] {platform} ({elapsed:.2f}s)")
            results[name] = platform

    total_elapsed = time.monotonic() - run_start
    print_summary(total, status_counts, platform_counts, total_elapsed)
    return results


def _format_counts(counts, total):
    """Yield 'label: count (pct%)' lines, most frequent first."""
    for label, count in counts.most_common():
        pct = (count / total * 100) if total else 0
        yield f"  {str(label):<28} {count:>4}  ({pct:5.1f}%)"


def print_summary(total, status_counts, platform_counts, total_elapsed):
    """Print response-code and platform breakdowns plus total execution time."""
    print("\n" + "=" * 48)
    print("SUMMARY")
    print("=" * 48)
    print(f"Sites processed: {total}")

    print("\nBy response status:")
    for line in _format_counts(status_counts, total):
        print(line)

    print("\nBy platform:")
    for line in _format_counts(platform_counts, total):
        print(line)

    mins, secs = divmod(total_elapsed, 60)
    print(f"\nTotal execution time: {total_elapsed:.1f}s ({int(mins)}m {secs:04.1f}s)")
    print("=" * 48)


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
