"""Crypto venues' public market data through CCXT, as an Open Meridian data
plugin.

It runs its data role class, `Lake` (feed.py) -- one SDK pairs feed per venue
of its catalogue (venues.py), each over that venue's CCXT instance
(transport.py, market.py) -- on the sidecar it is launched beside, declaring
its catalogue, its storage and its settings (declaration.py) and its pages
(page.py), which `meridian.run` serves. Each venue a deployment admin turns
on in Settings maps its markets to the deployment's instruments, hears what
the lake wants of it and records it, and keeps each standing want current,
until stopped. Everything goes through the sidecar; nothing but each enabled
venue's public REST API is called, through CCXT, and with sample data not
even that.

It holds nothing it cannot lose: each venue's raw responses and product map
are kept in the storage the deployment grants it (decisions/028), and a
restart reads each map back and hears again what the lake wants.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import meridian
from meridian.edge import RawStore, storage_root
from meridian.roles.data.pairs import ProductMap

from .declaration import DECLARATION, PORT
from .declared import BROKER_TAGS, KIND, SAMPLE_DATA, WINDOW_DAYS, venue_setting
from .feed import Lake, VenueFeed
from .market import CcxtMarket
from .page import figures_now, hold, pages
from .transport import Replay, attribution, made
from .venues import VENUES, Venue

log = logging.getLogger("ccxt_venues")

#: Where a developer's recorded exchanges are replayed from, under the
#: plugin's storage, when `make e2e-recorded` mounts them there.
RECORDED = "recorded"
#: How often its datasets' licences are read again and its health said.
HEALTH_EVERY_SECONDS = 60


def market(venue: Venue, store: RawStore, synthetic: bool, broker_tags: bool = False) -> CcxtMarket:
    """The venue itself, or with sample data its answers from files: a
    developer's recorded exchanges where storage holds them, else this
    package's synthetic ones."""
    if not synthetic:
        exchange = made(venue.id, venue.options, store, broker_tags=broker_tags)
        return CcxtMarket(venue, exchange, "live")
    recorded = store.root / RECORDED
    if recorded.is_dir():
        replay, mode = Replay.recorded(recorded, venue.id), "recorded"
    else:
        replay, mode = Replay.synthetic(venue.id), "synthetic"
    exchange = made(venue.id, venue.options, store, replay=replay, broker_tags=broker_tags)
    return CcxtMarket(venue, exchange, mode)


def product_map(store: RawStore, venue: Venue, mode: str) -> ProductMap:
    held = ProductMap(store.root / f"products-{venue.id}-{mode}.json")
    held.load()
    return held


class Plugin:
    """The plugin's settings applied to its data role class: sample data
    switched, venues turned on and off, CCXT's attribution set, and raw
    responses moved past their window."""

    def __init__(self, lake: Lake, store: RawStore) -> None:
        self.lake, self.store = lake, store
        self.synthetic = False

    async def on_settings(self, delivered: Any) -> None:
        values = delivered.values
        synthetic = values.get(SAMPLE_DATA) is True
        tags = values.get(BROKER_TAGS) is True
        on = {v.id for v in VENUES if values.get(venue_setting(v.id)) is True}
        log.info("settings delivered: sample data %s, venues on %s", synthetic, sorted(on))
        for venue in VENUES:
            feed = self.lake.feeds[venue.id]
            if synthetic != self.synthetic:
                chosen = market(venue, self.store, synthetic, tags)
                feed.use(chosen, product_map(self.store, venue, chosen.session.mode))
            current = feed.market
            assert isinstance(current, CcxtMarket)
            attribution(current.exchange, tags)
        self.synthetic = synthetic
        self.lake.enable(on)
        window = values.get(f"{KIND}_window_days")
        past = values.get(f"{KIND}_past_window")
        await self.store.tend(
            self.lake.plugin,
            window if isinstance(window, int) else WINDOW_DAYS,
            past if isinstance(past, str) else "kept",
            datetime.now(UTC).date(),
        )

    async def health(self) -> None:
        """Each minute: each venue's datasets' licences read again (contract
        v20), and on its health whether each enabled venue answers."""
        import asyncio

        while True:
            try:
                await self.lake.read_licences()
            except meridian.MeridianError as failed:
                log.warning("licences not read: %s", failed)
            failing = []
            for venue in sorted(self.lake.enabled):
                health = self.lake.feeds[venue].market.session.health
                if health.last_failed_ns > health.last_ok_ns:
                    failing.append(f"{venue}: {health.last_error}")
            detail = "; ".join(failing) or f"{len(self.lake.enabled)} venues on, answering"
            try:
                await self.lake.plugin.report(healthy=not failing, detail=detail[:200])
            except (meridian.MeridianError, ValueError) as failed:
                log.warning("health not reported: %s", failed)
            await asyncio.sleep(HEALTH_EVERY_SECONDS)


class Running(Lake):
    """`Lake`, its health said each minute beside each venue's work."""

    held: Plugin | None = None

    async def run(self) -> None:
        import asyncio

        assert self.held is not None
        await asyncio.gather(super().run(), self.held.health())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    store = RawStore(storage_root(), KIND)
    lake = Running()
    for venue in VENUES:
        chosen = market(venue, store, synthetic=False)
        lake.feeds[venue.id] = VenueFeed(
            chosen, product_map(store, venue, "live"), owner=lake, clock_ns=time.time_ns
        )
    plugin = Plugin(lake, store)
    lake.held = plugin
    hold(lake)
    meridian.run(
        declaration=DECLARATION,
        roles=[lake],
        pages=pages,
        port=PORT,
        on_settings=plugin.on_settings,
        figures=figures_now,
    )


if __name__ == "__main__":
    main()


__all__ = ["Path", "main"]
