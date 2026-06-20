from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def historical_rate(
        from_currency: str,
        to_currency: str,
        date: str,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Get the exchange rate for a currency pair on a specific past date (ECB
        reference, nearest prior business day). For back-dating invoices, settlements,
        and historical accounting.

        PAID: $0.005 USDC per query after a daily free allowance. On a 402, pay the
        returned Solana memo and re-call with the SAME args plus payment_tx=<signature>.
        An Authorization: Bearer fnet_ key bypasses payment.

        Args:
            from_currency: ISO 4217 source code, e.g. "USD".
            to_currency: ISO 4217 target code, e.g. "EUR".
            date: the date, YYYY-MM-DD.
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_historical_rate(from_currency, to_currency, date,
                                             agent_key=identity.resolve_agent_key(agent_id),
                                             payment_tx=payment_tx, api_key=identity.bearer())
