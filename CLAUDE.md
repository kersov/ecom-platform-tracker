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

```bash
pip install -r requirements.txt
python detect_platform.py   # Run platform detection against sites.json
python clean_stores.py      # Deduplicate and sort sites.json
```

### Docker

```bash
npm run docker:build   # Build Docker image
npm run docker:run     # Run detection in container
```

## Architecture

### Data Flow

1. `sites.json` — list of ~260 brands with name, URL, category
2. `detect_platform.py` — Playwright-based scraper; detects platform via heuristic HTML/header matching; writes to `data.json` only if platform changed
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

`detect_platform.py` searches HTML and HTTP headers for platform-specific signatures (e.g., `cdn.shopify.com` for Shopify, `wp-content/plugins/woocommerce` for WooCommerce). Returns `"Unidentified"` if no match. Playwright timeout is 15 seconds per site.