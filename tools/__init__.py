"""currency-intel-mcp tools — one per file.

  convert         (free)    convert an amount between two currencies
  rates           (free)    all current rates for a base currency
  historical_rate ($0.005)  the rate for a pair on a past date
  rate_trend      ($0.01)   rate history + trend direction + volatility
  daily_brief     ($5)      curated daily FX movers brief
  mint_info       (free)    FoundryNet Data Network + MINT cross-promo
"""
from . import convert as convert_tool
from . import rates as rates_tool
from . import historical_rate as historical_rate_tool
from . import rate_trend as rate_trend_tool
from . import daily_brief as daily_brief_tool
from . import mint as mint_tool


def register_all(mcp) -> None:
    convert_tool.register(mcp)
    rates_tool.register(mcp)
    historical_rate_tool.register(mcp)
    rate_trend_tool.register(mcp)
    daily_brief_tool.register(mcp)
    mint_tool.register(mcp)
