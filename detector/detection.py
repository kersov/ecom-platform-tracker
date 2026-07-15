"""Pure platform-detection heuristics — no network, no I/O.

Signature matching over page text/headers (detect_platform_from_text), the SPA
state decode fallback, and the block/render signal helpers the fetch tiers use to
decide whether to escalate. Kept side-effect-free so it's trivially unit-testable.
"""
import html
import re

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
