"""currency-intel-mcp — currency conversion & exchange-rate intelligence for agents.

A FastMCP server over its OWN standalone Supabase project. `convert` and `rates` are
FREE (the loss leader — huge volume, every call surfaces the FoundryNet network);
`historical_rate` and `rate_trend` are paid via x402. Rates are aggregated hourly
from the ECB (Frankfurter) with exchangerate.host as backup.

  convert         — convert an amount between two currencies   (free)
  rates           — all current rates for a base currency      (free)
  historical_rate — the rate for a pair on a past date         ($0.005)
  rate_trend      — rate history + trend + volatility          ($0.01)
  daily_brief     — curated daily FX movers brief              ($5)
  mint_info       — FoundryNet Data Network + MINT cross-promo (free)

Paid-tool free tier 50 queries/day per agent, then x402 (USDC on Solana). Bearer
fnet_ key bypasses. Transport: Streamable HTTP at /mcp (+ legacy /sse). Health: /health.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import config
import core
import currency_aggregator as agg
import daily_curator
import identity
import payment_gate
import supa
import tools

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("cur.mcp")

if not supa.configured():
    logger.warning("SUPABASE_SERVICE_KEY not set — rates served live per call, nothing cached.")

mcp = FastMCP("currency-intel")

if payment_gate.is_active():
    logger.info(f"pay-per-query ARMED → {config.PAYMENT_RECIPIENT} after "
                f"{config.FREE_TIER_DAILY}/day free (convert/rates always free; "
                f"historical=${config.PRICE_HISTORICAL_RATE}, trend=${config.PRICE_RATE_TREND})")
else:
    logger.info("pay-per-query INERT (X402 off or recipient unset) — all tools free")

tools.register_all(mcp)


# ── Health ──────────────────────────────────────────────────────────────────
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok", "service": "currency-intel-mcp", "transport": "streamable-http",
        "network": "FoundryNet Data Network",
        "tools": ["convert", "rates", "historical_rate", "rate_trend", "daily_brief", "mint_info"],
        "dataset": "supabase:fx_rates" if supa.configured() else "unconfigured",
        "rate_source": "ECB (Frankfurter) + exchangerate.host backup",
        "agg_interval_minutes": config.AGG_INTERVAL_MINUTES,
        "x402_enabled": config.X402_ENABLED,
        "query_payment": "armed" if payment_gate.is_active() else "free",
        "prices_usdc": {"convert": 0, "rates": 0,
                        "historical_rate": config.PRICE_HISTORICAL_RATE,
                        "rate_trend": config.PRICE_RATE_TREND,
                        "daily_brief": config.PRICE_DAILY_BRIEF},
        "free_tier_daily": config.FREE_TIER_DAILY,
        "payment_recipient": config.PAYMENT_RECIPIENT,
    })


@mcp.custom_route("/ping", methods=["GET"])
async def ping(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ── REST surface ─────────────────────────────────────────────────────────────
_ERR_STATUS = {"bad_request": 400, "not_configured": 503, "not_found": 404,
               "payment_required": 402, "not_available": 404}


def _resp(d: dict) -> JSONResponse:
    if "error" not in d:
        return JSONResponse(d, status_code=200)
    err = str(d.get("error") or "")
    code = _ERR_STATUS.get(err, 502 if err in ("network", "non_json_response", "unreachable") else 400)
    if err.startswith("http_") and err[5:].isdigit():
        code = int(err[5:])
    return JSONResponse(d, status_code=code)


async def _json_body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def _akey(request: Request, body: dict) -> str:
    return identity.resolve_agent_key(body.get("agent_id"), request=request)


def _frm(b: dict) -> str:
    return b.get("from") or b.get("from_currency") or ""


def _to(b: dict) -> str:
    return b.get("to") or b.get("to_currency") or ""


@mcp.custom_route("/v1/convert", methods=["GET", "POST"])
async def rest_convert(request: Request) -> JSONResponse:
    b = await _json_body(request)
    qp = request.query_params
    amount = b.get("amount", qp.get("amount", 1))
    frm = _frm(b) or qp.get("from", "")
    to = _to(b) or qp.get("to", "")
    return _resp(await core.do_convert(amount, frm, to))


@mcp.custom_route("/v1/rates", methods=["GET", "POST"])
async def rest_rates(request: Request) -> JSONResponse:
    b = await _json_body(request)
    base = b.get("base") or request.query_params.get("base") or "USD"
    return _resp(await core.do_rates(base))


@mcp.custom_route("/v1/historical", methods=["POST"])
async def rest_historical(request: Request) -> JSONResponse:
    b = await _json_body(request)
    return _resp(await core.do_historical_rate(_frm(b), _to(b), b.get("date", ""),
                                               agent_key=_akey(request, b),
                                               payment_tx=b.get("payment_tx"),
                                               api_key=identity.bearer(request)))


@mcp.custom_route("/v1/trend", methods=["POST"])
async def rest_trend(request: Request) -> JSONResponse:
    b = await _json_body(request)
    return _resp(await core.do_rate_trend(_frm(b), _to(b), b.get("days", 30),
                                          agent_key=_akey(request, b),
                                          payment_tx=b.get("payment_tx"),
                                          api_key=identity.bearer(request)))


@mcp.custom_route("/v1/daily-brief", methods=["POST"])
async def rest_daily_brief(request: Request) -> JSONResponse:
    b = await _json_body(request)
    return _resp(await core.do_daily_brief(b.get("date"), agent_key=_akey(request, b),
                                           payment_tx=b.get("payment_tx"),
                                           api_key=identity.bearer(request)))


@mcp.custom_route("/v1/mint-info", methods=["GET", "POST"])
async def rest_mint(request: Request) -> JSONResponse:
    return JSONResponse(core.mint_info())


# ── Discovery ────────────────────────────────────────────────────────────────
_AGENT_CARD = {
    "name": "Currency & Exchange Rate MCP",
    "description": ("Convert currencies and query exchange rates — free conversion and "
                    "live rates, plus paid historical rates and trend/volatility analytics "
                    "from ECB reference data."),
    "url": config.PUBLIC_MCP_URL,
    "version": "1.0.0",
    "capabilities": {"tools": ["convert", "rates", "historical_rate", "rate_trend",
                               "daily_brief", "mint_info"]},
    "provider": {"name": "FoundryNet", "url": "https://foundrynet.io"},
    "network": "FoundryNet Data Network",
    "attestation": {"protocol": "MINT Protocol",
                    "endpoint": "https://mint-mcp-production.up.railway.app/mcp",
                    "verified_outputs": True, "live_feed": "https://mint.foundrynet.io/feed", "feed_api": "https://mint-mcp-production.up.railway.app/v1/feed"},
    "protocols": {"mcp": {"endpoint": config.PUBLIC_MCP_URL, "transport": "streamable-http", "tools_count": 6},
                  "x402": {"supported": True, "currency": "USDC", "network": "solana"}},
    "contact": "hello@foundrynet.io",
}


@mcp.custom_route("/.well-known/agent-card.json", methods=["GET"])
async def agent_card(request: Request) -> JSONResponse:
    return JSONResponse(_AGENT_CARD, headers={"Cache-Control": "public, max-age=300"})


@mcp.custom_route("/.well-known/mcp", methods=["GET"])
async def mcp_endpoints(request: Request) -> JSONResponse:
    return JSONResponse({"endpoints": [{"url": config.PUBLIC_MCP_URL,
                                        "transport": "streamable-http",
                                        "name": "Currency & Exchange Rate MCP"}]},
                        headers={"Cache-Control": "public, max-age=300"})


async def _live_tools() -> list:
    res = mcp.list_tools()
    if inspect.iscoroutine(res):
        res = await res
    return [{"name": t.name, "description": (getattr(t, "description", "") or "").strip(),
             "inputSchema": getattr(t, "parameters", None) or {"type": "object"}} for t in res]


@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])
async def server_card(request: Request) -> JSONResponse:
    live = await _live_tools()
    return JSONResponse({
        "serverInfo": {"name": "Currency & Exchange Rate MCP", "version": "1.0.0"},
        "authentication": {"type": "http", "scheme": "bearer",
                           "description": ("convert, rates and mint_info are free; historical_rate "
                                           "and rate_trend give 50 free queries/day then take an "
                                           "fnet_ Bearer key OR x402 USDC.")},
        "tools": live, "version": "1.0", "name": "Currency & Exchange Rate MCP",
        "tagline": "Free currency conversion + paid FX history & trends for agents.",
        "description": ("Currency conversion and exchange-rate intelligence: free convert + "
                        "live rates, plus paid historical rates and trend/volatility analytics. "
                        "ECB reference data, refreshed hourly. The free conversion gateway every "
                        "agent handling international transactions needs."),
        "serverUrl": config.PUBLIC_MCP_URL, "transport": "streamable-http",
        "tools_count": len(live),
        "categories": ["finance", "data", "currency", "fx", "utilities"],
        "keywords": ["currency conversion", "exchange rates", "forex", "fx", "ecb",
                     "historical rates", "currency trend"],
        "network": "FoundryNet Data Network", "see_also": config.SISTER_SERVERS,
        "pricing": {"model": "metered",
                    "free_tier": "convert + rates are free; 50 paid queries/day per agent",
                    "paid_from": f"{config.PRICE_HISTORICAL_RATE} USDC per query (x402)"},
    }, headers={"Cache-Control": "public, max-age=300"})


# ── Entrypoint ───────────────────────────────────────────────────────────────
_FREE_TOOL_NAMES = {"mint_info", "macro_dashboard", "cve_detail", "detail",
                    "domain_age", "convert", "rates", "market_overview", "price",
                    "quote", "batch_quote", "sector_performance"}


@mcp.custom_route("/.well-known/mcp.json", methods=["GET"])
async def wellknown_mcp_json(request: Request) -> JSONResponse:
    """Machine-discovery card (emerging standard) for AI clients/crawlers."""
    live = await _live_tools()
    names = [t["name"] for t in live]
    return JSONResponse({
        "name": _AGENT_CARD["name"],
        "description": _AGENT_CARD["description"],
        "url": config.PUBLIC_MCP_URL,
        "transport": ["streamable-http"],
        "tools": names,
        "pricing": {"model": "per-query", "free_tier": True,
                    "paid_tools": [n for n in names if n not in _FREE_TOOL_NAMES]},
        "attestation": {"enabled": True, "protocol": "MINT Protocol",
                        "feed": "https://mint.foundrynet.io/feed"},
        "network": {"name": "FoundryNet Data Network", "servers": 17,
                    "homepage": "https://foundrynet.io"},
    }, headers={"Cache-Control": "public, max-age=300"})


def build_dual_app():
    main_app = mcp.http_app(transport="http", path="/mcp")
    sse_app = mcp.http_app(transport="sse", path="/sse")
    for r in sse_app.routes:
        if getattr(r, "path", None) in ("/sse", "/messages"):
            main_app.router.routes.append(r)
    main_life, sse_life = main_app.router.lifespan_context, sse_app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _dual_lifespan(app):
        async with main_life(app):
            async with sse_life(app):
                agg_task = asyncio.create_task(agg.agg_loop())
                brief_task = asyncio.create_task(daily_curator.curator_loop())
                try:
                    yield
                finally:
                    for t in (agg_task, brief_task):
                        t.cancel()
                        with contextlib.suppress(Exception):
                            await t
    main_app.router.lifespan_context = _dual_lifespan
    return main_app


if __name__ == "__main__":
    import uvicorn
    logger.info(f"currency-intel-mcp starting on 0.0.0.0:{config.PORT} "
                f"(dataset={'supabase' if supa.configured() else 'off'}, x402={config.X402_ENABLED})")
    uvicorn.run(build_dual_app(), host="0.0.0.0", port=config.PORT, log_level="warning")
