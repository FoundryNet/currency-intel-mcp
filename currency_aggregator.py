"""Currency aggregator — refreshes the latest rate snapshot every hour and keeps
the historical daily series filled in. Runs in-process (build_dual_app starts the
loop), so no external cron is needed.

  • run_aggregation()  — fetch latest ECB rates → upsert fx_latest + today's fx_rates
  • backfill_history()  — on first run, populate the last HISTORY_BACKFILL_DAYS of
                          daily rates so rate_trend / historical_rate work immediately
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import config
import currency_sources as src
import supa

logger = logging.getLogger("cur.agg")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def run_aggregation() -> dict:
    """Fetch the latest rates and persist them (snapshot + today's historical row)."""
    data = await src.latest()
    rates = data.get("rates") or {}
    if not rates:
        logger.warning("aggregation: no rates fetched")
        return {"ok": False, "count": 0}
    date_str = data.get("date") or _today()
    await supa.upsert_latest(date_str, rates)
    await supa.upsert_rates_for_date(date_str, rates)
    logger.info(f"aggregation: {len(rates)} rates as of {date_str}")
    return {"ok": True, "count": len(rates), "as_of": date_str}


async def backfill_history() -> int:
    """Populate the last HISTORY_BACKFILL_DAYS of daily rates if the history table is
    sparse. Idempotent (upsert). Returns the number of days written."""
    existing = await supa.select("fx_rates", {"select": "date", "order": "date.desc", "limit": "5"})
    if len(existing) >= 3:
        return 0  # already have history
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=config.HISTORY_BACKFILL_DAYS)
    series = await src.series(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    n = 0
    for date_str, rates in sorted(series.items()):
        rates = dict(rates)
        rates[config.PIVOT] = 1.0
        res = await supa.upsert_rates_for_date(date_str, rates)
        if not (isinstance(res, dict) and res.get("error")):
            n += 1
    logger.info(f"backfill_history: wrote {n} days of rates")
    return n


async def agg_loop() -> None:
    """Refresh now (and backfill on cold start), then every AGG_INTERVAL_MINUTES."""
    interval = max(5, config.AGG_INTERVAL_MINUTES) * 60
    # Cold-start: pull latest immediately + backfill history so tools work at once.
    try:
        if supa.configured():
            await run_aggregation()
            await backfill_history()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"initial aggregation error: {e}")
    while True:
        try:
            await asyncio.sleep(interval)
            if supa.configured():
                await run_aggregation()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"agg loop error: {e}")
            await asyncio.sleep(300)
