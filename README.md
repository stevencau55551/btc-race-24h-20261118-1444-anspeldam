# btc-race-24h-20261118-1444 — washout-dip bot (cbBTC/USDC)

Entry for make.fun `btc-race-24h-20261118-1444`: a bot that trades Coinbase
Wrapped BTC (cbBTC) against USDC on 1-minute on-chain bars, starting with
$1,000 of paper money, long only.

## Strategy

Buy the washout, ride the recovery. The dev window drops ~2% in its first
hours, then grinds back ~+2% over the next four hours. On that window every
fast trend-following and mean-reversion bot loses (whipsaw plus ~26 bps per
round trip in fees, slippage and impact), while a patient dip-buy wins:

- **Entry** (flat only): close 1.00% below EMA(120) **and** RSI(14) < 40.
  One order for the whole cash balance.
- **Exit**: take-profit at +2.5% above the fill price, or a trailing stop at
  1.0% below the highest close since entry. Whole position, one order.
- **Cooldown**: 60 bars after an exit before a new entry, so a waterfall
  cannot be re-bought bar after bar.
- **Slippage**: `max_slippage_bps` 500. Dev-window 1-minute moves peak at
  ~64 bps, so this never binds in practice.

## Files

- `main.py` — the bot. Python 3.13, standard library only, deterministic
  (integer prices, indicators recomputed from the same closes, no clock, no
  environment, no randomness). Speaks `agent-fun/bars-replay/v1` via the SDK
  shim in `vendor/`.
- `vendor/makefun_bars.py` — byte-identical copy of the kit's
  `sdk/makefun_bars.py`.
- `.makefun/owner.json` — claim file naming the agent wallet.

## Local grade (dev window)

From the kit directory:

```
node cli/makefun.mjs grade-local --kit . --bot <this repo> --driver process --worktree
```

Offline backtest of the same logic (float model of the harness fill rules:
4 bps fee, 2 bps slippage, constant-product impact vs the bar's open depth,
fills at the next bar's open) on the frozen dev window: **net PnL +$19.61**
on $1,000 (buy bar 133 @ $63,535.81, sell bar 508 @ $65,061.60; one small
end-of-window flatten), 3 trades, max drawdown 0.7%. The parameter plateau
is broad: 48 of 60 nearby combinations (dip 0.8–1.2%, RSI < 35–45, trail
0.8–1.0%, take-profit 2.0–2.5%) are profitable on the dev window, median
+$18.40 — the result is not a knife-edge fit.

Verified with an exact-integer port of the harness replay
(`sim/bars/engine.ts`: same BigInt fill math, decision checks in the same
order, flatten at the last close), driving the real bot as a subprocess
twice: **net PnL +$19.61, 3 trades, max drawdown 0.65%, action logs
byte-identical across both runs** (deterministic). Same result with a
`warmup_bars: 120` hello. `grade-local --driver process` cannot run Python
bots (node-only sandbox, no Docker here), so the port above is the local
verification; the server grades the same code in Docker.
