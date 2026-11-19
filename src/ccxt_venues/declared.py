"""What this version declares beside its role (W8.1, W4.1): its catalogue,
its storage and its settings.

**Its catalogue** (spec/the-lake, "The catalogue"): for each venue in the
catalogue (venues.py), its own datasets, each naming the venue as its vendor
(387), so each venue is licensed, prioritised and kept apart:

- `<venue>_daily`: each spot market's close and bar for a UTC day, its day
  ending at 00:00 UTC (`Etc/UTC`, end minute 0; each venue is asked for its
  UTC candle), pulled for what the lake wants and pushed for a standing
  want; `backfill`, since the venue serves its daily history.
- `<venue>_live`: the last trade's price and the best bid and ask as
  prices, at most once a second per subject and kind, pulled for the latest
  or kept current for a standing want, for spot markets and perpetual swaps
  alike (a perpetual's last, bid and ask only, ruling 163); `stream_only`,
  since a ticker as it stood is not served again. Hyperliquid's states no
  last price.

A dataset a venue does not offer is not declared, and the venue's entry says
why (`Venue.not_offered`). No dataset names an aggregator: CCXT is a library
this plugin runs, which carries nothing, and each venue is reached directly.

**Its terms and pricing** (contract 30, ruling 1032): no dataset declares a
licence; each describes its venue's terms, who may not use it and its reach
in plain words, with the sources and the date they were read
(`venues.described`). The deployment admin's licence on Data sources is the
one enforced.

**Its settings**, in the data role's order: one switch per venue
(`venue_<id>`, off by default: a deployment admin enables each), CCXT's
broker attribution (`broker_tags`, off by default; ruling 164), the
credentials a later stage reads for trading (declared secret, never read by
this version: stage A uses no key), and sample data, a developer's.
"""

from __future__ import annotations

import meridian
from meridian import DatasetDeclaration, Setting

from .venues import CCXT_VERSION, DAILY, LIVE, VENUES, described

SAMPLE_DATA = "sample_data"
BROKER_TAGS = "broker_tags"

#: Its one kind of raw record, each venue's answers as received: a month of
#: them by default. An admin sets the window in Settings.
KIND = "responses"
LABEL = "Raw responses"
WINDOW_DAYS = 30

#: The data types of each of a venue's datasets.
_TYPES = {
    DAILY: ["meridian.v1.Price", "meridian.v1.Bar", "meridian.v1.Bar.trade_count"],
    LIVE: ["meridian.v1.Price"],
}


def venue_setting(venue_id: str) -> str:
    """The setting that enables a venue."""
    return f"venue_{venue_id}"


def _dataset(venue: object, key: str) -> DatasetDeclaration:
    from .venues import Venue

    assert isinstance(venue, Venue)
    daily = key == DAILY
    types = list(_TYPES[key])
    if daily and venue.id not in ("binance", "hyperliquid"):
        types.remove("meridian.v1.Bar.trade_count")  # the venue states no trade count
    return DatasetDeclaration(
        key=f"{venue.id}_{key}",
        vendor=venue.name,
        data_types=types,
        modes=["pull", "push"],
        cadence=86_400 if daily else 1,
        history=venue.history_days if daily else 0,
        terms_and_pricing=described(venue),
        gap_recovery="backfill" if daily else "stream_only",
        day_time_zone="Etc/UTC",
        day_end_minute=0,
    )


CATALOGUE = [_dataset(venue, key) for venue in VENUES for key in venue.offers]


def catalogue_of(venue_id: str) -> list[DatasetDeclaration]:
    """One venue's datasets, as the catalogue declares them."""
    return [d for d in CATALOGUE if d.key.startswith(f"{venue_id}_")]


#: The credentials a later stage reads to trade, by venue: declared now, so a
#: deployment sees what stage B asks for; never read by this version.
STAGE_B_CREDENTIALS: dict[str, tuple[tuple[str, str], ...]] = {
    "okx": (("key", "API key"), ("secret", "API secret"), ("passphrase", "API passphrase")),
    "bybit": (("key", "API key"), ("secret", "API secret")),
    "bitstamp": (("key", "API key"), ("secret", "API secret")),
    "deribit": (("key", "Client ID"), ("secret", "Client secret")),
    "hyperliquid": (("key", "API wallet's private key"), ("address", "Main wallet address")),
    "binance": (("key", "API key"), ("secret", "API secret")),
}

SETTINGS: list[Setting] = [
    *[
        Setting(
            venue_setting(venue.id),
            bool,
            default=False,
            label=venue.name,
            description=(
                f"Read {venue.name}'s public market data through CCXT {CCXT_VERSION}. Off: its "
                f"datasets answer nothing. {venue.reach} Its terms and who may not use it are "
                "on Data sources."
            )[:500],
        )
        for venue in VENUES
    ],
    Setting(
        BROKER_TAGS,
        bool,
        default=False,
        label="CCXT broker attribution",
        description=(
            "Send CCXT's own broker tags with orders (OKX's tag, Bybit's Referer, KuCoin's "
            "partner, Gate's channel), which credit CCXT, at no cost to you. Off by default. "
            "This version places no orders."
        ),
    ),
    *[
        Setting(
            f"{venue}_{name}",
            str,
            secret=True,
            label=f"{dict((v.id, v.name) for v in VENUES)[venue]} {label}",
            description="For trading, in a later version. This version reads no key.",
        )
        for venue, held in STAGE_B_CREDENTIALS.items()
        for name, label in held
    ],
    meridian.sample_data(
        description=(
            "Answer from built-in made-up answers shaped as each venue sends them, or a "
            "developer's recorded ones, instead of calling any venue. Development deployments "
            "only."
        )
    ),
]
