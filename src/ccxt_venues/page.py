"""The plugin's pages, under Manage: the data role's Connection and Datasets
(spec/plugin-pages-follow-their-role), as the SDK draws them for a pairs
venue (`meridian.roles.data.pairs`), for one venue at a time, chosen on the
page; and Venues, each venue on or off and what it serves.

A data plugin shows no market data (ruled 2026-10-03): no price, bar or
candle is on any page. Each page declares the record it renders (`answers=`),
so each is a read tool on the deployment's MCP surface answering the same
record: `read_connection` and `read_datasets` for a venue (`venue`, the
first one on where none is named), and `read_venues`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import meridian
from meridian import Figure
from meridian.roles.data import pairs

from .declared import CATALOGUE, catalogue_of
from .venues import BY_ID, CCXT_VERSION, VENUES

TITLE = "CCXT venues"
#: The kit the pages are built against.
KIT = "0.12.0"
#: What each venue entitles this plugin to: its public market data, no key.
ENTITLED = "Public market data, no key"

pages = meridian.Pages(TITLE, templates=Path(__file__).parent / "templates", kit=KIT)


@dataclass(frozen=True)
class Chosen:
    """Which venue a page or its tool answers for, by CCXT id; the first one
    on where empty."""

    venue: str = field(
        default="",
        metadata={"description": "The venue, by its CCXT id: " + ", ".join(BY_ID)},
    )


@dataclass(frozen=True)
class VenueRow:
    """One venue: on or off, what it serves, and how it is reached."""

    venue: str
    ccxt_id: str
    ccxt_version: str
    on: bool
    serves: str
    not_served: str
    markets: str
    day: str
    reach: str
    listed: int


@dataclass(frozen=True)
class VenuesRead:
    """Venues' record (`read_venues`): each venue, and whether any is on."""

    venues: list[VenueRow]
    on: bool


class _Held:
    lake: Any = None


HELD = _Held()


def hold(lake: Any) -> None:
    """The work the pages show: the plugin's data role class (feed.Lake)."""
    HELD.lake = lake


def _enabled() -> set[str]:
    return set(HELD.lake.enabled) if HELD.lake is not None else set()


def _chosen(asked: str) -> str:
    """The venue asked for, else the first one on, else the first."""
    if asked in BY_ID:
        return asked
    on = [v.id for v in VENUES if v.id in _enabled()]
    return on[0] if on else VENUES[0].id


def _feed(venue: str) -> pairs.Feed | None:
    lake = HELD.lake
    return None if lake is None else lake.feeds.get(venue)


def _choice(venue: str) -> dict[str, Any]:
    on = _enabled()
    return {
        "choices": [{"id": v.id, "name": v.name, "on": v.id in on} for v in VENUES],
        "chosen": venue,
        "on": venue in on,
        "name": BY_ID[venue].name,
    }


def connection_now(venue: str = "") -> pairs.ConnectionRead:
    chosen = _chosen(venue)
    return pairs.connection_read(_feed(chosen), BY_ID[chosen].name, ENTITLED)


def datasets_now(venue: str = "", instance: str = "ccxt") -> pairs.DatasetsRead:
    chosen = _chosen(venue)
    return pairs.datasets_read(_feed(chosen), catalogue_of(chosen), instance, ENTITLED)


def venues_now() -> VenuesRead:
    on = _enabled()
    rows = []
    for venue in VENUES:
        feed = _feed(venue.id)
        listed = len(feed.products.listed) if feed is not None else 0
        rows.append(
            VenueRow(
                venue=venue.name,
                ccxt_id=venue.id,
                ccxt_version=CCXT_VERSION,
                on=venue.id in on,
                serves=", ".join(f"{venue.id}_{d}" for d in venue.offers),
                not_served=" ".join(f"{k}: {why}" for k, why in venue.not_offered.items()),
                markets=" and ".join(
                    {"spot": "spot", "swap": "perpetual swaps (last, bid and ask)"}[t]
                    for t in venue.types
                ),
                day="Etc/UTC, ends 00:00",
                reach=venue.reach,
                listed=listed,
            )
        )
    return VenuesRead(venues=rows, on=bool(on))


@pages.page(
    "/", "Connection", levels="admin", params=Chosen, answers=pairs.ConnectionRead,
    name="read_connection",
)  # fmt: skip
def connection(request: meridian.Request) -> meridian.Response:
    """How the plugin reaches the venue chosen: the mode, no key needed, what
    the venue entitles it to, the venue master's ID it resolved and the
    endpoints; its limits and what CCXT spends of them, its calls, the last
    call and the last error."""
    asked = _asked(request)
    chosen = _chosen(asked)
    return pages.answer("connection.html", connection_now(chosen), **_choice(chosen))


@pages.page(
    "/datasets", "Datasets", levels="admin", params=Chosen, answers=pairs.DatasetsRead,
    name="read_datasets",
)  # fmt: skip
def datasets(request: meridian.Request) -> meridian.Response:
    """What the plugin serves the lake from the venue chosen: each of its
    datasets and whether it is licensed, what it recorded and declined; the
    wants it heard and the standing wants it keeps current; whether it may
    read an instrument's record; and the venue's product map."""
    chosen = _chosen(_asked(request))
    instance = request.plugin.identity.instance_id if request.plugin is not None else "ccxt"
    record = datasets_now(chosen, instance)
    return pages.answer("datasets.html", record, venue=BY_ID[chosen].name, **_choice(chosen))


@pages.page("/venues", "Venues", levels="admin", answers=VenuesRead, name="read_venues")
def venues(request: meridian.Request) -> meridian.Response:
    """Each venue the plugin reaches through CCXT: on or off, the datasets it
    serves and those it does not, with why; the markets read, its day, how
    far its public API reaches, and the markets it lists."""
    return pages.answer("venues.html", venues_now())


def _asked(request: meridian.Request) -> str:
    held: Any = request.params
    named = held.venue if isinstance(held, Chosen) else ""
    return named or str(request.query.get("venue", ""))


def figures_now() -> list[Figure]:
    """The data role's figures on the Summary, in its order, for the first
    venue on: Connection, Entitled at the vendor, Stream and Last recorded."""
    chosen = _chosen("")
    return pairs.figures_read(_feed(chosen), CATALOGUE)
