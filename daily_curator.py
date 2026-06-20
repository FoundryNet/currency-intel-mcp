"""Daily curated brief — currency-intel.

Runs once a day at BRIEF_HOUR_UTC (05:00 UTC). It computes the biggest 7-day FX
movers across major currencies (vs USD), the current key cross-rates, and attests
the package through MINT, then upserts it into `daily_briefs`. The paid daily_brief
tool reads that row back.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import config
import mint_integration
import supa

logger = logging.getLogger("cur.curator")

SERVER = config.SERVER_SLUG
PRICE = config.PRICE_DAILY_BRIEF

MAJORS = ["USD", "EUR", "GBP", "JPY", "CNY", "CHF", "CAD", "AUD", "INR",
          "BRL", "MXN", "KRW", "SGD", "HKD", "SEK", "NOK", "ZAR", "TRY"]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _expires_at(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")


def related_briefs(exclude: str) -> list:
    return [{"server": s, "price": p, "tool": "daily_brief"}
            for s, p in config.NETWORK_BRIEFS.items() if s != exclude]


async def _curate_signals() -> tuple[dict, int]:
    latest = await supa.get_latest_rates()
    usd = latest.get("USD")
    key_rates = {}
    if usd:
        for q in ["EUR", "GBP", "JPY", "CNY", "CHF", "CAD", "AUD", "INR"]:
            if latest.get(q) is not None:
                key_rates[f"USD/{q}"] = round(latest[q] / usd, 6)

    # 7-day movers vs USD, computed from the historical series.
    from_date = (datetime.now(timezone.utc).date() - timedelta(days=8)).strftime("%Y-%m-%d")
    movers = []
    for q in MAJORS:
        if q == "USD":
            continue
        series = await supa.get_series(q, from_date)  # PIVOT->q
        usd_series = await supa.get_series("USD", from_date)
        sq = dict(series)
        su = dict(usd_series)
        common = sorted(set(sq) & set(su))
        if len(common) < 2:
            continue
        # USD->q rate = q_per_eur / usd_per_eur
        first = sq[common[0]] / su[common[0]] if su[common[0]] else None
        last = sq[common[-1]] / su[common[-1]] if su[common[-1]] else None
        if not first or not last:
            continue
        change = round(100 * (last - first) / first, 3)
        movers.append({"pair": f"USD/{q}", "change_pct_7d": change,
                       "from": round(first, 6), "to": round(last, 6)})
    movers.sort(key=lambda m: abs(m["change_pct_7d"]), reverse=True)

    signals = {
        "as_of": latest.get("_as_of"),
        "key_rates_usd_base": key_rates,
        "top_movers_7d": movers[:10],
    }
    count = len(key_rates) + len(movers[:10])
    return signals, count


async def run_curation(date_str: str | None = None) -> dict:
    date_str = date_str or _today()
    signals, count = await _curate_signals()

    brief = {
        "brief_date": date_str, "server": SERVER, "signal_count": count,
        "signals": signals, "expires_at": _expires_at(date_str),
        "related_briefs": related_briefs(SERVER),
    }
    attestation = await asyncio.to_thread(
        mint_integration.attest_data, brief, "analysis",
        f"Daily {SERVER} brief: {count} FX signals")
    brief["provenance"] = attestation

    row = {
        "brief_date": date_str, "brief_data": brief, "signal_count": count,
        "attestation_hash": attestation.get("attestation_hash"),
        "expires_at": _expires_at(date_str),
    }
    res = await supa.upsert("daily_briefs", [row], "brief_date")
    if isinstance(res, dict) and res.get("error"):
        logger.warning(f"daily brief upsert failed: {str(res)[:200]}")
    else:
        logger.info(f"daily brief stored: {date_str} ({count} FX signals)")
    return brief


async def get_brief(date_str: str | None = None) -> dict | None:
    date_str = date_str or _today()
    rows = await supa.select("daily_briefs",
                             {"select": "*", "brief_date": f"eq.{date_str}", "limit": "1"})
    if not rows:
        return None
    row = rows[0]
    exp = row.get("expires_at")
    if exp:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(exp.replace("Z", "+00:00")):
                return None
        except Exception:  # noqa: BLE001
            pass
    return row.get("brief_data")


async def bump_purchase(date_str: str) -> None:
    try:
        await supa.rpc("increment_brief_purchase", {"p_brief_date": date_str})
    except Exception:  # noqa: BLE001
        pass


async def curator_loop() -> None:
    while True:
        now = datetime.now(timezone.utc)
        secs = now.hour * 3600 + now.minute * 60 + now.second
        wait = (config.BRIEF_HOUR_UTC * 3600 - secs) % 86400 or 86400
        try:
            await asyncio.sleep(wait)
            if supa.configured():
                await run_curation()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"curator loop error: {e}")
            await asyncio.sleep(3600)
