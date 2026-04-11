"""Shared constants and helpers used across CLI commands."""

from datetime import date as _date

# Single source of truth for halving date -- used by discord_bot, dashboard, digest
LAST_HALVING: _date = _date(2024, 4, 19)

# ---------------------------------------------------------------------------
# Sparplan allocation (Trade Republic, 0 fees)
# BTC: 8 EUR/week = 32/month, ETH: 2/week = 8/month
# SP500: 16/week = 64/month, SEMIS: 4/week = 16/month
# REALTY: 4/week = 16/month, URANIUM: 1/week = 4/month
# Total: 35 EUR/week = 140 EUR/month
# ---------------------------------------------------------------------------

SPARPLAN_MONTHLY = {
    "BTC":            32.0,
    "ETH":             8.0,
    "SP500":          64.0,
    "SEMICONDUCTORS": 16.0,
    "REALTY_INCOME":  16.0,
    "URANIUM":         4.0,
}
_SPARPLAN_TOTAL = sum(SPARPLAN_MONTHLY.values())  # 140 EUR

SPARPLAN_TARGETS = {k: v / _SPARPLAN_TOTAL * 100 for k, v in SPARPLAN_MONTHLY.items()}

_CRYPTO_ASSETS = {"BTC", "ETH"}


def detect_asset_class(asset_name: str) -> str:
    """Return 'crypto' for BTC/ETH, 'etf' for all other assets."""
    return "crypto" if asset_name.upper() in _CRYPTO_ASSETS else "etf"


_CYCLE_DAYS = 48 * 30.44  # ~4 years in days

def halving_cycle_info() -> dict:
    """Return current halving cycle phase info.

    Research3: fase mas debil es meses 18-24 post-halving (30d=-7.2% vs baseline).
    Halving abril 2024 -> zona de riesgo: octubre 2025 - abril 2026.

    Keys: months_elapsed, in_risk_zone, halving_date, cycle_pct, next_halving_year.
    """
    today = _date.today()
    days_elapsed = (today - LAST_HALVING).days
    months_elapsed = days_elapsed / 30.44
    cycle_pct = min(days_elapsed / _CYCLE_DAYS * 100, 100)
    in_risk_zone = 18 <= months_elapsed < 24
    return {
        "months_elapsed": months_elapsed,
        "in_risk_zone": in_risk_zone,
        "halving_date": "abril 2024",
        "halving_date_fmt": LAST_HALVING.strftime("%b %Y"),
        "cycle_pct": round(cycle_pct, 1),
        "next_halving_year": 2028,
    }
