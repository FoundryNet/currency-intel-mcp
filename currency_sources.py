"""Exchange-rate sources — ECB via Frankfurter (primary, free, no key) with
open.er-api.com (exchangerate-api free, keyless) as the latest-only backup. All
rates are returned relative to the PIVOT base (EUR); cross-rates are derived
downstream. Every function returns plain data and never raises.

Frankfurter moved to https://api.frankfurter.dev/v1 (the old api.frankfurter.app
301-redirects there). It serves official ECB reference rates:
  GET /v1/latest?base=EUR                       → {"date","rates":{...}}
  GET /v1/{YYYY-MM-DD}?base=EUR                  → historical day (nearest prior)
  GET /v1/{start}..{end}?base=EUR&symbols=...    → time-series {"rates":{date:{...}}}
"""
from __future__ import annotations

import logging

import config
from http_util import request_json

logger = logging.getLogger("cur.sources")

FRANKFURTER = "https://api.frankfurter.dev/v1"
# Keyless backup (latest only): exchangerate-api.com open endpoint.
ERAPI = "https://open.er-api.com/v6/latest"


def _with_pivot(rates: dict) -> dict:
    out = {k: float(v) for k, v in rates.items() if v is not None}
    out[config.PIVOT] = 1.0
    return out


async def latest() -> dict:
    """Latest rates relative to PIVOT. Returns {"date": str, "rates": {quote: rate}}."""
    r = await request_json("GET", f"{FRANKFURTER}/latest",
                           params={"base": config.PIVOT}, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, dict) and isinstance(r.get("rates"), dict):
        return {"date": r.get("date"), "rates": _with_pivot(r["rates"])}
    # Backup: open.er-api.com (base=EUR), shape {rates, time_last_update_utc}.
    r = await request_json("GET", f"{ERAPI}/{config.PIVOT}", timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, dict) and isinstance(r.get("rates"), dict) and r.get("result") == "success":
        date = (r.get("time_last_update_utc") or "")[:16]
        return {"date": date or None, "rates": _with_pivot(r["rates"])}
    logger.warning(f"latest rates fetch failed: {r}")
    return {}


async def on_date(date_str: str) -> dict:
    """Rates on a specific date (ECB nearest-prior business day)."""
    r = await request_json("GET", f"{FRANKFURTER}/{date_str}",
                           params={"base": config.PIVOT}, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, dict) and isinstance(r.get("rates"), dict):
        return {"date": r.get("date"), "rates": _with_pivot(r["rates"])}
    return {}


async def series(start: str, end: str, symbols: list | None = None) -> dict:
    """Time-series of rates between two dates. Returns {date: {quote: rate}}."""
    params = {"base": config.PIVOT}
    if symbols:
        params["symbols"] = ",".join(symbols)
    r = await request_json("GET", f"{FRANKFURTER}/{start}..{end}",
                           params=params, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, dict) and isinstance(r.get("rates"), dict):
        return r["rates"]
    return {}
