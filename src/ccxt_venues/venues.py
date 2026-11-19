"""The venue catalogue: one entry per venue this plugin reaches through CCXT
(ruling 162), each with what a deployment admin needs to decide whether to
enable it. None is on by default; the admin enables each in Settings
(`venue_<id>`), and a venue left off answers nothing.

Each entry carries:

- its CCXT id and the CCXT version this plugin pins (`CCXT_VERSION`, exact,
  ruling 166), with a snapshot of what that version says the venue `has`
  and its `features` (`venues.json`, written from the pinned CCXT and
  checked against it by the tests, so a bump shows every change);
- the market types read (spot, and perpetual swaps: last, bid and ask only,
  ruling 163) and the day its daily candles are on;
- a reach note: where the venue's public API answers from;
- its terms and who may not use it, as the venue's own pages state them,
  each cited with the date it was read. That record is data for the
  deployment admin, shown on Data sources (the datasets' terms) and in the
  docs, never a gate in code: the deployment's licence is the one enforced.

Coinbase Exchange spot, Kraken spot, Polymarket and Kalshi are not served
through CCXT: their own plugins serve them (ruling 162).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

#: The CCXT this plugin is built and tested against, exactly (ruling 166):
#: pyproject.toml pins the same, and the tests hold the two together.
CCXT_VERSION = "4.5.93"
#: When the venues' terms and restricted lists below were read
#: (`ccxt-report.md`, §2.1 and §7).
READ_ON = "2026-11-18"

DAILY, LIVE, TRADES = "daily", "live", "trades"


@dataclass(frozen=True)
class Venue:
    """One venue reached through CCXT (see the module)."""

    #: CCXT's id for it, which is also its code as a `symbol`'s source.
    id: str
    name: str
    #: CCXT's options for it: which market types its listing reads.
    options: dict[str, Any]
    #: Which of CCXT's market types are read: "spot", and "swap" for its
    #: perpetuals (their last, bid and ask only).
    types: tuple[str, ...]
    #: Where its last price and its best bid and ask are read from: its
    #: "ticker", its "book", or "" where it states none publicly; by type
    #: where they differ.
    last_from: dict[str, str]
    top_from: dict[str, str]
    #: Its datasets, by key, and those it does not offer, each with why.
    offers: tuple[str, ...]
    not_offered: dict[str, str]
    #: The most daily candles one request answers, and how far back its
    #: history reaches in days (0: the venue states no bound).
    most_candles: int
    history_days: int
    #: What its public API allows, in its own documentation's words.
    allowed: str
    #: Where its public API answers from.
    reach: str
    #: Its terms and who may not use it, as read on READ_ON, with sources.
    terms: str
    restricted: str
    sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def keys(self) -> tuple[str, ...]:
        """Its datasets' keys in the catalogue: `<id>_<dataset>`."""
        return tuple(f"{self.id}_{d}" for d in self.offers)


_SPOT_AND_PERPS = ("spot", "swap")
_TRADES_LATER = "Its trades are not served yet: a later stage reads them, with their stream."

VENUES: tuple[Venue, ...] = (
    Venue(
        id="okx",
        name="OKX",
        options={"fetchMarkets": {"types": ["spot", "swap"]}},
        types=_SPOT_AND_PERPS,
        last_from={"spot": "ticker", "swap": "ticker"},
        top_from={"spot": "ticker", "swap": "ticker"},
        offers=(DAILY, LIVE),
        not_offered={TRADES: _TRADES_LATER},
        most_candles=300,
        history_days=0,
        allowed="Public market data by IP: candles 40 requests in 2 seconds",
        reach="Its public API answers from the United States and elsewhere.",
        terms=(
            "OKX API Agreement (updated 28 Jul 2026), section 9.4: market data solely for your "
            "own personal, non-commercial trading and account management; public access grants "
            "no right to redistribute; no competing data product; no AI training. Section 9.5: "
            "no rate-limit circumvention."
        ),
        restricted=(
            "Restricted locations: Afghanistan, Canada, Cuba, Hong Kong, Iran, India, Japan, "
            "Malaysia, Nepal, North Korea, Syria, Uzbekistan, Crimea, Donetsk, Luhansk, certain "
            "US jurisdictions incl. US territories. Partly: Australia (derivatives), Bahamas "
            "(retail), "
            "Brazil (derivatives, P2P), South Korea (derivatives, P2P), UK (derivatives, P2P), "
            "Russia (fiat). US persons are served by OKX US, a separate CCXT id."
        ),
        sources=(
            "https://www.okx.com/help/okx-api-agreement",
            "OKX's restricted-locations disclosure (updated 14 Nov 2026), section 3, "
            "on okx.com/help",
        ),
    ),
    Venue(
        id="bybit",
        name="Bybit",
        options={"fetchMarkets": {"types": ["spot", "linear"]}},
        types=_SPOT_AND_PERPS,
        last_from={"spot": "ticker", "swap": "ticker"},
        top_from={"spot": "ticker", "swap": "ticker"},
        offers=(DAILY, LIVE),
        not_offered={TRADES: _TRADES_LATER},
        most_candles=1000,
        history_days=0,
        allowed="600 requests in 5 seconds per IP",
        reach=(
            "Its public API refuses US IP addresses: a deployment or runner in the US gets no "
            "answer, and its wants are declined source_silent."
        ),
        terms=(
            "Bybit API Terms: you shall not repackage or resell the API or Service Data, nor "
            "commercially exploit the APIs (the current page could not be read; from an earlier "
            "survey)."
        ),
        restricted=(
            "Service restricted countries (updated 7 May 2026, Service Agreement 11.3): United "
            "States, Chinese Mainland, Hong Kong, Singapore, Canada, North Korea, Cuba, Iran, and "
            "others (the list was read only in part)."
        ),
        sources=(
            "https://www.bybit.com/en/legal/service-specific-terms/API-Terms",
            "https://bybit.com/en/help-center/article/Service-Restricted-Countries",
        ),
    ),
    Venue(
        id="bitstamp",
        name="Bitstamp",
        options={},
        types=("spot",),
        last_from={"spot": "ticker"},
        top_from={"spot": "ticker"},
        offers=(DAILY, LIVE),
        not_offered={TRADES: _TRADES_LATER},
        most_candles=1000,
        history_days=0,
        allowed="400 requests a second; 10,000 in 10 minutes",
        reach="Its public API answers from the United States and elsewhere.",
        terms=(
            "Bitstamp API: commercial use of its data needs a commercial use Data License "
            "Agreement (partners@bitstamp.net), under which commercial redistribution is allowed."
        ),
        restricted="Not stated on its API page. Licensed as a MiCA CASP in Luxembourg.",
        sources=("https://www.bitstamp.net/api/",),
    ),
    Venue(
        id="deribit",
        name="Deribit",
        options={},
        types=_SPOT_AND_PERPS,
        last_from={"spot": "ticker", "swap": "ticker"},
        top_from={"spot": "ticker", "swap": "ticker"},
        offers=(DAILY, LIVE),
        not_offered={TRADES: _TRADES_LATER},
        most_candles=1000,
        history_days=0,
        allowed="Credits: 500 a request, refilled at 10,000 a second, a pool of 50,000",
        reach="Its public API answers from the United States and elsewhere.",
        terms="Its terms of service state nothing on API or market data (the page read empty).",
        restricted=(
            "Its restricted-jurisdictions page could not be read; a search snippet of it names "
            "the United States and Japan among others."
        ),
        sources=(
            "https://www.deribit.com/kb/deribit-terms-of-service",
            "https://support.deribit.com/hc/en-us/articles/25944487427741-Restricted-Jurisdictions",
        ),
    ),
    Venue(
        id="hyperliquid",
        name="Hyperliquid",
        options={"fetchMarkets": {"types": ["spot", "swap"]}, "builderFee": False},
        types=_SPOT_AND_PERPS,
        last_from={"spot": "", "swap": ""},
        top_from={"spot": "book", "swap": "book"},
        offers=(DAILY, LIVE),
        not_offered={
            TRADES: (
                "Its public data states no trade history: CCXT's fetchTrades reads one wallet's "
                "fills, never the venue's trades."
            ),
            "live last": (
                "Its public data states no last trade price, only a mark and a mid, neither a "
                "trade: live records its best bid and ask alone."
            ),
        },
        most_candles=5000,
        history_days=0,
        allowed="REST weight 1,200 a minute per IP",
        reach="Its public API answers from the United States and elsewhere.",
        terms="Its terms could not be read (the page refused automated reads).",
        restricted="Not found: its terms page could not be read.",
        sources=("https://hyperliquid.xyz/terms",),
    ),
    Venue(
        id="binance",
        name="Binance",
        options={"fetchMarkets": {"types": ["spot", "linear"]}},
        types=_SPOT_AND_PERPS,
        last_from={"spot": "ticker", "swap": "ticker"},
        top_from={"spot": "ticker", "swap": "book"},
        offers=(DAILY, LIVE),
        not_offered={TRADES: _TRADES_LATER},
        most_candles=1000,
        history_days=0,
        allowed="Request weight per IP a minute; 429, then IP bans of 2 minutes to 3 days",
        reach=(
            "Its public API refuses some regions; a deployment in one gets no answer, and its "
            "wants are declined source_silent."
        ),
        terms=(
            "Binance Terms of Use (effective 27 Oct 2026), cl. 27: its material solely for "
            "non-commercial personal or internal business use; cl. 14.1.2(b): API access subject "
            "to separate API terms and its approval. Its bulk files on data.binance.vision are CC "
            "BY-NC-SA 4.0 and are not used by this plugin."
        ),
        restricted=(
            "Prohibited (list updated 5 Jan 2026): United States (incl. citizens); residents of "
            "Canada and the Netherlands; Cuba, North Korea, Iran, Crimea, the so-called DPR and "
            "LPR. Not a MiCA CASP; new EU services stopped 1 Jul 2026."
        ),
        sources=(
            "https://www.binance.com/en/about-legal/terms",
            "https://www.binance.com/en/legal/list-of-prohibited-countries/",
        ),
    ),
)

BY_ID = {venue.id: venue for venue in VENUES}


def snapshot() -> dict[str, Any]:
    """What the pinned CCXT says of each venue, as `venues.json` holds it:
    its version, and per venue `has` and `features`."""
    held: dict[str, Any] = json.loads(
        (resources.files("ccxt_venues") / "venues.json").read_text(encoding="utf-8")
    )
    return held


def described(venue: Venue) -> str:
    """The venue's terms and pricing for its datasets' catalogue entry (at
    most 2,000 characters): free and keyless, its terms, who may not use it,
    its reach, and the sources read."""
    text = (
        f"{venue.name}'s public market data, reached through CCXT {CCXT_VERSION} (MIT): free, "
        f"no key or account. Terms: {venue.terms} Who may not use it: {venue.restricted} "
        f"Reach: {venue.reach} Read {READ_ON}: {' '.join(venue.sources)}. Not legal advice."
    )
    return text[:2000]
