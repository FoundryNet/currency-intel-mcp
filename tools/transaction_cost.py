from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def transaction_cost(
        amount: float,
        from_currency: str,
        to_currency: str,
        method: str = "wire",
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Calculate the TOTAL landed cost of a cross-border payment: FX spread +
        transfer fee + settlement time, by payment method. Goes beyond the mid-market
        rate to show what the recipient actually receives and which rail is cheapest.
        Methods: wire (SWIFT), ach, crypto (USDC/stablecoin), card, paypal.

        PAID: $0.01 USDC per calculation after a daily free allowance (50/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses payment.

        Args:
            amount: the amount to send, in from_currency (e.g. 10000).
            from_currency: ISO 4217 source code, e.g. "USD".
            to_currency: ISO 4217 target code, e.g. "EUR".
            method: payment rail — one of wire, ach, crypto, card, paypal (default wire).
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_transaction_cost(
            amount, from_currency, to_currency, method,
            agent_key=identity.resolve_agent_key(agent_id),
            payment_tx=payment_tx, api_key=identity.bearer())
