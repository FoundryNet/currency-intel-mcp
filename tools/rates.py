from typing import Optional

import core


def register(mcp) -> None:
    @mcp.tool
    async def rates(base: Optional[str] = "USD") -> dict:
        """Get all current exchange rates for a base currency at the latest ECB
        reference fix. FREE. Returns a {currency: rate} map plus the as-of date.

        Args:
            base: ISO 4217 base currency (default "USD").
        """
        return await core.do_rates(base)
