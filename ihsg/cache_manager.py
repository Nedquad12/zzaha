"""
cache_manager.py — Manajemen cache terpusat untuk indikator eksternal.

Cache yang dikelola:
  MGN_CACHE  : margin volume (build_mgn_cache)
  BRK_CACHE  : BlackRock holdings (build_brk_cache)
  OWN_CACHE  : kepemilikan ritel Local ID + Foreign ID (build_own_cache)

Dipanggil oleh:
  - main.py  → saat startup (main()) dan saat admin reload (do_reload())
  - scorer.py → mengambil cache via get_*_cache()
"""

import logging

logger = logging.getLogger(__name__)

# ── Path default — sama dengan yang ada di masing-masing modul ────────────────
MARGIN_FOLDER     = "/home/ec2-user/database/margin"
BLACKROCK_FOLDER  = "/home/ec2-user/database/br/ind"
OWNERSHIP_FOLDER  = "/home/ec2-user/database/data"

# ── Storage cache di RAM ───────────────────────────────────────────────────────
_MGN_CACHE: dict = {}
_BRK_CACHE: dict = {}
_OWN_CACHE: dict = {}


# ── Getter (dipakai oleh scorer.py) ───────────────────────────────────────────

def get_mgn_cache() -> dict:
    return _MGN_CACHE

def get_brk_cache() -> dict:
    return _BRK_CACHE

def get_own_cache() -> dict:
    return _OWN_CACHE


# ── Builder utama (dipanggil dari main.py) ────────────────────────────────────

def build_all_external_caches(
    margin_folder:    str = MARGIN_FOLDER,
    blackrock_folder: str = BLACKROCK_FOLDER,
    ownership_folder: str = OWNERSHIP_FOLDER,
) -> str:
    """
    Bangun ketiga cache eksternal secara berurutan.
    Return string ringkasan untuk ditampilkan di pesan reload admin.
    """
    global _MGN_CACHE, _BRK_CACHE, _OWN_CACHE

    from indicators.mgn import build_mgn_cache
    from indicators.brk import build_brk_cache
    from indicators.own import build_own_cache

    _MGN_CACHE = build_mgn_cache(margin_folder)
    _BRK_CACHE = build_brk_cache(blackrock_folder)
    _OWN_CACHE = build_own_cache(ownership_folder)

    summary = (
        f"📦 External cache: "
        f"MGN={len(_MGN_CACHE)} "
        f"BRK={len(_BRK_CACHE)} "
        f"OWN={len(_OWN_CACHE)} ticker"
    )
    logger.info(summary)
    return summary
