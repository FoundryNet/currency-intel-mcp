"""Env-driven configuration for currency-intel-mcp.

A high-frequency currency conversion & exchange-rate MCP server. `convert` and
`rates` are FREE (the loss leader — massive volume, every call surfaces the
FoundryNet network); `historical_rate` and `rate_trend` are paid via x402. Rates
are aggregated hourly from the ECB (Frankfurter) with exchangerate.host as backup
and cached in its OWN standalone Supabase project. Part of the FoundryNet Data
Network.

Required to be useful:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   the standalone currency-intel Supabase project.
Optional:
  PORT, REQUEST_TIMEOUT
  X402_ENABLED            "true" arms the paywall on the paid tools (DEFAULT true)
  SOLANA_WALLET / PAYMENT_RECIPIENT / PAYMENT_VERIFY_RPC / PAYMENT_USDC_MINT /
  PAYMENT_EXPIRY_SECONDS
  FREE_TIER_DAILY         free PAID-tool queries/day per agent, default 50
  AGG_INTERVAL_MINUTES    rate refresh cadence, default 60
  HISTORY_BACKFILL_DAYS   days of history to backfill on first run, default 90
  PRICE_HISTORICAL_RATE   default 0.005
  PRICE_RATE_TREND        default 0.01
  PRICE_DAILY_BRIEF       default 5
  FNET_API_KEY            fleet bearer for free internal sibling calls
  PUBLIC_MCP_URL
"""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


# ── Standalone currency-intel Supabase project ───────────────────────────────
SUPABASE_URL         = _env("SUPABASE_URL", "https://jqcaenobanfqcuerliqb.supabase.co").rstrip("/")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")

PORT            = int(_env("PORT", "8080"))
REQUEST_TIMEOUT = int(_env("REQUEST_TIMEOUT", "30"))

# ── Rate aggregation ─────────────────────────────────────────────────────────
AGG_INTERVAL_MINUTES  = int(_env("AGG_INTERVAL_MINUTES", "60"))
HISTORY_BACKFILL_DAYS = int(_env("HISTORY_BACKFILL_DAYS", "90"))
# All rates are stored relative to this base (ECB native). Cross-rates are derived.
PIVOT = "EUR"

# ── x402 pay-per-query gate (paid tools only) ────────────────────────────────
X402_ENABLED      = _flag("X402_ENABLED", True)
SOLANA_WALLET     = _env("SOLANA_WALLET", "wUumjWJjfn27VQhTXd1jUNTzszCmsErkzaEeHWbLThd")
PAYMENT_RECIPIENT = _env("PAYMENT_RECIPIENT", SOLANA_WALLET).strip()
PAYMENT_VERIFY_RPC = _env("PAYMENT_VERIFY_RPC", "https://api.mainnet-beta.solana.com").rstrip("/")
PAYMENT_USDC_MINT  = _env("PAYMENT_USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").strip()
PAYMENT_EXPIRY_SECONDS = int(_env("PAYMENT_EXPIRY_SECONDS", "300"))

FREE_TIER_DAILY = int(_env("FREE_TIER_DAILY", "50"))

PRICE_HISTORICAL_RATE = float(_env("PRICE_HISTORICAL_RATE", "0.005"))
PRICE_RATE_TREND      = float(_env("PRICE_RATE_TREND", "0.01"))
PRICE_DAILY_BRIEF     = float(_env("PRICE_DAILY_BRIEF", "5"))
PRICE_BRIEF_SUMMARY = float(_env("PRICE_BRIEF_SUMMARY", "0.5"))  # $0.50 sample tier
PRICE_TRANSACTION_COST = float(_env("PRICE_TRANSACTION_COST", "0.01"))  # cross-border cost calc

# ── Stripe rail (parallel payment option to x402, for the daily brief) ────────
# Agents without a USDC wallet pay this hosted Payment Link instead. The secret
# key verifies the resulting Checkout Session; the link URL is shown on a 402.
STRIPE_SECRET_KEY       = _env("STRIPE_SECRET_KEY", "")
STRIPE_LINK_DAILY_BRIEF = _env("STRIPE_LINK_DAILY_BRIEF",
                               "https://buy.stripe.com/14A6oH2fCddBa184Xt2400d")

# ── Daily curated brief ──────────────────────────────────────────────────────
BRIEF_HOUR_UTC = int(_env("BRIEF_HOUR_UTC", "5"))   # curator runs at 05:00 UTC
SERVER_SLUG    = "currency-intel"
NETWORK_BRIEFS = {
    "financial-signals": "$25", "cyber-intel": "$15", "patent-intel": "$10",
    "gov-contracts": "$10", "compliance": "$10", "brand-intel": "$5",
    "weather-intel": "$5", "fact-check": "$5", "oss-intel": "$5",
    "social-intel": "$5", "email-verify": "$5", "currency-intel": "$5",
}

# Fleet bearer for free internal sibling calls (bypasses each sibling's x402 gate).
FNET_API_KEY = (_env("FNET_API_KEY") or _env("FORGE_API_KEY") or _env("MINT_API_KEY")).strip()

PUBLIC_MCP_URL = _env("PUBLIC_MCP_URL", "https://currency-intel-mcp-production.up.railway.app/mcp")

# ── FoundryNet Data Network — full sister-server map ──────────────────────────
_FNET_ALL_SERVERS = {
    "mint-mcp":              "https://mint-mcp-production.up.railway.app/mcp",
    "foundrynet-mcp":        "https://foundrynet-mcp-production.up.railway.app/mcp",
    "gov-contracts-mcp":     "https://gov-contracts-mcp-production.up.railway.app/mcp",
    "brand-intel-mcp":       "https://brand-intel-mcp-production.up.railway.app/mcp",
    "patent-intel-mcp":      "https://patent-intel-mcp-production.up.railway.app/mcp",
    "financial-signals-mcp": "https://financial-signals-mcp-production.up.railway.app/mcp",
    "weather-intel-mcp":     "https://weather-intel-mcp-production.up.railway.app/mcp",
    "cyber-intel-mcp":       "https://cyber-intel-mcp-production.up.railway.app/mcp",
    "compliance-mcp":        "https://compliance-mcp-production.up.railway.app/mcp",
    "academic-intel-mcp":    "https://academic-intel-mcp-production.up.railway.app/mcp",
    "fact-check-mcp":        "https://fact-check-mcp-production.up.railway.app/mcp",
    "oss-intel-mcp":         "https://oss-intel-mcp-production.up.railway.app/mcp",
    "social-intel-mcp":      "https://social-intel-mcp-production.up.railway.app/mcp",
    "crypto-intel-mcp":      "https://crypto-intel-mcp-production.up.railway.app/mcp",
    "market-data-mcp":       "https://market-data-mcp-production.up.railway.app/mcp",
    "email-verify-mcp":      "https://email-verify-mcp-production.up.railway.app/mcp",
    "currency-intel-mcp":    "https://currency-intel-mcp-production.up.railway.app/mcp",
}
SISTER_SERVERS = {k: v for k, v in _FNET_ALL_SERVERS.items() if k != "currency-intel-mcp"}
