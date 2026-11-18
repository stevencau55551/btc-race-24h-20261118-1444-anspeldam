"""Washout-dip bot for btc-race-24h-20261118-1444 (cbBTC vs USDC, 1-minute bars).

Strategy: buy the washout, ride the recovery. The dev window falls ~2% in its
first hours, then grinds back ~+2% over the next four hours; fast trend and
mean-reversion bots all lose on it (whipsaw + ~26 bps per round trip), while a
patient dip-buy wins. Entry needs BOTH a deep dip and an oversold RSI, exits
are a take-profit and a trailing stop, and entries are rare (a few per window).

  - Entry (flat only): close < EMA(120) * (1 - 1.00%) AND RSI(14) < 40.
    Full size: the whole cash balance in one buy order.
  - Exit (holding): sell everything when close >= fill price * (1 + 2.5%),
    or when close <= peak-since-entry * (1 - 1.0%) (trailing stop).
  - Cooldown: no new entry within 60 bars of an exit, so one failed dip
    cannot be re-bought immediately in a waterfall.
  - The take-profit's reference is the buy's actual fill price, read from
    the next batch's fills; if that price were ever unseen, it falls back
    to the position's cost per unit (a few bps stricter, never looser).
  - max_slippage_bps 500: 1-minute BTC moves are at most ~64 bps on the dev
    window, so 500 bps never binds, yet it still guards against a wild open.

Deterministic: integer prices, float indicators recomputed from the same
closes every run, no clock, no environment, no randomness. One asset (CBBTC),
long only, at most one open position. Speaks agent-fun/bars-replay/v1 through
the kit SDK shim in vendor/ (byte-identical copy of sdk/makefun_bars.py).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
EMA_N = 120            # bars of the slow average the dip is measured against
RSI_N = 14             # bars of the oversold gauge
DIP_BPS = 100          # entry: close 1.00% below the EMA
RSI_MAX = 40           # entry: RSI(14) under 40
TAKE_PROFIT_BPS = 250  # exit: +2.5% above the fill price
TRAIL_BPS = 100        # exit: -1.0% below the peak close since entry
COOLDOWN_BARS = 60     # bars to wait after an exit before a new entry
MAX_SLIPPAGE_BPS = 500

closes = []            # CBBTC closes, raw price units (ints), one per bar
ema = None             # EMA(EMA_N) of closes, float
entry_px = None        # fill price of the open position, raw price units
peak = None            # highest close since entry, raw price units
last_exit_seq = None   # seq of the batch where the last exit was decided
pending_buy_id = None  # client_id of the buy order awaiting its fill


def rsi_14():
    """RSI(14) over the closes so far (mean gain / mean loss of the last 14
    one-bar changes), or None before 15 closes."""
    if len(closes) < RSI_N + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - RSI_N, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def on_batch(state, batch):
    global ema, entry_px, peak, last_exit_seq, pending_buy_id

    # Only learn from a batch that actually carries a CBBTC bar; a minute the
    # recorder missed leaves the last close standing, never a repeated bar.
    if not any(b["symbol"] == SYMBOL for b in batch["bars"]):
        return []
    close = state.close(SYMBOL)
    if close is None:
        return []

    # A buy decided on the previous bar fills at this bar's open; its fill
    # price (from the batch's fills) is the take-profit's reference.
    for fill in batch["fills"]:
        if fill["client_id"] == pending_buy_id and fill["status"] == "filled":
            entry_px = int(fill["price"])
            peak = entry_px
    pending_buy_id = None

    closes.append(close)
    k = 2.0 / (EMA_N + 1)
    ema = float(close) if ema is None else close * k + ema * (1.0 - k)

    if state.warming_up:
        return []

    holding = state.positions.get(SYMBOL)
    if holding is not None:
        if peak is None:
            peak = close
        # Fallback if the fill price was never seen (a fill whose client_id
        # did not match): derive the entry price from the position's cost
        # and quantity, so the take-profit still has a reference. Cost is
        # the notional spent, fees included, so this price sits a few bps
        # above the market fill price and the take-profit is slightly
        # stricter -- never looser.
        if entry_px is None:
            sym = state.symbols[SYMBOL]
            entry_px = (holding.cost * 10 ** (sym["qty_scale"] + sym["price_scale"])) // (
                holding.qty * 10 ** state.hello["capital"]["quote_scale"]) if holding.qty > 0 else None
        elif close > peak:
            peak = close
        # Take profit: close 2.5% above the fill price (integer comparison).
        if entry_px is not None and close * 10000 >= entry_px * (10000 + TAKE_PROFIT_BPS):
            last_exit_seq = state.seq
            entry_px = None
            peak = None
            return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        # Trailing stop: close 1.0% below the peak since entry.
        if peak is not None and close * 10000 <= peak * (10000 - TRAIL_BPS):
            last_exit_seq = state.seq
            entry_px = None
            peak = None
            return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    # Flat: wait for a washout dip with an oversold RSI.
    if len(closes) <= EMA_N:
        return []
    if last_exit_seq is not None and state.seq - last_exit_seq < COOLDOWN_BARS:
        return []
    rsi = rsi_14()
    if rsi is None or rsi >= RSI_MAX:
        return []
    if not close * 10000 < ema * (10000 - DIP_BPS):
        return []
    size = state.cash
    room = state.weight_room(SYMBOL)
    if room < size:
        size = room
    if size < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    cid = state.client_id()
    pending_buy_id = cid
    return [{"side": "buy", "symbol": SYMBOL, "client_id": cid,
             "notional_quote_units": size, "max_slippage_bps": MAX_SLIPPAGE_BPS}]


makefun_bars.run(on_batch)
