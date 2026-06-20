from typing import Optional

import core


def register(mcp) -> None:
    @mcp.tool
    async def convert(
        amount: float,
        from_currency: str,
        to_currency: str,
    ) -> dict:
        """Convert an amount from one currency to another at the latest ECB reference
        rate. FREE — the gateway tool every agent handling international transactions
        needs. Returns the converted amount, the rate used, and the as-of date.

        Args:
            amount: the amount to convert (e.g. 100).
            from_currency: ISO 4217 source code, e.g. "USD".
            to_currency: ISO 4217 target code, e.g. "EUR".
        """
        return await core.do_convert(amount, from_currency, to_currency)
