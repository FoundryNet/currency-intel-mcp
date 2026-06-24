"""Shared logic behind the MCP tools and REST routes.

convert/rates are FREE and served from the latest snapshot (live fallback on a cold
cache). historical_rate/rate_trend are PAID (x402) and read the historical daily
series (live fallback + cache on miss). All stored rates are relative to PIVOT (EUR);
cross-rates are derived as rates[to]/rates[from].
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import datetime, timedelta, timezone

import config
import currency_sources as src
import daily_curator
import mint_integration
import payment_gate
import stripe_gate
import supa

logger = logging.getLogger("cur.core")


def _ccy(x) -> str:
    return (x or "").strip().upper()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _billing(decision: dict) -> dict:
    g = decision.get("gate")
    if g == "free":
        cap, cnt = decision.get("cap"), decision.get("count")
        return {"tier": "free", "used_today": cnt, "daily_free": cap,
                "remaining_today": (cap - cnt) if (cap is not None and cnt is not None) else None}
    if g == "paid":
        return {"tier": "paid", "charged_usdc": decision.get("amount_usdc")}
    if g == "api_key":
        return {"tier": "api_key", "note": "billed to your Forge account"}
    return {"tier": "free", "note": "gating inert"}


async def _latest_rates() -> dict:
    """Latest PIVOT-based rates from cache; live fallback (and cache) on cold start."""
    rates = await supa.get_latest_rates()
    if rates and len(rates) > 2:
        return rates
    data = await src.latest()
    live = data.get("rates") or {}
    if live:
        live["_as_of"] = data.get("date")
        try:
            await supa.upsert_latest(data.get("date") or _today(), {k: v for k, v in live.items() if k != "_as_of"})
        except Exception:  # noqa: BLE001
            pass
    return live


def _cross(rates: dict, frm: str, to: str):
    """rate(from→to) = rates[to]/rates[from]. None if either code is unknown."""
    rf, rt = rates.get(frm), rates.get(to)
    if rf in (None, 0) or rt is None:
        return None
    return rt / rf


# ── convert (FREE) ────────────────────────────────────────────────────────────
async def do_convert(amount, frm: str, to: str) -> dict:
    frm, to = _ccy(frm), _ccy(to)
    if not frm or not to:
        return {"error": "bad_request", "detail": "from and to currency codes are required"}
    try:
        amt = float(amount if amount is not None else 1)
    except (TypeError, ValueError):
        return {"error": "bad_request", "detail": "amount must be a number"}
    rates = await _latest_rates()
    rate = _cross(rates, frm, to)
    if rate is None:
        return {"error": "bad_request",
                "detail": f"unknown currency code(s); supported: {', '.join(sorted(k for k in rates if not k.startswith('_')))[:400]}"}
    return {"amount": amt, "from": frm, "to": to,
            "converted": round(amt * rate, 6), "rate": round(rate, 6),
            "as_of": rates.get("_as_of"), "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": "FoundryNet Data Network — free FX gateway", "billing": {"tier": "free"}}


# ── rates (FREE) ──────────────────────────────────────────────────────────────
async def do_rates(base: str | None) -> dict:
    base = _ccy(base) or "USD"
    rates = await _latest_rates()
    rb = rates.get(base)
    if rb in (None, 0):
        return {"error": "bad_request", "detail": f"unknown base currency '{base}'"}
    out = {q: round(r / rb, 6) for q, r in rates.items()
           if not q.startswith("_") and r is not None}
    return {"base": base, "rates": out, "count": len(out),
            "as_of": rates.get("_as_of"), "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": "FoundryNet Data Network — free FX gateway", "billing": {"tier": "free"}}


# ── historical_rate (PAID) ────────────────────────────────────────────────────
async def do_historical_rate(frm: str, to: str, date: str, *, agent_key, payment_tx=None, api_key=None) -> dict:
    frm, to = _ccy(frm), _ccy(to)
    if not frm or not to or not date:
        return {"error": "bad_request", "detail": "from, to, and date (YYYY-MM-DD) are required"}
    decision = await payment_gate.precheck("historical_rate", {"from": frm, "to": to, "date": date},
                                           config.PRICE_HISTORICAL_RATE, agent_key, payment_tx, api_key)
    if decision["gate"] == "blocked":
        return decision["body"]
    rates = await supa.get_rates_on(date)
    if not rates:
        data = await src.on_date(date)
        rates = data.get("rates") or {}
        if rates:
            try:
                await supa.upsert_rates_for_date(data.get("date") or date, rates)
            except Exception:  # noqa: BLE001
                pass
    rate = _cross(rates, frm, to)
    if rate is None:
        return {"error": "not_found",
                "detail": f"no rate for {frm}->{to} on {date} (date out of range or unknown code)",
                "billing": _billing(decision)}
    result = {"from": frm, "to": to, "date": date, "rate": round(rate, 6),
              "billing": _billing(decision)}
    result["provenance"] = await asyncio.to_thread(
        mint_integration.attest_data, result, "analysis", "historical_rate result")
    return result


# ── rate_trend (PAID) ─────────────────────────────────────────────────────────
async def do_rate_trend(frm: str, to: str, days, *, agent_key, payment_tx=None, api_key=None) -> dict:
    frm, to = _ccy(frm), _ccy(to)
    if not frm or not to:
        return {"error": "bad_request", "detail": "from and to currency codes are required"}
    try:
        n = max(2, min(int(days or 30), 365))
    except (TypeError, ValueError):
        n = 30
    decision = await payment_gate.precheck("rate_trend", {"from": frm, "to": to, "days": n},
                                           config.PRICE_RATE_TREND, agent_key, payment_tx, api_key)
    if decision["gate"] == "blocked":
        return decision["body"]
    from_date = (datetime.now(timezone.utc).date() - timedelta(days=n)).strftime("%Y-%m-%d")
    s_from = dict(await supa.get_series(frm, from_date))
    s_to = dict(await supa.get_series(to, from_date))
    # Live fallback if history is too thin.
    if len(s_from) < 2 or len(s_to) < 2:
        end = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        ser = await src.series(from_date, end, symbols=sorted({frm, to} - {config.PIVOT}))
        for d, r in ser.items():
            r = dict(r); r[config.PIVOT] = 1.0
            if frm in r:
                s_from[d] = r[frm]
            if to in r:
                s_to[d] = r[to]
            try:
                await supa.upsert_rates_for_date(d, r)
            except Exception:  # noqa: BLE001
                pass
    # Build the pair series rate(from→to) = to/from per common date.
    series = []
    for d in sorted(set(s_from) & set(s_to)):
        rf, rt = s_from[d], s_to[d]
        if rf:
            series.append((d, rt / rf))
    if len(series) < 2:
        return {"error": "not_found", "detail": f"insufficient history for {frm}->{to}",
                "billing": _billing(decision)}
    vals = [v for _, v in series]
    first, last = vals[0], vals[-1]
    change_pct = round(100 * (last - first) / first, 4) if first else None
    mean = statistics.fmean(vals)
    vol = round((statistics.pstdev(vals) / mean) * 100, 4) if mean else None
    direction = ("appreciating" if last > first * 1.001
                 else "depreciating" if last < first * 0.999 else "flat")
    result = {
        "from": frm, "to": to, "days": n, "observations": len(series),
        "start": {"date": series[0][0], "rate": round(first, 6)},
        "end": {"date": series[-1][0], "rate": round(last, 6)},
        "change_pct": change_pct,
        "trend_direction": direction,
        "volatility_pct": vol,
        "min": round(min(vals), 6), "max": round(max(vals), 6), "avg": round(mean, 6),
        "history": [{"date": d, "rate": round(v, 6)} for d, v in series],
        "billing": _billing(decision),
    }
    result["provenance"] = await asyncio.to_thread(
        mint_integration.attest_data,
        {k: result[k] for k in ("from", "to", "days", "change_pct", "trend_direction", "volatility_pct")},
        "analysis", "rate_trend result")
    return result


# ── daily_brief (premium, curated) ────────────────────────────────────────────
async def do_daily_brief(date, *, agent_key, payment_tx=None, api_key=None,
                         stripe_token=None) -> dict:
    day = (date or _today()).strip()

    # Stripe rail (parallel to x402): a paid Checkout Session unlocks the brief.
    stripe_err = None
    if stripe_token and stripe_gate.is_active():
        sv = await stripe_gate.verify_session(stripe_token, config.PRICE_DAILY_BRIEF,
                                              tool="daily_brief", agent_key=agent_key)
        if sv["ok"]:
            brief = await daily_curator.get_brief(day)
            if not brief:
                return {"error": "not_available",
                        "detail": f"No brief for {day} (not yet generated, or expired at midnight UTC). "
                                  f"Briefs are curated daily at {config.BRIEF_HOUR_UTC:02d}:00 UTC.",
                        "billing": "stripe"}
            await daily_curator.bump_purchase(day)
            return {**brief, "billing": "stripe", "stripe_session": sv["session"]}
        stripe_err = sv.get("detail")  # surface on the 402 below

    decision = await payment_gate.precheck("daily_brief", {"date": day},
                                           config.PRICE_DAILY_BRIEF, agent_key, payment_tx, api_key)
    if decision["gate"] == "blocked":
        return stripe_gate.augment_402(decision["body"], config.PRICE_DAILY_BRIEF,
                                       stripe_error=stripe_err)
    brief = await daily_curator.get_brief(day)
    if not brief:
        return {"error": "not_available",
                "detail": f"No brief for {day} (not yet generated, or expired at midnight UTC). "
                          f"Briefs are curated daily at {config.BRIEF_HOUR_UTC:02d}:00 UTC.",
                "billing": _billing(decision)}
    await daily_curator.bump_purchase(day)
    return {**brief, "billing": _billing(decision)}


# ── transaction_cost (PAID $0.01): cross-border transaction cost calculator ───
_FEE_SCHEDULES = {
    "wire":   {"fixed": 25.0, "pct": 0.001,  "settlement_days": 2, "name": "Bank Wire (SWIFT)"},
    "ach":    {"fixed": 5.0,  "pct": 0.0005, "settlement_days": 3, "name": "ACH Transfer"},
    "crypto": {"fixed": 0.5,  "pct": 0.001,  "settlement_days": 0, "name": "USDC/Stablecoin"},
    "card":   {"fixed": 0.0,  "pct": 0.029,  "settlement_days": 1, "name": "Credit/Debit Card"},
    "paypal": {"fixed": 0.30, "pct": 0.029,  "settlement_days": 1, "name": "PayPal"},
}
_SPREAD_PCT = {"wire": 0.005, "card": 0.015, "crypto": 0.001}


async def do_transaction_cost(amount, from_currency, to_currency, method="wire", *,
                              agent_key, payment_tx=None, api_key=None) -> dict:
    frm, to = _ccy(from_currency), _ccy(to_currency)
    if not frm or not to:
        return {"error": "bad_request", "detail": "from_currency and to_currency are required"}
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return {"error": "bad_request", "detail": "amount must be a number"}
    if amt <= 0:
        return {"error": "bad_request", "detail": "amount must be greater than 0"}
    method = (method or "wire").strip().lower()

    dec = await payment_gate.precheck("transaction_cost",
                                      {"amount": amt, "from": frm, "to": to, "method": method},
                                      config.PRICE_TRANSACTION_COST, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]

    rate_data = await do_convert(amt, frm, to)
    if not rate_data or "error" in rate_data:
        return {"error": "source_error", "detail": "Could not fetch exchange rate",
                "billing": _billing(dec)}
    converted = rate_data.get("converted")
    rate = rate_data.get("rate")
    if converted is None or rate is None:
        return {"error": "source_error", "detail": "Could not fetch exchange rate",
                "billing": _billing(dec)}

    fee_info = _FEE_SCHEDULES.get(method, _FEE_SCHEDULES["wire"])
    spread_pct = _SPREAD_PCT.get(method, 0.01)
    spread_cost = converted * spread_pct
    transfer_fee = fee_info["fixed"] + amt * fee_info["pct"]
    total_cost = spread_cost + transfer_fee
    effective_rate = rate * (1 - spread_pct)
    total_cost_pct = (total_cost / converted * 100) if converted else None

    out = {
        "payment": {
            "amount": amt, "from": frm, "to": to,
            "mid_market_rate": rate, "converted_at_mid": converted,
        },
        "costs": {
            "fx_spread": round(spread_cost, 2),
            "fx_spread_pct": f"{round(spread_pct * 100, 3)}%",
            "transfer_fee": round(transfer_fee, 2),
            "total_cost": round(total_cost, 2),
            "total_cost_pct": (f"{round(total_cost_pct, 3)}%" if total_cost_pct is not None else None),
        },
        "effective": {
            "rate": round(effective_rate, 6),
            "you_receive": round(converted - spread_cost, 2),
            "settlement_days": fee_info["settlement_days"],
        },
        "method": fee_info["name"],
        "cheaper_alternative": (
            "Consider USDC/stablecoin transfer — near-zero fees, instant settlement"
            if method != "crypto" and total_cost > 10 else None),
        "as_of": rate_data.get("as_of"),
        "billing": _billing(dec),
    }
    out["provenance"] = await asyncio.to_thread(
        mint_integration.attest_data, out, "analysis", "cross-border transaction cost")
    return out


def mint_info() -> dict:
    return {
        "network": "FoundryNet Data Network", **mint_integration.network_feed_block(),
        "message": ("Attest your agent's FX conversions and rate analysis with MINT "
                    "Protocol for verifiable on-chain proof of work."),
        "positioning": ("A free conversion gateway (convert/rates) plus paid historical "
                        "and trend analytics — ECB reference rates for agents handling "
                        "international transactions."),
        "mint_protocol": {"mcp_endpoint": "https://mint-mcp-production.up.railway.app/mcp",
                          "info_url": "https://mint.foundrynet.io",
                          "tools": ["mint_register", "mint_attest", "mint_verify",
                                    "mint_rate", "mint_recommend", "mint_discover"]},
        "see_also": config.SISTER_SERVERS,
    }


# ── Soft upsell: surface the daily_brief on every paid, non-brief response ─────
import time as _upsell_time

_brief_upsell_cache = {"day": None, "ts": 0.0, "available": False, "count": 0}


async def _brief_status_cached() -> tuple[bool, int]:
    day = _upsell_time.strftime("%Y-%m-%d", _upsell_time.gmtime())
    now = _upsell_time.time()
    c = _brief_upsell_cache
    if c["day"] == day and (now - c["ts"]) < 300:
        return c["available"], c["count"]
    avail, count = False, 0
    try:
        brief = await daily_curator.get_brief(day)
        if brief:
            avail, count = True, int(brief.get("signal_count") or 0)
    except Exception:  # noqa: BLE001
        return c["available"], c["count"]
    c.update(day=day, ts=now, available=avail, count=count)
    return avail, count


async def _available_intelligence() -> dict:
    avail, count = await _brief_status_cached()
    return {"daily_brief": {
        "available": avail,
        "signal_count": count,
        "price_usd": config.PRICE_DAILY_BRIEF,
        "tool": "daily_brief",
        "note": "Curated daily intelligence — more efficient than individual queries",
    }}


def _make_upsell(_fn):
    import functools

    @functools.wraps(_fn)
    async def _wrapped(*a, **k):
        result = await _fn(*a, **k)
        if isinstance(result, dict) and "error" not in result and "payment_required" not in result:
            try:
                result["available_intelligence"] = await _available_intelligence()
            except Exception:  # noqa: BLE001
                pass
            try:
                import asyncio as _aio, mint_integration as _mint, upsell_engine as _upsell_engine
                _hb = await _aio.to_thread(_mint.network_heartbeat)
                _av, _ct = await _brief_status_cached()
                result["foundrynet_network"] = {**_hb, **_upsell_engine.get_upsell(
                    brief_price=config.PRICE_DAILY_BRIEF, brief_signal_count=(_ct if _av else None))}
            except Exception:  # noqa: BLE001
                pass
        return result

    return _wrapped


for _upsell_fn in ("do_historical_rate", "do_rate_trend", "do_transaction_cost"):
    if _upsell_fn in globals():
        globals()[_upsell_fn] = _make_upsell(globals()[_upsell_fn])



# ── brief_summary ($0.50): structured top-5 sample of today's brief (upsell) ──
def _top_signals(brief: dict, n: int = 5) -> list:
    """Flatten a brief's signals into a flat top-N list — structure-agnostic
    (works whether `signals` is a dict-of-categories or a flat list)."""
    sig = (brief or {}).get("signals")
    items: list = []
    if isinstance(sig, dict):
        for cat, val in sig.items():
            if isinstance(val, list):
                for it in val:
                    items.append({"category": cat, **(it if isinstance(it, dict) else {"value": it})})
            elif isinstance(val, dict):
                items.append({"category": cat, **val})
            elif val not in (None, "", 0):
                items.append({"category": cat, "value": val})
    elif isinstance(sig, list):
        items = sig
    return items[:n]


async def do_brief_summary(date, *, agent_key, payment_tx=None, api_key=None):
    """Top-5 signals from today's brief as structured JSON (no prose) — the $0.50
    sample that upsells the full daily_brief."""
    from datetime import datetime, timezone
    day = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    dec = await payment_gate.precheck("brief_summary", {"date": day}, config.PRICE_BRIEF_SUMMARY,
                                      agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    brief = await daily_curator.get_brief(day)
    if not brief:
        return {"error": "not_available",
                "detail": f"No brief for {day} yet (curated daily; expires next midnight UTC).",
                "billing": _billing(dec)}
    return {
        "date": day,
        "top_signals": _top_signals(brief, 5),
        "total_signals": brief.get("signal_count"),
        "full_brief": {"tool": "daily_brief", "price_usd": config.PRICE_DAILY_BRIEF,
                       "note": "Full brief returns all signals with complete detail + MINT attestation."},
        "billing": _billing(dec),
    }
