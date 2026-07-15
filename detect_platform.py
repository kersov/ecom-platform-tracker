#!/usr/bin/env python3
"""Entry point for e-commerce platform detection.

- Reads sites.json
- Fetches each site with a tiered strategy (Tier 0 `requests` -> Tier 1 `curl_cffi`
  Chrome impersonation -> Tier 2 headless Chrome via nodriver), detecting the
  platform from HTML/header signatures
- Writes results into data.json (only when a brand's platform changed)

All logic now lives in the `detector/` package, split by concern:
  detector.config     — timeouts, proxy, concurrency, paths, headers
  detector.detection  — pure signature/heuristic matching
  detector.fetchers   — Tier 0/1 HTTP fetchers
  detector.browser    — Tier 2 nodriver machinery
  detector.pipeline   — two-phase concurrent orchestration + main()

This file is kept as the entry point so `python detect_platform.py` — the Docker
CMD, the CI job, and local runs — keeps working unchanged. `python -m detector`
works too.
"""
from detector.pipeline import main

if __name__ == '__main__':
    main()
