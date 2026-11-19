"""Each venue's side of the data suite: this plugin's synthetic exchange for
the venue, named for what each case asks a source to present.

tests/test_venue_suite.py runs the SDK's data suite unchanged, once per venue
(`meridian.suites.run` over `meridian.roles.data.testing.pairs_producers`),
against this plugin's own conversion: each answer comes through the venue's
real CCXT class, kept as a raw record and read from its text, from the
synthetic exchanges this package carries (`src/ccxt_venues/synthetic/`),
shaped as each venue sends its answers, with invented values. No live
network: CCXT's session answers from the synthetic exchange alone.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from meridian.edge import RawStore
from meridian.roles.data.pairs import Socket

from ccxt_venues.market import CcxtMarket
from ccxt_venues.transport import Replay, made
from ccxt_venues.venues import BY_ID

PACKAGE = Path(__file__).parent.parent / "src" / "ccxt_venues"
SYNTHETIC = PACKAGE / "synthetic"
#: The plugin's own modules no float may reach.
CONVERSION = (PACKAGE / "read.py", PACKAGE / "market.py")

#: The suite's clock: 2026-10-10 12:00 UTC, the day still forming.
NOW_NS = 1_791_633_600 * 1_000_000_000
TODAY = date(2026, 10, 10)
#: A day whose candles are complete.
CLOSED = date(2026, 10, 8)
TODAY_S = 1_791_590_400
#: The forming day's candle, as read twice while it fills: open, high, low,
#: close, volume.
FORMING = [
    ("61988.9", "62200.0", "61900.0", "62010.3", "120.5"),
    ("61988.9", "62300.0", "61850.0", "62155.8", "240.25"),
]

_TRADES = "this stage serves no trades: they come with the venue's stream, later"
_QUOTES = "live records prices -- last, bid and ask -- never a quote, in this stage"
#: What no venue presents in this stage, each with why (a case about a kind
#: of data the plugin never publishes yet, or a field no venue states here).
NOT_PRESENTED: dict[str, str] = {
    **{
        case: _TRADES
        for case in (
            "a-trade-recorded",
            "the-takers-side-stated",
            "the-makers-side-inverted",
            "a-condition-converted",
            "a-condition-not-converted",
            "a-trade-withdrawn",
            "a-standing-want-streamed",
            "a-restarts-gap-backfilled",
            "queries-the-lake-within-bounds",
        )
    },
    **{
        case: _QUOTES
        for case in (
            "a-quote-recorded",
            "a-one-sided-quote",
            "a-crossed-quote-is-recorded-invalid",
            "a-duplicate-is-recorded-suspicious",
            "rows-after-a-gap-are-suspicious",
        )
    },
    "records-a-datasets-liveness": "it polls each venue's REST API; it streams nothing yet",
    "reports-its-feed-delay": "it polls each venue's REST API; no streamed row to age yet",
    "reads-a-calendar": "crypto venues trading 24/7: it reads no settlement calendar",
    "asks-for-a-settlement-date": "records prices and bars as each venue states them; never "
    "computes a settlement date",
    "records-an-outcome": "these venues' markets read are no event contracts: no outcome",
    "restates-a-disputed-outcome": "no event contract read: no outcome disputed",
    "records-a-partial-payout": "no event contract read: no payout to settle",
    "reports-an-event-group": "no event contract read: no event to group",
    "reports-a-flag-the-venue-does-not-state": "no event contract read: no event's flags",
}
_NO_FX = "the venue lists no market of one currency priced in another"


def _numbers(body: Any) -> str:
    """JSON with each Decimal written as the number it was read from, as a
    venue sending JSON numbers (Deribit) sends it."""
    marked = json.dumps(body, default=lambda value: f"\0{value}\0", separators=(",", ":"))
    return re.sub(r'"\\u0000([^"]*)\\u0000"', r"\1", marked)


def _forming(venue: str, body: Any, reading: tuple[str, ...]) -> Any:
    """A daily answer with the forming day's candle added, as `venue` states one."""
    o, h, low, c, v = reading
    ms = TODAY_S * 1000
    if venue == "okx":
        body["data"].insert(0, [str(ms), o, h, low, c, v, "0", "0", "0"])
    elif venue == "bybit":
        body["result"]["list"].insert(0, [str(ms), o, h, low, c, v, "1"])
    elif venue == "binance":
        body.append([ms, o, h, low, c, v, ms + 86_399_999, "1", 8200, "1", "1", "0"])
    elif venue == "bitstamp":
        body["data"]["ohlc"].append(
            {"high": h, "timestamp": str(TODAY_S), "volume": v, "low": low, "close": c, "open": o}
        )
    elif venue == "deribit":
        result = body["result"]
        for column, value in (("ticks", ms), ("open", o), ("high", h), ("low", low),
                              ("close", c), ("volume", v), ("cost", "1")):  # fmt: skip
            result[column].append(Decimal(str(value)))
    elif venue == "hyperliquid":
        body.append({"t": ms, "T": ms + 86_399_999, "s": "@1", "i": "1d", "o": o, "c": c,
                     "h": h, "l": low, "v": v, "n": 8200})  # fmt: skip
    return body


@dataclass
class Case:
    """One venue's exchange and the suite's names for it."""

    VENUE: str
    BASE: str
    #: BASE's product the forming day is added to.
    FORMING_PRODUCT: str
    FX_BASE: str | None = None
    STABLE_BASE: str = ""
    EXACT_BASE: str = "TKN"
    BAR_BASE: str = "TKN"
    AMBIGUOUS: str = "PLY"
    ONE_SIDED_BASE: str = "TKN"
    #: A perpetual the venue lists, by the product this plugin names it.
    PERPETUAL: str = ""
    #: The last price, bid and ask each of BASE's products states now.
    LIVE: dict[str, tuple[str | None, str, str]] = field(default_factory=dict)
    NOW_NS: int = NOW_NS
    TODAY: date = TODAY
    CLOSED: date = CLOSED
    STREAM: Any = None
    STREAM_CASES: dict[str, str] = field(default_factory=dict)
    NOT_PRESENTED: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.STABLE_BASE = self.STABLE_BASE or self.BASE
        self.NOT_PRESENTED = {
            **NOT_PRESENTED,
            **({} if self.FX_BASE else {"an-fx-rate": _NO_FX}),
            **self.NOT_PRESENTED,
        }

    def held(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads((SYNTHETIC / f"{self.VENUE}.json").read_text())
        return loaded

    def market(self, now_ns: int = NOW_NS, forming: int | None = None) -> CcxtMarket:
        """The venue's synthetic exchange through its CCXT class, its answers
        kept in a fresh store; `forming` adds the forming day's candle to
        BASE's product, as read the first or second time."""
        venue = BY_ID[self.VENUE]
        replay = Replay.synthetic(self.VENUE)
        if forming is not None:
            for key, (status, text) in list(replay.answers.items()):
                if self._daily_of(key):
                    body = json.loads(text, parse_float=Decimal)
                    replay.answers[key] = (status, _numbers(_forming(
                        self.VENUE, body, FORMING[forming])))  # fmt: skip
        store = RawStore(Path(tempfile.mkdtemp(prefix=f"ccxt-{self.VENUE}-raw-")))
        exchange = made(venue.id, venue.options, store, replay=replay, clock_ns=lambda: now_ns)
        return CcxtMarket(venue, exchange, "synthetic", clock_ns=lambda: now_ns)

    def _daily_of(self, key: str) -> bool:
        product = self.FORMING_PRODUCT
        daily = ("candles", "kline", "klines", "ohlc", "chart_data", "candleSnapshot")
        named = product in key or product.lower() in key or product.replace("-", "") in key
        return named and any(d in key for d in daily)

    def replayed(self, messages: list[str]) -> Socket:
        raise NotImplementedError("this plugin streams nothing yet")


CASES = {
    case.VENUE: case
    for case in (
        Case(
            "okx",
            "BTC",
            "BTC-USDT",
            PERPETUAL="BTC-USDT-SWAP",
            LIVE={
                "BTC-USDT": ("61988.9", "61991.7", "61991.8"),
                "BTC-USDC": ("62006.75", "62007.1", "62007.4"),
            },
        ),
        Case(
            "bybit",
            "BTC",
            "BTCUSDT",
            PERPETUAL="linear/BTCUSDT",
            LIVE={
                "BTCUSDT": ("61988.9", "61991.7", "61991.8"),
                "BTCUSDC": ("62006.75", "62007.1", "62007.4"),
            },
        ),
        Case(
            "binance",
            "BTC",
            "BTCUSDT",
            PERPETUAL="linear/BTCUSDT",
            LIVE={
                "BTCUSDT": ("61988.9", "61991.7", "61991.8"),
                "BTCUSDC": ("62006.75", "62007.1", "62007.4"),
            },
        ),
        Case(
            "bitstamp",
            "BTC",
            "btcusd",
            FX_BASE="EUR",
            LIVE={
                "btcusd": ("61988.9", "61991.7", "61991.8"),
                "btcusdc": ("62006.75", "62007.1", "62007.4"),
            },
        ),
        Case(
            "deribit",
            "BTC",
            "BTC_USDC",
            PERPETUAL="BTC-PERPETUAL",
            LIVE={"BTC_USDC": ("62006.75", "62007.1", "62007.4")},
        ),
        Case(
            "hyperliquid",
            "UBTC",
            "@1",
            PERPETUAL="linear/BTC",
            LIVE={"@1": (None, "62007.1", "62007.4")},
            NOT_PRESENTED={
                "a-subject-another-source-resolved": (
                    "Hyperliquid lists no bitcoin: its UBTC is a token of its own, never named "
                    "by bitcoin's global identifier"
                )
            },
        ),
    )  # fmt: skip
}
