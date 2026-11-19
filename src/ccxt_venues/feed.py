"""The data role's work, for every venue at once: one SDK pairs feed per venue
(`VenueFeed`, `meridian.roles.data.pairs.Feed` over that venue's
`CcxtMarket`), held by the plugin's one data role class (`Lake`), which hands
each want to the feed whose dataset it names.

**Datasets per venue.** Each venue's datasets are its own catalogue entries,
keyed `<venue>_<dataset>` (`okx_daily`, `okx_live`), each naming the venue as
its vendor, so a deployment licenses, prioritises and keeps each venue apart,
and a dedicated plugin for one venue can later take priority over it through
the deployment's source priorities. A feed's own bookkeeping says `daily` and
`live`, as the SDK's feed does; `VenueWants` names them as the lake does.

**What a feed serves** (rulings 162 and 163): a spot market's daily close and
bar, and its last price and best bid and ask; a perpetual's last price and
best bid and ask only, never its daily candles (declined `not_covered`).
`live` records prices -- last, bid and ask -- never a quote, and no trades
are served yet: a want of either is not covered.

**A venue left off** in Settings (`venue_<id>`, off by default) answers
nothing: its wants are declined `not_covered`, it is never called, and its
feed's work is not run. Turning it on starts its work; turning it off stops
it, its standing wants kept for when it is on again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from meridian.roles import data
from meridian.roles.data._wants import Wants
from meridian.roles.data.pairs import DAILY, LIVE, Feed

from .market import CcxtMarket

log = logging.getLogger("ccxt_venues")

PRICE = "meridian.v1.Price"
BAR = "meridian.v1.Bar"


@dataclass
class VenueWants(Wants):
    """A venue's wants, its datasets named `<instance>:<venue>_<key>`: the
    SDK's bookkeeping, keyed as the SDK's pairs feed keys it (`daily`,
    `live`), named as the lake names it."""

    prefix: str = ""

    def _plain(self, key: str) -> str:
        return key.removeprefix(self.prefix)

    def dataset(self, key: str) -> str:
        return f"{self.role.plugin.identity.instance_id}:{self.prefix}{self._plain(key)}"

    def key_of(self, dataset: str) -> str:
        instance, _, key = dataset.partition(":")
        if instance != self.role.plugin.identity.instance_id or not key.startswith(self.prefix):
            return ""
        return key[len(self.prefix) :]

    def sent_to(self, key: str) -> Any:
        return super().sent_to(self._plain(key))


@dataclass(eq=False)
class VenueFeed(Feed):
    """One venue's work: the SDK's pairs feed over its `CcxtMarket`, its
    datasets named for the venue, bound to the plugin's one data role class
    (`owner`), through which it acts."""

    owner: Any = None
    offers: tuple[str, ...] = (DAILY, LIVE)

    def __post_init__(self) -> None:
        super().__post_init__()
        held = self.wants
        self.wants = VenueWants(
            self, self.offers, clock_ns=self.clock_ns, prefix=f"{self.market.venue}_"
        )
        self.wants.latency, self.wants.session = held.latency, held.session

    @property
    def plugin(self) -> Any:
        """The connection the plugin's data role class was registered on: a
        venue's feed acts through it, as that class."""
        if self.owner is not None:
            return self.owner.plugin
        return super().plugin

    @staticmethod
    def _serves(key: str, data_type: str, kinds: tuple[int, ...]) -> bool:
        """The SDK's feed's, but a quote: `live` records prices alone."""
        if key == LIVE and data_type == "meridian.v1.Quote":
            return False
        return key in (DAILY, LIVE) and Feed._serves(key, data_type, kinds)

    async def record_days(
        self,
        subjects: Any,
        first: date,
        last: date,
        data_type: str = "",
        want_id: str = "",
    ) -> dict[str, str]:
        """The SDK's, a perpetual's subject declined `not_covered`: its daily
        candles are not read (ruling 163)."""
        await self.ensure_mapped()
        subjects = list(subjects)
        await self.name(subjects)
        market = self.market
        assert isinstance(market, CcxtMarket)
        served = self.products.for_subjects(subjects)
        perps = {
            s for s, products in served.items()
            if products and all(market.perpetual(m.product) for m in products)
        }  # fmt: skip
        declined = {s: "not_covered" for s in perps}
        rest = [s for s in subjects if s not in perps]
        if rest:
            declined.update(await super().record_days(rest, first, last, data_type, want_id))
        return declined


@dataclass(eq=False)
class Lake(data.Role):
    """The plugin's data role class: every venue's feed, each want handed to
    the feed whose dataset it names, and each enabled venue's work run."""

    feeds: dict[str, VenueFeed] = field(default_factory=dict)
    #: The venues a deployment admin has enabled, by CCXT id.
    enabled: set[str] = field(default_factory=set)
    _running: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    _changed: asyncio.Event = field(default_factory=asyncio.Event)

    def feed_of(self, dataset: str) -> VenueFeed | None:
        """The feed one of the plugin's datasets is a venue's, if any."""
        return next((f for f in self.feeds.values() if f.wants.key_of(dataset)), None)

    async def on_observations_wanted(self, heard: Any) -> None:
        """A want handed to its venue's feed; a venue left off declines it
        `not_covered`, counted on its feed."""
        feed = self.feed_of(heard.message.dataset)
        if feed is None:
            log.warning("a want of %s, no dataset of this plugin", heard.message.dataset)
            return
        if feed.market.venue not in self.enabled:

            async def off(want: Any, key: str, subjects: list[str], kinds: Any) -> dict[str, str]:
                return {s: "not_covered" for s in subjects}

            await feed.wants.hear(heard, off)
            return
        await feed.on_observations_wanted(heard)

    async def on_want_withdrawn(self, heard: Any) -> None:
        for feed in self.feeds.values():
            await feed.on_want_withdrawn(heard)

    async def read_licences(self) -> None:
        """Each venue's datasets' licences (contract v20), read for each feed."""
        for feed in self.feeds.values():
            await feed.read_licences()

    def enable(self, venues: set[str]) -> None:
        """The venues to run, as Settings say: started and stopped by `run`."""
        if venues != self.enabled:
            self.enabled = set(venues)
            self._changed.set()

    async def run(self) -> None:
        """Each enabled venue's feed run, started and stopped as Settings
        enable it; until cancelled."""
        try:
            while True:
                for venue, task in list(self._running.items()):
                    if venue not in self.enabled or task.done():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await task
                        del self._running[venue]
                for venue in sorted(self.enabled):
                    if venue in self.feeds and venue not in self._running:
                        self._running[venue] = asyncio.create_task(self.feeds[venue].run())
                self._changed.clear()
                await self._changed.wait()
        finally:
            for task in self._running.values():
                task.cancel()
            self._running.clear()
