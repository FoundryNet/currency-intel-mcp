from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def rate_trend(
        from_currency: str,
        to_currency: str,
        days: Optional[int] = 30,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Get the rate history for a currency pair over the last N days, with the
        trend direction (appreciating/depreciating/flat), percentage change, and
        volatility — for FX risk, hedging, and timing decisions.

        PAID: $0.01 USDC per query after a daily free allowance. On a 402, pay the
        returned Solana memo and re-call with the SAME args plus payment_tx=<signature>.
        An Authorization: Bearer fnet_ key bypasses payment.

        Args:
            from_currency: ISO 4217 source code, e.g. "USD".
            to_currency: ISO 4217 target code, e.g. "EUR".
            days: lookback window in days (2–365, default 30).
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_rate_trend(from_currency, to_currency, days,
                                        agent_key=identity.resolve_agent_key(agent_id),
                                        payment_tx=payment_tx, api_key=identity.bearer())
