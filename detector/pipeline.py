"""Two-phase concurrent detection pipeline + CLI entry point.

Phase A runs the HTTP tiers (0->1) across all sites in a thread pool; Phase B runs
the Tier 2 browser over the flagged tail with bounded tab concurrency; a serial
merge folds Tier 2 in, applies the SPA fallback, and records results under the
skip rules. `main()` wires sites.json -> pipeline -> data.json history.
"""
import json
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

from .browser import close_tier2, run_tier2_batch
from .config import (
    DATA_FILE,
    HTTP_WORKERS,
    PROXIES,
    REQUEST_HEADERS,
    SITES_FILE,
    TIER2_CONCURRENCY,
)
from .detection import (
    _looks_blocked,
    _needs_render,
    detect_platform_from_spa_state,
    detect_platform_from_text,
)
from .fetchers import fetch_tier0, fetch_tier1


def fetch_http_tiers(session, url):
    """HTTP-only slice of the escalation ladder (Tier 0 -> Tier 1).

    Runs Tier 0, escalates to Tier 1 only when the result looks blocked, and stops
    as soon as a platform is identified. Returns ``(best, needs_tier2)`` where:
      * ``best`` = ``(tier, status, text, headers, platform)`` — the most
        informative response seen (a tier yielding text is preferred over a later
        tier that returns nothing), mirroring the old escalation's "best" rule.
      * ``needs_tier2`` = True when still Unidentified but a real browser could
        plausibly help: the page looks blocked (403/anti-bot interstitial) or is
        client-side rendered / an empty shell. Tier 2 is run separately, batched.
    """
    best = None
    for tier, fetch in ((0, lambda: fetch_tier0(session, url)),
                        (1, lambda: fetch_tier1(url))):
        status, text, headers = fetch()
        platform = (detect_platform_from_text(text, headers, url)
                    if text is not None else 'Unidentified')
        if text is not None or best is None:
            best = (tier, status, text, headers, platform)
        if platform != 'Unidentified':
            return best, False
        # Only a block is worth a stronger *HTTP* fetch (Tier 1). A non-blocked
        # miss won't improve at Tier 1 — stop and let Tier 2 decide if it renders.
        if not _looks_blocked(status, text):
            break

    _, b_status, b_text, _, _ = best
    needs_tier2 = _looks_blocked(b_status, b_text) or (
        b_text is not None and _needs_render(b_text))
    return best, needs_tier2


def _apply_spa_fallback(best, url):
    """Last-tier SPA fallback on a still-Unidentified result: decode the page's
    embedded client-app state and retry detection — the platform often hides in
    escaped API/CDN URLs there. Returns best unchanged if it doesn't apply."""
    b_tier, b_status, b_text, b_headers, b_platform = best
    if b_platform == 'Unidentified' and b_text is not None:
        spa_platform = detect_platform_from_spa_state(b_text, b_headers, url)
        if spa_platform != 'Unidentified':
            return (b_tier, b_status, b_text, b_headers, spa_platform)
    return best


def fetch_all_sites(sites):
    """Detect each site's platform via a two-phase concurrent pipeline.

    Phase A — HTTP tiers 0->1 for every site in a thread pool.
    Phase B — Tier 2 browser (bounded concurrent tabs) for the sites Phase A
              flagged as browser-worthy.
    Merge   — serial: fold Tier 2 into each result, apply the SPA fallback, then
              the skip/record rules. Returns name -> platform for recorded sites.

    Only *scheduling* differs from the old serial escalation; detection semantics
    (tier ladder, "most informative response" rule, SPA fallback, skip rules) are
    unchanged.
    """
    results = {}
    total = len(sites)
    status_counts = Counter()
    platform_counts = Counter()
    skipped = 0
    run_start = time.monotonic()
    proxy_state = "on (Tier 1+)" if PROXIES else "off (direct)"
    print(f"Starting platform detection for {total} site(s)... "
          f"[proxy: {proxy_state} | http_workers: {HTTP_WORKERS} | "
          f"tier2_concurrency: {TIER2_CONCURRENCY}]")

    # Drop entries with no URL up front.
    valid = []
    for site in sites:
        name = site.get('name') or site.get('url') or 'unidentified'
        url = site.get('url')
        if not url:
            print(f"[WARN] Site entry missing 'url': {site}")
            continue
        valid.append((name, url))

    # ---- Phase A: HTTP tiers 0->1, concurrent (one requests.Session per thread,
    # since Session isn't reliably thread-safe) ----
    _local = threading.local()

    def _session():
        s = getattr(_local, 'session', None)
        if s is None:
            s = requests.Session()
            s.headers.update(REQUEST_HEADERS)
            _local.session = s
        return s

    def _phase_a(item):
        _name, url = item
        try:
            best, needs_tier2 = fetch_http_tiers(_session(), url)
        except Exception:  # noqa: BLE001 — one bad site must not kill the pool
            best, needs_tier2 = (0, None, None, None, 'Unidentified'), False
        return url, best, needs_tier2

    http_best = {}
    t2_urls, t2_seen = [], set()
    try:
        with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as ex:
            for url, best, needs_tier2 in ex.map(_phase_a, valid):
                http_best[url] = best
                if needs_tier2 and url not in t2_seen:
                    t2_seen.add(url)
                    t2_urls.append(url)
        print(f"  HTTP tiers done: {len(valid)} sites in "
              f"{time.monotonic() - run_start:.1f}s; {len(t2_urls)} -> Tier 2")

        # ---- Phase B: Tier 2 browser, bounded concurrency ----
        t2_start = time.monotonic()
        t2_html = run_tier2_batch(t2_urls)
        if t2_urls:
            print(f"  Tier 2 done: {len(t2_urls)} sites in "
                  f"{time.monotonic() - t2_start:.1f}s")
    finally:
        # Always tear down the shared Tier 2 browser, even on error/interrupt.
        close_tier2()

    # ---- Merge + record (serial; skip/detection semantics unchanged) ----
    for index, (name, url) in enumerate(valid, start=1):
        best = http_best.get(url, (0, None, None, None, 'Unidentified'))
        # Fold in Tier 2 when Phase A was still Unidentified and the browser
        # returned something (the render is the later, most-informative tier). If
        # Tier 2 returned nothing, keep Phase A's best text.
        if best[4] == 'Unidentified':
            html2 = t2_html.get(url)
            if html2 is not None:
                best = (2, 200, html2, None,
                        detect_platform_from_text(html2, None, url))
        best = _apply_spa_fallback(best, url)
        tier, status, text, _, platform = best

        if text is None:
            # Unreachable even on the last tier: skip — never record 'Unidentified'
            # just because we couldn't fetch it.
            status_counts['unreachable'] += 1
            skipped += 1
            print(f"[{index}/{total}] [WARN] {name} -> {url}  =>  "
                  f"unreachable — skipped (T{tier})")
            continue

        status_counts[status] += 1

        # Don't record an 'Unidentified' that isn't a genuine storefront miss. Skip
        # it — leaving the brand's known history untouched — when the final response
        # is a non-2xx (3xx/4xx/5xx) or a detected anti-bot interstitial even at 200
        # (a WAF can launder a 403 into a 200 challenge page at the browser tier;
        # _looks_blocked recognizes these). A plain 2xx page we just don't recognize
        # is a real miss and is still recorded as 'Unidentified'.
        if platform == 'Unidentified' and (
                not (status is not None and 200 <= status < 300)
                or _looks_blocked(status, text)):
            skipped += 1
            reason = ('non-2xx'
                      if not (status is not None and 200 <= status < 300)
                      else 'blocked')
            print(f"[{index}/{total}] (T{tier}) {name} -> {url}  =>  "
                  f"[{status}] Unidentified — skipped ({reason})")
            continue

        platform_counts[platform] += 1
        print(f"[{index}/{total}] (T{tier}) {name} -> {url}  =>  [{status}] {platform}")
        results[name] = platform

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
