"""Operational configuration for the platform detector.

Fetch timeouts, HTTP headers, input/output paths, and the env-tunable knobs
(proxy, concurrency). Pure constants — the only side effect is reading env vars.
"""
import os

# Repo root is the parent of this package directory, so sites.json / data.json
# resolve next to detect_platform.py regardless of how the entry point is invoked.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITES_FILE = os.path.join(ROOT, 'sites.json')
DATA_FILE = os.path.join(ROOT, 'data.json')

TIMEOUT = 15          # Tier 0 (plain requests) — read timeout
CONNECT_TIMEOUT = 6   # Tier 0 — connect timeout, so dead hosts fail fast
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

# Concurrency. The HTTP tiers (0/1) run across sites in a thread pool; the Tier 2
# browser drives a bounded number of tabs at once. Every brand is a distinct
# domain hit exactly once, so parallelism causes no single-host hammering. Both
# are env-tunable (dial down if a flaky local network shows instant-failure
# bursts, or dial Tier 2 down if concurrent Chrome tabs get unstable).
HTTP_WORKERS = int(os.environ.get("HTTP_WORKERS") or 24)
TIER2_CONCURRENCY = int(os.environ.get("TIER2_CONCURRENCY") or 6)

# Chrome/Chromium binary for the Tier 2 browser. nodriver auto-detects a system
# Chrome when unset (fine on dev machines); the Docker image sets this to the
# Chromium it installs.
CHROME_PATH = os.environ.get("CHROME_PATH") or None
