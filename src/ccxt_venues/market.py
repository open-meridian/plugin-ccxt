"""One venue's public market data through CCXT, read into the venue's values
the SDK's pairs feed works over (`meridian.roles.data.pairs.Market`).

**The listing** is CCXT's markets for the venue (`load_markets`), of the
types its catalogue entry reads: each spot market a product, its base priced
in its quote, each side by the venue's own code (CCXT's `baseId` and
`quoteId`); and each perpetual swap a product whose base is the perpetual
itself, known by the venue's own ID for it (`BTC-USDT-SWAP`), priced in its
quote (ruling 163: its last, bid and ask only, against the deployment's
record of that perpetual, which is incomplete until the contract carries
derivative terms). Dated futures and options are not read.

**Assets** (as Kraken's and Coinbase's plugins name theirs): a currency by
its ISO 4217 code where CCXT's code for it is one (`FIAT`); bitcoin and ether
by their SLIP-44 CAIP-19 (`NATIVE`), the only coins whose network a venue's
code fixes; every other token is the venue's own instrument, by its code
alone: a stablecoin is a token, never its currency.

**Figures** are read from each answer's own text (read.py), never from
CCXT's floats: a call is made through CCXT, and the raw records it kept are
read. A call is made one at a time on the venue's instance (`lock`).

**Not offered** is said, never faked: a venue whose public data states no
last price has none (`last_from` empty), and a method CCXT says the venue
lacks (`has` false, None or emulated) or that raises `NotSupported` is
`NotOffered`.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import Any

import ccxt
from meridian.roles.data import (
    NANOS_PER_SECOND,
    SECONDS_PER_DAY,
    Endpoint,
    Limits,
    Session,
    Unread,
    json_decimal,
    number,
)
from meridian.roles.data import Health as Health
from meridian.roles.data.pairs import Asset, Candle, Listed, Print, Socket, Tick, Top

from . import read
from .venues import Venue

#: CCXT's codes that are ISO 4217 currencies, among those these venues list.
FIAT = frozenset({"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "TRY", "BRL", "PLN"})
#: The coins whose network a venue's code fixes, by CCXT's code.
NATIVE = {
    "BTC": "bip122:000000000019d6689c085ae165831e93/slip44:0",
    "ETH": "eip155:1/slip44:60",
}
#: How long one ticker answer serves both its last price and its best bid and
#: ask: a pass asks each once.
TICKER_FRESH_NS = NANOS_PER_SECOND
NS_PER_MS = 1_000_000
#: A venue's ID for a perpetual that does not name it apart: letters and
#: digits alone.
BARE = re.compile(r"[A-Za-z0-9]+")


#: The CCXT methods called, by their unified names in `has`.
UNIFIED = {
    "fetch_ohlcv": "fetchOHLCV",
    "fetch_ticker": "fetchTicker",
    "fetch_order_book": "fetchOrderBook",
}


class NotOffered(Exception):
    """What the venue's public data does not state (see the module)."""


def offered(exchange: Any, method: str) -> bool:
    """Whether CCXT says the venue has `method` natively: `has` true. False,
    None (not unified in CCXT) and "emulated" are not offered."""
    return exchange.has.get(method) is True


class CcxtMarket:
    """One venue's market data, as the SDK's pairs feed asks for it."""

    def __init__(
        self,
        venue: Venue,
        exchange: Any,
        mode: str = "live",
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.entry, self.exchange, self.clock_ns = venue, exchange, clock_ns
        self.venue = venue.id
        self.venue_identifiers: tuple[tuple[str, str, str], ...] = (("symbol", venue.id, venue.id),)
        self.name = venue.name
        address = exchange.urls.get("www", "") if mode == "live" else ""
        api = exchange.urls.get("api")
        rest = api if isinstance(api, str) else next(iter((api or {}).values()), "")
        self.session = Session(
            mode=mode,
            endpoints=(
                Endpoint(
                    "REST",
                    str(rest) if mode == "live" else f"{mode}: no call leaves the deployment",
                    "markets, daily candles, ticker"
                    + (", book" if "book" in venue.top_from.values() else ""),
                ),  # fmt: skip
            ),
            limits=Limits(
                allowed=venue.allowed,
                spent=f"CCXT {exchange.version or ''} throttles to one request each "
                f"{exchange.rateLimit:g} ms".replace("CCXT  ", "CCXT "),
                most_candles=venue.most_candles,
                history_days=venue.history_days,
            ),
        )
        self.home = address
        #: Each product's market, by the venue's ID for it.
        self.markets: dict[str, dict[str, Any]] = {}
        #: Each product's last ticker read: when it arrived, what it stated,
        #: and its raw record.
        self._tickers: dict[str, tuple[int, read.Ticked, str]] = {}

    # ── Calls ─────────────────────────────────────────────────────────────

    def _call(self, live: bool, method: str, *args: Any) -> list[tuple[str, int]]:
        """One CCXT call, alone on the venue's instance; the raw records it
        kept, in order. A refusal is counted on the session's health and
        raised."""
        health = self.session.health
        unified = UNIFIED.get(method)
        if unified is not None and not offered(self.exchange, unified):
            raise NotOffered(
                f"{self.name}: CCXT says it has {unified} as "
                f"{self.exchange.has.get(unified)!r}, so it is not offered"
            )
        with self.exchange.lock:
            self.exchange.kept_now, self.exchange.as_line = [], live
            health.calls += 1
            try:
                getattr(self.exchange, method)(*args)
            except ccxt.NotSupported as lacking:
                raise NotOffered(f"{self.name}: {method} is not offered ({lacking})") from None
            except ccxt.RateLimitExceeded as limited:
                health.rate_limited += 1
                self._failed(f"{method}: {limited}")
                raise
            except Exception as failed:
                self._failed(f"{method}: {failed}")
                raise
            finally:
                kept: list[tuple[str, int]] = self.exchange.kept_now
                self.exchange.kept_now, self.exchange.as_line = [], False
        health.last_ok_ns = self.clock_ns()
        return kept

    def _failed(self, why: str) -> None:
        health = self.session.health
        health.failures += 1
        health.last_failed_ns = self.clock_ns()
        health.last_error = why[:200]

    def _body(self, key: str) -> Any:
        """A raw record's body, read exactly (`json_decimal`)."""
        record = self.exchange.store.get(key) if self.exchange.store is not None else None
        if record is None:
            raise ValueError(f"no raw record {key}")
        return json_decimal(str(record["body"]))

    def _kind(self, product: str) -> str:
        market = self.markets.get(product)
        if market is None:
            raise NotOffered(f"{self.name} lists no {product}")
        return "swap" if market.get("type") == "swap" else "spot"

    # ── The listing ───────────────────────────────────────────────────────

    def asset(self, code: str) -> Asset:
        """One of the venue's assets, by its own code: a currency or a native
        coin where that code is one's, never by CCXT's renaming of it (CCXT
        calls Hyperliquid's UBTC, a token, BTC)."""
        if code.upper() in FIAT:
            return Asset(code, "currency", "iso4217", code.upper())
        if code.upper() in NATIVE:
            return Asset(code, "token", "caip19", NATIVE[code.upper()])
        return Asset(code, "token")

    @staticmethod
    def own(market: dict[str, Any], side: str) -> str:
        """The venue's own code for a market's base or quote: its name where
        CCXT keeps one apart from its ID (Hyperliquid's tokens), else its ID."""
        return str(market.get(f"{side}Name") or market.get(f"{side}Id") or market[side])

    @staticmethod
    def own_id(market: dict[str, Any]) -> str:
        """The venue's own ID for a market: its name where CCXT's ID is an
        index (Hyperliquid's perpetuals), else CCXT's ID."""
        name = (market.get("info") or {}).get("name")
        if market.get("type") == "swap" and str(market["id"]).isdigit() and name:
            return str(name)
        return str(market["id"])

    def listing(self) -> list[Listed]:
        """Every spot market and perpetual swap the venue lists, by its ID."""
        self._call(False, "load_markets", True)
        listed: list[Listed] = []
        markets: dict[str, dict[str, Any]] = {}
        chosen = [m for m in self.exchange.markets.values() if self._read(m)]
        # A perpetual is known by the venue's own ID for it where that ID names
        # it apart (OKX's BTC-USDT-SWAP, Deribit's BTC-PERPETUAL); where it is
        # a bare word that a spot market or a coin could share (Bybit's and
        # Binance's BTCUSDT, Hyperliquid's BTC), prefixed by CCXT's sub-type and
        # a slash (linear/BTCUSDT), so a coin's record is never named as it.
        for market in chosen:
            product = self.own_id(market)
            quote = self.asset(self.own(market, "quote"))
            if market["type"] == "swap":
                if BARE.fullmatch(product):
                    product = f"{market.get('subType') or market['type']}/{product}"
                base = Asset(product, "token", name=f"{self.name} {market['symbol']} perpetual")
            else:
                base = self.asset(self.own(market, "base"))
            markets[product] = market
            active = market.get("active")
            listed.append(
                Listed(
                    product=product,
                    base=base,
                    quote=quote,
                    tradable=active is not False,
                    status="active" if active is not False else "inactive",
                )
            )
        self.markets = markets
        return sorted(listed, key=lambda p: p.product)

    def _read(self, market: dict[str, Any]) -> bool:
        """Whether a market is read: a spot market, or a perpetual swap,
        where the venue's entry reads its type, by CCXT's `type`: a dated
        future is "future", never read. (Deribit's spot markets are also
        marked `swap`, and its perpetuals carry an expiry in the year 3000.)"""
        return str(market.get("type")) in self.entry.types

    def perpetual(self, product: str) -> bool:
        return self.markets.get(product, {}).get("type") == "swap"

    # ── Daily candles ─────────────────────────────────────────────────────

    def candles(self, product: str, first: date, last: date) -> list[Candle]:
        """The product's daily candles from `first` to `last`, each read from
        the venue's text; a perpetual's are not read (ruling 163)."""
        if self.perpetual(product):
            raise NotOffered(f"{self.name}: a perpetual's daily candles are not read")
        market = self.markets.get(product)
        if market is None:
            raise NotOffered(f"{self.name} lists no {product}")
        start = int(datetime(first.year, first.month, first.day, tzinfo=UTC).timestamp())
        days = (last - first).days + 1
        limit = min(max(days, 1), self.entry.most_candles)
        kept = self._call(False, "fetch_ohlcv", market["symbol"], "1d", start * 1000, limit)
        reader = read.DAYS[self.venue]
        end = start + days * SECONDS_PER_DAY
        found: dict[int, Candle] = {}
        for key, _ in kept:
            for day in reader(self._body(key)):
                if start <= day.start_s < end:
                    found[day.start_s] = self._candle(product, day, key)
        return [found[s] for s in sorted(found)]

    def _candle(self, product: str, day: read.Day, key: str) -> Candle:
        unread = tuple(
            Unread(f"ohlcv.{name}", "") for name, value in (
                ("open", day.open), ("high", day.high), ("low", day.low),
                ("close", day.close), ("volume", day.volume)) if value is None
        )  # fmt: skip
        return Candle(
            product=product,
            start_s=day.start_s,
            open=day.open,
            high=day.high,
            low=day.low,
            close=day.close,
            volume=day.volume,
            vwap=None,
            trade_count=day.count,
            raw_key=f"{key}#{day.at}",
            unread=unread,
        )

    # ── Live ──────────────────────────────────────────────────────────────

    def _ticked(self, product: str, source: str) -> tuple[int, read.Ticked, str]:
        """The product's ticker or book, read now, or the ticker read within
        the second (one answer serves its last price and its bid and ask)."""
        now = self.clock_ns()
        held = self._tickers.get(product)
        if source == "ticker" and held is not None and now - held[0] < TICKER_FRESH_NS:
            return held
        symbol = self.markets[product]["symbol"]
        if source == "ticker":
            kept = self._call(True, "fetch_ticker", symbol)
            reader = read.TICKERS[self.venue]
        else:
            kept = self._call(True, "fetch_order_book", symbol, 5)
            reader = read.BOOKS[self.venue]
        if not kept:
            raise ValueError(f"{self.name}: {source} for {product} kept no answer")
        key, received = kept[-1]
        ticked = (received, reader(self._body(key)), key)
        if source == "ticker":
            self._tickers[product] = ticked
        return ticked

    def last(self, product: str) -> Tick:
        """The last trade's price, as the venue's ticker states it."""
        source = self.entry.last_from.get(self._kind(product), "")
        if not source:
            raise NotOffered(f"{self.name}'s public data states no last trade price")
        received, ticked, key = self._ticked(product, source)
        price = number(ticked.last)
        return Tick(
            product=product,
            price=price,
            at_ns=ticked.at_ms * NS_PER_MS if ticked.at_ms else received,
            stated=bool(ticked.at_ms),
            ident=str(ticked.at_ms) if ticked.at_ms else key.rsplit("/", 1)[-1],
            raw_key=key,
            unread=() if price is not None else (Unread("ticker.last", str(ticked.last)),),
        )

    def top(self, product: str) -> Top:
        """The best bid and ask with their sizes where stated; a side with no
        order is None."""
        source = self.entry.top_from.get(self._kind(product), "")
        if not source:
            raise NotOffered(f"{self.name}'s public data states no best bid and ask")
        received, ticked, key = self._ticked(product, source)
        unread: list[Unread] = []
        sides: list[Any] = []
        for side, size in (("bid", ticked.bid_size), ("ask", ticked.ask_size)):
            stated = getattr(ticked, side)
            price = number(stated) if stated not in (None, "") else None
            if stated not in (None, "") and price is None:
                unread.append(Unread(f"{source}.{side}", str(stated)))
            sides.append((price, number(size) if price is not None and size else None))
        return Top(
            product=product,
            bid=sides[0][0],
            ask=sides[1][0],
            at_ns=ticked.at_ms * NS_PER_MS if ticked.at_ms else received,
            stated=bool(ticked.at_ms),
            ident=str(ticked.at_ms) if ticked.at_ms else key.rsplit("/", 1)[-1],
            raw_key=key,
            unread=tuple(unread),
            bid_size=sides[0][1],
            ask_size=sides[1][1],
        )

    # ── Not served in stage A ─────────────────────────────────────────────

    def trades(self, product: str, since_ns: int = 0) -> list[Print]:
        raise NotOffered(f"{self.name}: trades are not served yet")

    @property
    def stream_address(self) -> str:
        return ""

    async def connect(self, address: str) -> Socket:
        raise NotOffered("this plugin streams nothing yet")

    def subscriptions(self, names: Sequence[str]) -> list[str]:
        return []

    def heard(self, text: str, received_ns: int) -> list[Print | Top]:
        return []


def stated(exchange: Any) -> dict[str, Any]:
    """What CCXT says of a venue: its `has`, and its `features` for spot and
    swap, as JSON holds them (`venues.json`)."""
    features = exchange.features or {}
    said: dict[str, Any] = json.loads(
        json.dumps(
            {
                "has": dict(sorted(exchange.has.items())),
                "features": {k: features.get(k) for k in ("spot", "swap") if k in features},
            },
            default=str,
        )
    )
    return said
