"""Tier 0 and Tier 1 HTTP fetchers.

Tier 0 is a plain `requests` GET; Tier 1 retries with `curl_cffi` Chrome TLS/HTTP2
impersonation (and the residential proxy, when configured) to beat fingerprint and
IP-reputation blocks. Both return ``(status, text, headers)`` with ``status`` None
on any error, so callers never have to catch.
"""
import requests
from curl_cffi import requests as cffi_requests

from .config import CONNECT_TIMEOUT, PROXIES, TIER1_TIMEOUT, TIMEOUT


def fetch_tier0(session, url):
    """Plain requests GET. Returns (status, text, headers); status None on error."""
    try:
        r = session.get(url, timeout=(CONNECT_TIMEOUT, TIMEOUT), allow_redirects=True)
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
