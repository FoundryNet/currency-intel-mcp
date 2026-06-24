# Cross-Border Transaction Cost Calculator

**Cross-border payment cost calculator for AI agents** — get the TOTAL landed
cost of an international payment (`transaction_cost`): FX spread + transfer fees +
settlement time, by payment method (wire/ACH/crypto/card/PayPal), so you know what
the recipient actually receives and which rail is cheapest. Also provides free,
instant currency conversion and live ECB exchange rates, plus paid historical
rates and trend/volatility analytics.

> Part of the **FoundryNet Data Network**. Attest your agent's FX conversions and
> payment-cost analysis with [MINT Protocol](https://mint-mcp-production.up.railway.app/mcp).

## Live network activity

**Live feed:** [mint.foundrynet.io/feed](https://mint.foundrynet.io/feed)
Real-time verified work across the network and autonomous agents, anchored on Solana via [MINT Protocol](https://mint.foundrynet.io).

## Connect

- **MCP endpoint** (Streamable HTTP): `https://currency-intel-mcp-production.up.railway.app/mcp`

```bash
claude mcp add --transport http currency-intel https://currency-intel-mcp-production.up.railway.app/mcp
```

## Tools

| Tool | Price | What it does |
|---|---|---|
| `convert` | **free** | Convert an amount between two currencies at the latest ECB reference rate |
| `rates` | **free** | All current rates for a base currency |
| `transaction_cost` | $0.01 | Total cross-border payment cost — FX spread + transfer fee + settlement time by method (wire/ACH/crypto/card/PayPal) |
| `historical_rate` | $0.005 | The rate for a pair on a past date |
| `rate_trend` | $0.01 | Rate history + trend direction + volatility |
| `daily_brief` | $5 | Curated daily FX movers brief |
| `mint_info` | **free** | FoundryNet Data Network + MINT Protocol |

**Free tier:** `convert` + `rates` are always free; 50 paid-tool queries/day per
agent. Then x402: the tool returns an HTTP-402 with a Solana USDC payment memo —
pay it, re-call with the same args plus `payment_tx=<signature>`. An
`Authorization: Bearer fnet_…` key bypasses the paywall.
