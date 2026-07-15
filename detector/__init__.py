"""Platform detector package.

Split by concern: `config` (operational constants), `detection` (pure heuristics),
`fetchers` (Tier 0/1 HTTP), `browser` (Tier 2 nodriver), `pipeline` (orchestration
+ CLI). The commonly used entry points are re-exported here for convenience.
"""
from .browser import close_tier2, fetch_tier2, run_tier2_batch
from .config import DATA_FILE, SITES_FILE
from .detection import detect_platform_from_spa_state, detect_platform_from_text
from .fetchers import fetch_tier0, fetch_tier1
from .pipeline import fetch_all_sites, fetch_http_tiers, main, print_summary

__all__ = [
    "SITES_FILE",
    "DATA_FILE",
    "detect_platform_from_text",
    "detect_platform_from_spa_state",
    "fetch_tier0",
    "fetch_tier1",
    "fetch_tier2",
    "run_tier2_batch",
    "close_tier2",
    "fetch_http_tiers",
    "fetch_all_sites",
    "print_summary",
    "main",
]
