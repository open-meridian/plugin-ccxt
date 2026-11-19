"""Each venue's answers, read from the text it sent: the one place a venue's
own field names are read (decisions/023: exact decimal for money).

CCXT parses every answer into floats. This plugin keeps each answer's text as
a raw record before CCXT reads it (transport.py), and reads its figures here,
with `json_decimal`, from the venue's own text: a figure the venue sends as a
string (OKX, Bybit, Binance, Bitstamp, Hyperliquid) is that string, and one
it sends as a JSON number (Deribit) is read from the number's own text,
never through a float. CCXT is used to reach the venue -- its addresses,
parameters, paging and rate limits, and its listing of markets -- never for
a figure.

Every reader takes the answer as `json_decimal` read it and gives the
venue's values as plain tuples of `Decimal | None`; a value that does not
read is `None`, and the caller keeps it as unread (`Unread`). A day's candle
must start at 00:00 UTC: each venue here is asked for its UTC day (OKX's
`1Dutc`, which CCXT asks for by default), and a candle that starts at any
other time is refused rather than dated wrongly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from meridian.roles.data import SECONDS_PER_DAY, number


@dataclass(frozen=True)
class Day:
    """One daily candle as the venue stated it: its start in UTC seconds, its
    open, high, low, close and volume (in the base asset), and its trade
    count where the venue states one."""

    start_s: int
    open: Any
    high: Any
    low: Any
    close: Any
    volume: Any
    count: int | None = None
    #: Where in the answer it was read: its position or its time.
    at: str = ""


@dataclass(frozen=True)
class Ticked:
    """The venue's ticker: its last trade's price, best bid and ask with
    their sizes, each as stated, and the time it states in milliseconds (0
    where it states none)."""

    last: Any = None
    bid: Any = None
    ask: Any = None
    bid_size: Any = None
    ask_size: Any = None
    at_ms: int = 0


def _ms(value: Any) -> int:
    """Milliseconds as a venue states them, a string or a number."""
    return int(Decimal(str(value)))


def _start(ms: Any) -> int:
    start = _ms(ms) // 1000
    if start % SECONDS_PER_DAY:
        raise ValueError(f"a daily candle at {start} does not start at 00:00 UTC")
    return start


def _day(start_s: int, figures: Any, count: int | None = None, at: str = "") -> Day:
    """A day from its start and its five figures, open to volume, each read
    from its text (`number`)."""
    o, h, low, c, v = (number(f) for f in figures)
    return Day(start_s, o, h, low, c, v, count=count, at=at)


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# ── Daily candles ─────────────────────────────────────────────────────────


def okx_days(body: Mapping[str, Any]) -> list[Day]:
    """`/api/v5/market/candles`: `data`, newest first, each `[ts, o, h, l, c,
    vol, volCcy, volCcyQuote, confirm]`, every figure a string; `vol` is in
    the base currency for a spot pair."""
    return [_day(_start(e[0]), e[1:6], at=str(e[0])) for e in body["data"]]


def bybit_days(body: Mapping[str, Any]) -> list[Day]:
    """`/v5/market/kline`: `result.list`, newest first, each `[startTime,
    open, high, low, close, volume, turnover]`, strings."""
    return [_day(_start(e[0]), e[1:6], at=str(e[0])) for e in body["result"]["list"]]


def binance_days(body: Any) -> list[Day]:
    """`/api/v3/klines`: oldest first, each `[open time, open, high, low,
    close, volume, close time, quote volume, trades, ...]`; figures strings,
    times and the trade count integers."""
    return [_day(_start(e[0]), e[1:6], count=_count(e[8]), at=str(e[0])) for e in body]


def bitstamp_days(body: Mapping[str, Any]) -> list[Day]:
    """`/api/v2/ohlc/{pair}/`: `data.ohlc`, oldest first, each an object of
    strings, its `timestamp` in seconds."""
    return [
        Day(
            _start(_ms(e["timestamp"]) * 1000),
            number(e.get("open")),
            number(e.get("high")),
            number(e.get("low")),
            number(e.get("close")),
            number(e.get("volume")),
            at=str(e["timestamp"]),
        )
        for e in body["data"]["ohlc"]
    ]


def deribit_days(body: Mapping[str, Any]) -> list[Day]:
    """`/public/get_tradingview_chart_data`: `result`, columns of JSON numbers
    -- `ticks` (milliseconds), `open`, `high`, `low`, `close`, `volume` --
    each read from its own text."""
    result = body["result"]
    return [
        _day(
            _start(tick),
            [result[c][i] for c in ("open", "high", "low", "close", "volume")],
            at=str(tick),
        )
        for i, tick in enumerate(result.get("ticks") or [])
    ]


def hyperliquid_days(body: Any) -> list[Day]:
    """`candleSnapshot`: oldest first, each `{t, T, s, i, o, c, h, l, v, n}`,
    figures strings, `n` the trade count."""
    return [
        Day(
            _start(e["t"]),
            number(e.get("o")),
            number(e.get("h")),
            number(e.get("l")),
            number(e.get("c")),
            number(e.get("v")),
            count=_count(e.get("n")),
            at=str(e["t"]),
        )
        for e in body
    ]


# ── Tickers and books ──────────────────────────────────────────────────────


def okx_ticker(body: Mapping[str, Any]) -> Ticked:
    """`/api/v5/market/ticker`: `data[0]`, strings."""
    item = body["data"][0]
    return Ticked(
        item.get("last"), item.get("bidPx"), item.get("askPx"), item.get("bidSz"),
        item.get("askSz"), _ms(item.get("ts") or 0),
    )  # fmt: skip


def bybit_ticker(body: Mapping[str, Any]) -> Ticked:
    """`/v5/market/tickers`: `result.list[0]`, strings; its time the answer's."""
    item = body["result"]["list"][0]
    return Ticked(
        item.get("lastPrice"), item.get("bid1Price"), item.get("ask1Price"),
        item.get("bid1Size"), item.get("ask1Size"), _ms(body.get("time") or 0),
    )  # fmt: skip


def binance_ticker(body: Mapping[str, Any]) -> Ticked:
    """`/api/v3/ticker/24hr` (spot: with the best bid and ask) or
    `/fapi/v1/ticker/24hr` (USDⓈ-M: the last price alone), strings."""
    return Ticked(
        body.get("lastPrice"), body.get("bidPrice"), body.get("askPrice"),
        body.get("bidQty"), body.get("askQty"), _ms(body.get("closeTime") or 0),
    )  # fmt: skip


def bitstamp_ticker(body: Mapping[str, Any]) -> Ticked:
    """`/api/v2/ticker/{pair}/`: strings, no sizes; its `timestamp` seconds."""
    return Ticked(
        body.get("last"), body.get("bid"), body.get("ask"),
        at_ms=_ms(body.get("timestamp") or 0) * 1000,
    )  # fmt: skip


def deribit_ticker(body: Mapping[str, Any]) -> Ticked:
    """`/public/ticker`: `result`, JSON numbers read from their text."""
    item = body["result"]
    return Ticked(
        item.get("last_price"), item.get("best_bid_price"), item.get("best_ask_price"),
        item.get("best_bid_amount"), item.get("best_ask_amount"),
        _ms(item.get("timestamp") or 0),
    )  # fmt: skip


def binance_book(body: Mapping[str, Any]) -> Ticked:
    """`/fapi/v1/depth`: `bids` and `asks`, `[price, quantity]` strings, best
    first; its time `T`, the transaction's, in milliseconds."""
    bids, asks = body.get("bids") or [], body.get("asks") or []
    return Ticked(
        None,
        bids[0][0] if bids else None,
        asks[0][0] if asks else None,
        bids[0][1] if bids else None,
        asks[0][1] if asks else None,
        _ms(body.get("T") or body.get("E") or 0),
    )


def hyperliquid_book(body: Mapping[str, Any]) -> Ticked:
    """`l2Book`: `levels`, bids then asks, each level `{px, sz, n}`, strings;
    its `time` in milliseconds."""
    levels = list(body.get("levels") or [])
    bids = levels[0] if levels else []
    asks = levels[1] if len(levels) > 1 else []
    return Ticked(
        None,
        bids[0]["px"] if bids else None,
        asks[0]["px"] if asks else None,
        bids[0]["sz"] if bids else None,
        asks[0]["sz"] if asks else None,
        _ms(body.get("time") or 0),
    )


#: Each venue's readers, by CCXT id: its daily candles, and the answer its
#: last price and its best bid and ask are read from (`ticker`, or `book`
#: where its ticker states no bid and ask).
DAYS: dict[str, Callable[[Any], list[Day]]] = {
    "okx": okx_days,
    "bybit": bybit_days,
    "binance": binance_days,
    "bitstamp": bitstamp_days,
    "deribit": deribit_days,
    "hyperliquid": hyperliquid_days,
}
TICKERS: dict[str, Callable[[Any], Ticked]] = {
    "okx": okx_ticker,
    "bybit": bybit_ticker,
    "binance": binance_ticker,
    "bitstamp": bitstamp_ticker,
    "deribit": deribit_ticker,
}
BOOKS: dict[str, Callable[[Any], Ticked]] = {
    "binance": binance_book,
    "hyperliquid": hyperliquid_book,
}
