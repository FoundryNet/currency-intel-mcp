"""Supabase PostgREST client for currency-intel-mcp (standalone currency project).

Backs the latest-rate snapshot (fx_latest), the historical daily rates (fx_rates),
the free-tier counter (cur_claim_free_query RPC), the x402 payment ledger
(cur_payments), and the daily brief (daily_briefs). All rates are stored relative
to PIVOT (EUR). Every helper returns plain data and never raises.
"""
from __future__ import annotations

import logging
from typing import Optional

import config
from http_util import request_json

logger = logging.getLogger("cur.supa")


def configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _headers(extra: Optional[dict] = None) -> dict:
    h = {"apikey": config.SUPABASE_SERVICE_KEY,
         "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
         "Content-Type": "application/json", "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def _url(path: str) -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{path}"


async def _select(table: str, params: dict) -> list:
    if not configured():
        return []
    r = await request_json("GET", _url(table), headers=_headers(),
                           params=params, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, list):
        return r
    logger.warning(f"supa select {table} failed: {r}")
    return []


async def _rpc(fn: str, body: dict):
    if not configured():
        return None
    return await request_json("POST", _url(f"rpc/{fn}"), headers=_headers(),
                              body=body, timeout=config.REQUEST_TIMEOUT)


# ── fx_latest (current snapshot, base=PIVOT) ──────────────────────────────────
async def get_latest_rates() -> dict:
    """Return {quote: rate} for the current snapshot (relative to PIVOT), plus the
    as_of date under key '_as_of'. Empty dict if none stored."""
    rows = await _select("fx_latest", {"base": f"eq.{config.PIVOT}",
                                       "select": "quote,rate,as_of", "limit": "1000"})
    out = {}
    as_of = None
    for r in rows:
        if r.get("quote") and r.get("rate") is not None:
            out[r["quote"]] = float(r["rate"])
            as_of = r.get("as_of") or as_of
    if out:
        out["_as_of"] = as_of
    return out


async def upsert_latest(date_str: str, rates: dict) -> dict:
    rows = [{"base": config.PIVOT, "quote": q, "rate": rt, "as_of": date_str}
            for q, rt in rates.items()]
    return await upsert("fx_latest", rows, "base,quote")


# ── fx_rates (historical daily, base=PIVOT) ───────────────────────────────────
async def get_rates_on(date_str: str) -> dict:
    rows = await _select("fx_rates", {"base": f"eq.{config.PIVOT}", "date": f"eq.{date_str}",
                                      "select": "quote,rate", "limit": "1000"})
    return {r["quote"]: float(r["rate"]) for r in rows if r.get("quote") and r.get("rate") is not None}


async def get_series(quote: str, from_date: str) -> list:
    """Daily (date, rate) for PIVOT→quote since from_date, ascending."""
    rows = await _select("fx_rates", {"base": f"eq.{config.PIVOT}", "quote": f"eq.{quote}",
                                      "date": f"gte.{from_date}", "select": "date,rate",
                                      "order": "date.asc", "limit": "2000"})
    return [(r["date"], float(r["rate"])) for r in rows if r.get("rate") is not None]


async def upsert_rates_for_date(date_str: str, rates: dict) -> dict:
    rows = [{"date": date_str, "base": config.PIVOT, "quote": q, "rate": rt}
            for q, rt in rates.items()]
    return await upsert("fx_rates", rows, "date,base,quote")


# ── generic helpers ───────────────────────────────────────────────────────────
async def select(table: str, params: dict) -> list:
    return await _select(table, params)


async def upsert(table: str, rows: list, on_conflict: str) -> dict:
    if not configured() or not rows:
        return {"error": "not_configured_or_empty"}
    r = await request_json("POST", _url(table),
                           headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                           params={"on_conflict": on_conflict},
                           body=rows, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, list):
        return {"data": r}
    if isinstance(r, dict) and "error" not in r:
        return {"data": []}
    return r if isinstance(r, dict) else {"error": "bad_response", "detail": str(r)}


async def rpc(fn: str, body: dict):
    return await _rpc(fn, body)


# ── free-tier counter ─────────────────────────────────────────────────────────
async def claim_free_query(agent_key: str, day: str, cap: int) -> Optional[dict]:
    r = await _rpc("cur_claim_free_query",
                   {"p_agent_key": agent_key, "p_day": day, "p_cap": cap})
    if isinstance(r, dict) and "allowed" in r:
        return r
    if isinstance(r, list) and r and isinstance(r[0], dict):
        return r[0]
    logger.warning(f"claim_free_query rpc unexpected: {r}")
    return None


# ── payment ledger ────────────────────────────────────────────────────────────
async def payment_tx_used(tx_signature: str) -> bool:
    rows = await _select("cur_payments",
                         {"tx_signature": f"eq.{tx_signature}", "select": "tx_signature", "limit": "1"})
    return bool(rows)


async def insert_payment(row: dict) -> dict:
    if not configured():
        return {"error": "not_configured"}
    r = await request_json("POST", _url("cur_payments"),
                           headers=_headers({"Prefer": "return=minimal"}),
                           body=row, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, list):
        return {"data": r}
    if isinstance(r, dict) and "error" not in r:
        return {"data": [r]}
    return r if isinstance(r, dict) else {"error": "bad_response", "detail": str(r)}
