# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Tracks and visualizes global e-commerce platform usage trends. A Python backend scrapes ~260 sites daily (via GitHub Actions + Docker) to detect which platform each runs (Shopify, WooCommerce, Magento, etc.), storing results in `data.json`. A React/TypeScript frontend on GitHub Pages visualizes the historical data.

## Commands

### Frontend

```bash
npm run dev        # Dev server at localhost:8080
npm run build      # Production build to dist/
npm run lint       # ESLint
npm run preview    # Preview production build locally
```

### Backend (Python)

Dependencies are declared in `pyproject.toml` and locked (with hashes for all
transitive deps) in `uv.lock`, managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # Create/update .venv from the lockfile
uv run python detect_platform.py # Run platform detection against sites.json
uv run python clean_stores.py    # Deduplicate and sort sites.json

# Changing dependencies: edit pyproject.toml, then refresh the lock:
uv lock                          # Re-resolve and update uv.lock
uv lock --check                  # CI/sanity: fail if lock is out of sync
```

### Docker

```bash
npm run docker:build   # Build Docker image
npm run docker:run     # Run detection in container
```

## Architecture

### Data Flow

1. `sites.json` — list of ~260 brands with name, URL, category
2. `detect_platform.py` — tiered scraper that escalates only when the cheaper tier is blocked or unrenderable: Tier 0 `requests` → Tier 1 `curl_cffi` Chrome impersonation (403s/timeouts) → Tier 2 headless Chrome via `nodriver` (JS/SPA rendering, anti-bot challenges). Detects platform via heuristic HTML/header matching, plus a last-tier SPA-state decode. Records a result only if the platform changed — and a **blocked** (anti-bot challenge, even at HTTP 200), **non-2xx**, or **unreachable** response is skipped rather than recorded as `Unidentified`, so a brand's known platform is never overwritten by a transient block.
3. `data.json` — nested structure: `brand → date → platform`
4. `src/lib/PlatformData.ts` — `PlatformDataModel` class parses `data.json`, precomputes ranked platform usage, exports a singleton
5. React components consume the singleton for rendering charts and stats

### Frontend Structure

- `src/pages/Index.tsx` — main dashboard (header, stats, charts, footer)
- `src/components/PlatformChart.tsx` — Recharts pie chart for market share
- `src/components/PlatformStats.tsx` — top-3 platform cards (gold/silver/bronze)
- `src/components/StatsCard.tsx` — reusable stat card with trend indicator
- `src/components/ui/` — shadcn/ui primitives (don't edit these directly)

### Routing

React Router with base path awareness: `/ecom-platform-tracker` in production, `/` in dev. Configured in `vite.config.ts`.

### CI/CD

- `.github/workflows/daily-docker.yml` — runs at 00:00 UTC; detects platforms and commits `data.json` to main
- `.github/workflows/deploy.yml` — manual trigger; builds React app and deploys to GitHub Pages

### Platform Detection Heuristics

`detect_platform.py` searches HTML and HTTP headers for platform-specific signatures (e.g., `cdn.shopify.com` for Shopify, `wp-content/plugins/woocommerce` for WooCommerce). A result is recorded as `"Unidentified"` **only for a genuine, reachable (2xx, non-challenge) page with no matching signature** — blocked/non-2xx/unreachable responses are skipped instead (see Data Flow), so `Unidentified` means "reachable but unrecognized," not "we couldn't fetch it."

Fetch tiers (escalated only on failure of an already-`Unidentified` result):

- **Tier 0** — `requests` (15s timeout).
- **Tier 1** — `curl_cffi` Chrome TLS/HTTP2 impersonation (20s); routed through the residential proxy in `SCRAPER_PROXY` when that env var is set.
- **Tier 2** — headless Chrome via `nodriver` (45s hard cap) for JS/SPA rendering and anti-bot challenges. Uses an **adaptive settle** (`_tier2_settle`) that polls the live DOM until a signature appears or rendering stabilizes, instead of a fixed sleep — this removes most run-to-run flip-flop on client-rendered sites.

**Anti-bot / blocked detection.** `_looks_blocked` flags challenge interstitials (Akamai, Cloudflare `cdn-cgi/challenge-platform` / "Just a moment...", DataDome, PerimeterX) and tiny stub bodies — used both to escalate tiers and to skip a would-be `Unidentified` when a WAF launders a 403 into a 200 challenge page.

**SPA-state decode.** On the last tier, embedded client-app state (`__NEXT_DATA__`, `__NUXT__`, `__APOLLO_STATE__`, …) is unescaped (`\/`, `\uXXXX`, HTML entities) and re-scanned, so signatures hidden behind JSON/HTML escaping still match. This only surfaces the **existing** platform set — it never invents a signature.