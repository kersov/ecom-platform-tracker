"""Tier 2 — a shared headless Chrome (nodriver) for the JS-sensor holdouts.

One browser is started lazily and reused across the whole blocked tail; URLs are
fetched with bounded tab concurrency (run_tier2_batch). If Chrome can't start the
tier disables itself and the run degrades gracefully. All the browser lifecycle
state lives here so the globals and the code that mutates them stay together.
"""
import asyncio
import sys
import time
from urllib.parse import urlparse

import nodriver as uc

from .config import (
    CHROME_PATH,
    PROXY_URL,
    TIER2_CONCURRENCY,
    TIER2_POLL,
    TIER2_SETTLE,
    TIER2_SETTLE_MAX,
    TIER2_TIMEOUT,
)
from .detection import _looks_blocked, detect_platform_from_text

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


async def _tier2_bounded(browser, sem, url):
    """One Tier 2 fetch under the concurrency semaphore, hard-capped per tab so a
    single stuck page can't stall the whole gather. Returns html or None."""
    async with sem:
        try:
            return await asyncio.wait_for(_tier2_fetch(browser, url), TIER2_TIMEOUT)
        except Exception:
            return None


async def _tier2_gather(browser, urls):
    sem = asyncio.Semaphore(TIER2_CONCURRENCY)
    htmls = await asyncio.gather(*(_tier2_bounded(browser, sem, u) for u in urls))
    return dict(zip(urls, htmls, strict=False))


def run_tier2_batch(urls):
    """Fetch many URLs through the shared Tier 2 browser with bounded tab
    concurrency. Returns ``{url: html or None}``.

    Starts the browser once (same retry + graceful-degrade as fetch_tier2); if it
    can't start, disables Tier 2 and returns all-None so the run still completes.
    Concurrency is capped by TIER2_CONCURRENCY (one nodriver tab per in-flight URL,
    cooperatively scheduled on the shared _tier2_loop).
    """
    global _tier2_loop, _tier2_browser, _tier2_disabled
    if not urls or _tier2_disabled:
        return {u: None for u in urls}
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
        return _tier2_loop.run_until_complete(_tier2_gather(_tier2_browser, urls))
    except Exception as e:
        # Browser never came up: disable Tier 2 for the rest of the run rather than
        # failing every URL individually.
        if _tier2_browser is None:
            _tier2_disabled = True
            print(f"[WARN] Tier 2 (nodriver) unavailable, disabling: {str(e)[:140]}")
        return {u: None for u in urls}


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
