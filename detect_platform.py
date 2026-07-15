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
import asyncio
import html
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

import nodriver as uc
import requests
from curl_cffi import requests as cffi_requests

ROOT = os.path.dirname(os.path.abspath(__file__))
SITES_FILE = os.path.join(ROOT, 'sites.json')
DATA_FILE = os.path.join(ROOT, 'data.json')

TIMEOUT = 15          # Tier 0 (plain requests)
TIER1_TIMEOUT = 20    # Tier 1 (curl_cffi impersonation)
TIER2_TIMEOUT = 45    # Tier 2 (nodriver browser) — hard cap per site
TIER2_SETTLE = 4      # initial grace for anti-bot sensor JS / auto-submit
TIER2_SETTLE_MAX = 15 # hard cap on the adaptive settle wait (two of these + a
                      # reload must stay under TIER2_TIMEOUT)
TIER2_POLL = 1.5      # re-check the DOM this often while waiting for a SPA

# A browser-like UA reduces trivial bot blocks on a plain HTTP fetch.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Residential proxy for the escalation tier(s). Many targets (luxury especially)
# block on datacenter IP reputation — and CI runners (GitHub Actions) sit on
# pre-flagged datacenter ranges — so a clean residential IP flips a lot of the
# 403/"Access Denied" tail back to 200.
#
# Set SCRAPER_PROXY to a full proxy URL, e.g.
#   http://user:pass@host:port   or   socks5://user:pass@host:port
# In CI, store it as a GitHub Actions secret and expose it as an env var — never
# commit the address. Tier 0 stays DIRECT on purpose: residential proxies bill
# per GB and full storefront pages are 1-3 MB each, so only the escalated retries
# (Tier 1+, i.e. the ~30-70 blocked sites) are worth routing through the proxy.
PROXY_URL = os.environ.get("SCRAPER_PROXY") or None
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

# Chrome/Chromium binary for the Tier 2 browser. nodriver auto-detects a system
# Chrome when unset (fine on dev machines); the Docker image sets this to the
# Chromium it installs.
CHROME_PATH = os.environ.get("CHROME_PATH") or None


# High-precision fingerprints of anti-bot interstitial / block pages that come
# back with a normal-looking body (often HTTP 200) but contain no storefront
# markup — so the detector sees them as "Unidentified". Kept tight on purpose:
# a genuine storefront that merely *embeds* a bot-manager script must NOT match,
# so these strings only appear on the actual challenge/deny pages themselves.
CHALLENGE_SIGNATURES = (
    "errors.edgesuite.net",            # Akamai "Access Denied" reference page
    "you don't have permission to access",
    "<title>access denied",            # Akamai deny page title
    "istlwashere",                     # Akamai Bot Manager sensor interstitial
    "cdn-cgi/challenge-platform",      # Cloudflare managed challenge / Turnstile
    "attention required! | cloudflare",
    "just a moment...</title>",        # Cloudflare interstitial
    "captcha-delivery.com",            # DataDome
    "perimeterx.com/whywasiblocked",   # PerimeterX / HUMAN block page
    "px-captcha",
)


def _looks_blocked(status, text):
    """A result worth escalating to a stronger fetch tier.

    Escalate on:
      * status None  — timeout / connection error
      * status 403   — likely bot/WAF forbidden
      * HTTP 200 whose body is actually an anti-bot interstitial: it carries a
        known challenge fingerprint or is an implausibly small stub. These come
        back 200 today and were silently recorded as 'Unidentified'.

    Deliberately NOT escalated: 429 (rate limit) and 402 (frozen store) — those
    aren't fingerprint problems, so a stronger tier won't help. The caller only
    consults this once detection has already failed, so a confidently identified
    storefront is never re-fetched even if it embeds a bot-manager script.
    """
    if status is None or status == 403:
        return True
    if status != 200:
        return False
    if not text:
        return True
    t = text.lower()
    if any(sig in t for sig in CHALLENGE_SIGNATURES):
        return True
    # A real storefront home page is large; a bare challenge/redirect stub is not.
    return len(text) < 1000


# Markers that a 200 body is client-side rendered — the storefront markup (and
# thus the platform signature) is built by JavaScript and simply isn't in the
# HTTP response. These are the single largest cause of "Unidentified": the HTTP
# tiers can't see the DOM, but the Tier 2 browser can. Kept precise so a normal
# server-rendered page isn't needlessly sent to the (slow) browser.
SPA_MARKERS = (
    "__next_data__", 'id="__next"',                     # Next.js
    "window.__nuxt__", 'id="__nuxt"',                   # Nuxt
    "__remixcontext",                                    # Remix
    "data-reactroot", 'id="react-root"', 'id="root"><script',  # React mounts
    "ng-version=",                                       # Angular
    "data-server-rendered", "data-v-",                  # Vue
    "svelte-",                                           # Svelte
    "__initial_state__", "__apollo_state__", "__preloaded_state__",
)


def _needs_render(text):
    """True when a 200 body should be retried in the Tier 2 browser because it's
    client-side rendered or an empty shell.

    Only consulted for an already-Unidentified 200 that does NOT look blocked, so
    a confidently detected or plainly custom server-rendered page is never sent
    to the browser. Detects known SPA frameworks, or a tiny titleless shell (a JS
    bootstrap / stealth stub) that carries no real page content.
    """
    if not text:
        return False
    t = text.lower()
    if any(m in t for m in SPA_MARKERS):
        return True
    return len(text) < 3500 and "<title" not in t


def fetch_tier0(session, url):
    """Plain requests GET. Returns (status, text, headers); status None on error."""
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        return r.status_code, r.text, r.headers
    except requests.exceptions.RequestException:
        return None, None, None


def fetch_tier1(url):
    """curl_cffi GET impersonating Chrome's TLS/HTTP2 fingerprint.

    Routed through SCRAPER_PROXY when set — this is the tier that retries the
    IP-reputation-blocked tail, so a residential IP here is the highest-leverage
    fix for CI runs. Falls back to a direct connection when no proxy is set.
    """
    try:
        r = cffi_requests.get(
            url, impersonate="chrome", timeout=TIER1_TIMEOUT,
            allow_redirects=True, proxies=PROXIES,
        )
        return r.status_code, r.text, r.headers
    except Exception:
        return None, None, None


# Tier 2 shares one headless Chrome (via nodriver) across the whole blocked tail
# so we pay browser startup once, not per site — this is what makes it usable
# where the old per-run SeleniumBase setup was slow. Lazily started on first use.
_tier2_loop = None
_tier2_browser = None
_tier2_disabled = False   # set if Chrome can't start (e.g. missing in the image)
_tier2_hook_installed = False

_default_unraisablehook = sys.unraisablehook


def _quiet_loop_closed_at_gc(unraisable):
    """Swallow the one harmless teardown artifact nodriver leaves behind.

    nodriver terminates Chrome without fully tearing down its asyncio subprocess
    transport, so after a run the transport can be garbage-collected *after* our
    event loop has already closed — CPython then reports a RuntimeError('Event
    loop is closed') from BaseSubprocessTransport.__del__. It is purely cosmetic:
    the run has finished and data.json is already written. We drop exactly that
    case (via sys.unraisablehook, CPython's channel for __del__ exceptions) and
    defer everything else to the normal hook so real errors still surface.
    """
    exc = unraisable.exc_value
    if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
        return
    _default_unraisablehook(unraisable)


def _install_tier2_unraisablehook():
    """Install the teardown-noise filter once, only when Tier 2 is actually used."""
    global _tier2_hook_installed
    if not _tier2_hook_installed:
        sys.unraisablehook = _quiet_loop_closed_at_gc
        _tier2_hook_installed = True


def _tier2_proxy_arg():
    """`--proxy-server` for Tier 2, but only for a credential-free proxy.

    Chrome's --proxy-server can't carry user:pass, and answering a proxy auth
    prompt needs a CDP Fetch handler; without it the browser would hang. So we
    only route Tier 2 through an IP-whitelisted proxy. An authenticated proxy
    still protects Tier 1 (curl_cffi handles auth natively) — Tier 2 just runs
    direct, which is fine since its job is executing the JS sensor challenge.
    TODO: add a cdp.fetch AuthRequired handler to proxy authenticated Tier 2 too.
    """
    if not PROXY_URL:
        return None
    p = urlparse(PROXY_URL)
    if p.username or p.password or not p.hostname or not p.port:
        return None
    return f"--proxy-server={p.hostname}:{p.port}"


async def _tier2_start():
    # Use the modern `--headless=new` flag explicitly rather than nodriver's
    # headless=True: the latter injects the legacy `--headless`, which fails to
    # attach on current Chrome (macOS especially). `--headless=new` is portable
    # across macOS dev and the Linux CI container.
    args = [
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--blink-settings=imagesEnabled=false",  # skip images: faster, lighter
    ]
    proxy_arg = _tier2_proxy_arg()
    if proxy_arg:
        args.append(proxy_arg)
    kwargs = {}
    if CHROME_PATH:
        kwargs["browser_executable_path"] = CHROME_PATH
    return await uc.start(headless=False, sandbox=False, browser_args=args, **kwargs)


async def _tier2_settle(tab):
    """Adaptively wait for a client-rendered page to finish rendering.

    A blind fixed sleep is the main cause of Tier 2 flip-flop: a SPA that hasn't
    hydrated yet yields a bare shell (Unidentified) on one run and the full page
    on the next. Instead we give the sensor/hydration JS an initial grace period,
    then poll the live DOM until either (a) a platform signature appears, or (b)
    the content size stops growing (render settled) — capped at TIER2_SETTLE_MAX.
    Returns the most complete HTML observed, so a late shrink never loses content.
    """
    await tab.sleep(TIER2_SETTLE)
    html = await tab.get_content() or ''
    if detect_platform_from_text(html, None, None) != 'Unidentified':
        return html
    best = html
    last_len = len(html)
    stable = 0
    waited = TIER2_SETTLE
    while waited < TIER2_SETTLE_MAX:
        await tab.sleep(TIER2_POLL)
        waited += TIER2_POLL
        cur = await tab.get_content() or ''
        if len(cur) >= len(best):
            best = cur                       # keep the most complete render
        if detect_platform_from_text(cur, None, None) != 'Unidentified':
            return cur                       # fingerprintable — stop early
        if abs(len(cur) - last_len) < 256:   # DOM stopped changing
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last_len = len(cur)
    return best


async def _tier2_fetch(browser, url):
    tab = await browser.get(url, new_tab=True)
    try:
        html = await _tier2_settle(tab)
        # Anti-bot pages typically set a clearance cookie via JS then auto-reload
        # to the real page. If we still see a challenge, give it one more cycle.
        if _looks_blocked(200, html):
            await tab.reload()
            html = await _tier2_settle(tab)
        return html
    finally:
        await tab.close()


def fetch_tier2(url):
    """Tier 2 — real browser (nodriver) for the JS-sensor holdouts.

    Runs the page's anti-bot JavaScript in headless Chrome so Akamai/Cloudflare/
    DataDome sensor challenges resolve to the real storefront, which the HTTP
    tiers can't do. Reuses one shared browser. Returns (status, text, headers);
    status is synthesized (200 when HTML comes back) because CDP navigation
    doesn't surface it cleanly and this is the terminal tier.
    """
    global _tier2_loop, _tier2_browser, _tier2_disabled
    if _tier2_disabled:
        return None, None, None
    try:
        if _tier2_loop is None:
            _install_tier2_unraisablehook()
            _tier2_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_tier2_loop)
        if _tier2_browser is None:
            # Chrome's CDP attach can race on startup; retry a couple of times
            # before giving up on the whole tier.
            last_err = None
            for _ in range(3):
                try:
                    _tier2_browser = _tier2_loop.run_until_complete(_tier2_start())
                    break
                except Exception as e:  # noqa: BLE001 — retry any startup failure
                    last_err = e
                    time.sleep(2)
            if _tier2_browser is None:
                raise last_err
        html = _tier2_loop.run_until_complete(
            asyncio.wait_for(_tier2_fetch(_tier2_browser, url), TIER2_TIMEOUT)
        )
        return (200 if html else None), html, None
    except Exception as e:
        # If the browser itself never came up, stop trying it for every remaining
        # site — degrade gracefully to "Tier 2 unavailable" for the rest of the run.
        if _tier2_browser is None:
            _tier2_disabled = True
            print(f"[WARN] Tier 2 (nodriver) unavailable, disabling: {str(e)[:140]}")
        return None, None, None


def close_tier2():
    """Shut down the shared Tier 2 browser + event loop, if they were started.

    nodriver's Browser.stop() *schedules* connection.aclose() as a task and
    terminates Chrome without awaiting either, so a naive close leaks a
    "coroutine was never awaited" warning plus an "Event loop is closed" error
    when the dead subprocess transport is GC'd. To avoid both we await aclose()
    ourselves, then await the Chrome process actually exiting so its asyncio
    subprocess transport is torn down while the loop is still open (a fixed sleep
    isn't enough — Chrome can take a second or two to die after SIGTERM), then
    cancel the remaining infinite tasks (keepalive/listener).
    """
    global _tier2_loop, _tier2_browser
    if _tier2_loop is None:
        return
    try:
        if _tier2_browser is not None:
            # Grab the process handle before stop() clears it.
            proc = getattr(_tier2_browser, "_process", None)
            try:
                _tier2_loop.run_until_complete(_tier2_browser.aclose())
            except Exception:
                pass
            _tier2_browser.stop()  # SIGTERM to the Chrome process
            if proc is not None:
                try:
                    _tier2_loop.run_until_complete(asyncio.wait_for(proc.wait(), 8))
                except Exception:
                    pass
        pending = [t for t in asyncio.all_tasks(_tier2_loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            _tier2_loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        _tier2_loop.run_until_complete(_tier2_loop.shutdown_asyncgens())
    except Exception:
        pass
    finally:
        try:
            _tier2_loop.close()
        except Exception:
            pass
        _tier2_browser = None
        _tier2_loop = None


def fetch_with_escalation(session, url):
    """Fetch a URL, climbing fetch tiers until a platform is identified.

    Escalation rules, only ever applied to an Unidentified result:
      * looks blocked (403 / timeout / anti-bot interstitial) -> next tier up,
        since a stronger *fetch* may beat the block (0 -> 1 -> 2).
      * client-side rendered / empty shell -> jump straight to Tier 2, since only
        a real browser can build the DOM (a curl_cffi hop would waste a fetch).
      * otherwise -> stop; it's a genuine miss no stronger tier will fix.

    Returns (tier, status, text, headers, platform). Keeps the most informative
    response seen: a tier that yields text (e.g. a 403 page we can still read) is
    preferred over a later tier that returns nothing (e.g. Tier 2 with no browser
    available), so escalation never discards a usable earlier result.
    """
    fetchers = (
        lambda: fetch_tier0(session, url),   # 0
        lambda: fetch_tier1(url),            # 1
        lambda: fetch_tier2(url),            # 2
    )
    best = None
    tier = 0
    while tier < len(fetchers):
        status, text, headers = fetchers[tier]()
        platform = (detect_platform_from_text(text, headers, url)
                    if text is not None else 'Unidentified')
        if text is not None or best is None:
            best = (tier, status, text, headers, platform)
        if platform != 'Unidentified':
            break
        if _looks_blocked(status, text):
            tier += 1
        elif _needs_render(text) and tier < 2:
            tier = 2                          # only the browser can render this
        else:
            break

    # Last-tier SPA fallback: we've exhausted the fetch ladder still Unidentified.
    # If the final page is a client-side app, decode its embedded state and try
    # once more — the platform often hides in escaped API/CDN URLs there.
    b_tier, b_status, b_text, b_headers, b_platform = best
    if b_platform == 'Unidentified' and b_text is not None:
        spa_platform = detect_platform_from_spa_state(b_text, b_headers, url)
        if spa_platform != 'Unidentified':
            best = (b_tier, b_status, b_text, b_headers, spa_platform)
    return best


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
    if ('cdn.shopify.com' in text or '.myshopify.com' in text
            or 'Shopify.theme' in html_text_orig or 'content="Shopify"' in text
            or 'x-shopify-' in hdr_keys or 'x-shopify-' in hdr_vals):
        return 'Shopify'
    # WooCommerce / WordPress e-commerce plugin patterns
    if ('woocommerce' in text or '/wp-content/plugins/woocommerce' in text
            or 'woocommerce' in hdr_keys or 'woocommerce' in hdr_vals):
        return 'WooCommerce'
    # Magento / Adobe Commerce
    if 'mage.js' in text or 'var mage' in text or 'magento' in text or '/skin/frontend/' in text:
        return 'Magento'
    # Salesforce Commerce Cloud (Demandware)
    if ('demandware' in text or 'bmcdn.net' in text or 'salesforce' in text
            or 'sfcc' in text or 'dwstatic' in text):
        return 'Salesforce Commerce Cloud'
    # SAP Commerce Cloud (Hybris / Spartacus / OCC)
    if ('hybris' in text or 'yaccelerator' in text or 'spartacus' in text
            or '/occ/v' in text or '/rest/v' in text or 'sap-commerce' in text
            or 'sap commerce' in text):
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


def _decode_escaped(text):
    """Normalize JSON/HTML escaping so escaped platform signatures become matchable.

    SPA state blobs (Next.js `__NEXT_DATA__`, Nuxt, Apollo, ...) embed URLs with
    escaped slashes (``\\/on\\/demandware``, ``cdn\\u002fshopify``) and HTML
    entities, so a signature like ``/skin/frontend/`` or ``.myshopify.com`` is
    present but hidden from the raw-text detector. Decoding the common escapes
    surfaces it. This only *normalizes* bytes already in the payload — it can
    reveal a signature that was there, never fabricate one.
    """
    if not text:
        return text
    decoded = text.replace('\\/', '/')
    decoded = re.sub(r'\\u([0-9a-fA-F]{4})',
                     lambda m: chr(int(m.group(1), 16)), decoded)
    return html.unescape(decoded)


def detect_platform_from_spa_state(text, headers, url):
    """Last-tier fallback for client-side-rendered pages.

    When a page carries SPA state (see SPA_MARKERS) but nothing matched in its raw
    form, decode the embedded state and re-run the signature detector over it: the
    backend platform (Shopify Hydrogen, SFCC PWA Kit, commercetools, ...) commonly
    leaks through escaped API/CDN URLs inside that state even when the visible DOM
    carries no marker. Returns a platform name or 'Unidentified'. A page with no
    SPA state is left untouched so server-rendered pages are never affected.
    """
    if not text:
        return 'Unidentified'
    if not any(m in text.lower() for m in SPA_MARKERS):
        return 'Unidentified'
    return detect_platform_from_text(_decode_escaped(text), headers, url)


# -------------------------
# Fetcher
# -------------------------
def fetch_all_sites(sites):
    """Fetch each site over HTTP with a reused session, return name -> platform dict."""
    results = {}
    total = len(sites)
    status_counts = Counter()
    platform_counts = Counter()
    skipped = 0
    run_start = time.monotonic()
    proxy_state = "on (Tier 1+)" if PROXIES else "off (direct)"
    print(f"Starting platform detection for {total} site(s)... [proxy: {proxy_state}]")
    try:
        with requests.Session() as session:
            session.headers.update(REQUEST_HEADERS)
            for index, site in enumerate(sites, start=1):
                name = site.get('name') or site.get('url') or 'unidentified'
                url = site.get('url')
                if not url:
                    print(f"[WARN] Site entry missing 'url': {site}")
                    continue

                # Fetch with tier escalation: a 403 or a 200-but-blocked
                # interstitial both bump the site up to the next fetch tier.
                site_start = time.monotonic()
                tier, status, text, _, platform = fetch_with_escalation(session, url)
                elapsed = time.monotonic() - site_start

                if text is None:
                    # Unreachable even on the last tier: skip entirely — never
                    # record 'Unidentified' just because we couldn't fetch it.
                    status_counts['unreachable'] += 1
                    skipped += 1
                    print(f"[{index}/{total}] [WARN] {name} -> {url}  =>  "
                          f"unreachable — skipped (T{tier}, {elapsed:.2f}s)")
                    continue

                status_counts[status] += 1

                # Don't record an 'Unidentified' that isn't a genuine storefront
                # miss. Skip it — leaving the brand's known history untouched — when
                # the final response is either:
                #   * a non-2xx (3xx redirect / 4xx block / 5xx error), or
                #   * a detected anti-bot interstitial, even at HTTP 200: a WAF
                #     (e.g. Cloudflare "Just a moment...") can launder a 403 into a
                #     200 challenge page at the browser tier, which carries no
                #     storefront markup. _looks_blocked already recognizes these.
                # A plain 2xx page we simply don't recognize is a real miss and is
                # still recorded as 'Unidentified'.
                if platform == 'Unidentified' and (
                        not (status is not None and 200 <= status < 300)
                        or _looks_blocked(status, text)):
                    skipped += 1
                    reason = ('non-2xx'
                              if not (status is not None and 200 <= status < 300)
                              else 'blocked')
                    print(f"[{index}/{total}] (T{tier}) {name} -> {url}  =>  "
                          f"[{status}] Unidentified — skipped ({reason}) "
                          f"({elapsed:.2f}s)")
                    continue

                platform_counts[platform] += 1
                print(f"[{index}/{total}] (T{tier}) {name} -> {url}  =>  "
                      f"[{status}] {platform} ({elapsed:.2f}s)")
                results[name] = platform
    finally:
        # Always tear down the shared Tier 2 browser, even on error/interrupt.
        close_tier2()

    total_elapsed = time.monotonic() - run_start
    print_summary(total, status_counts, platform_counts, skipped, total_elapsed)
    return results


def _format_counts(counts, total):
    """Yield 'label: count (pct%)' lines, most frequent first."""
    for label, count in counts.most_common():
        pct = (count / total * 100) if total else 0
        yield f"  {str(label):<28} {count:>4}  ({pct:5.1f}%)"


def print_summary(total, status_counts, platform_counts, skipped, total_elapsed):
    """Print response-code and platform breakdowns plus total execution time."""
    print("\n" + "=" * 48)
    print("SUMMARY")
    print("=" * 48)
    print(f"Sites processed: {total}")
    print(f"Recorded: {sum(platform_counts.values())}   "
          f"Skipped (unreachable / non-2xx): {skipped}")

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
    with open(SITES_FILE, encoding='utf-8') as f:
        sites = json.load(f)

    data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding='utf-8') as f:
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
