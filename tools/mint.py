import core


def register(mcp) -> None:
    @mcp.tool
    async def mint_info() -> dict:
        """FoundryNet Data Network + MINT Protocol details (FREE). How to attest your
        agent's FX conversions and rate analysis on-chain for verifiable proof of work,
        and the sibling data servers available across the network.
        """
        return core.mint_info()
