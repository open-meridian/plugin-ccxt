"""The pages as a deployment admin would see them, on synthetic data, each
printed as one HTML file: for looking at them without a deployment.

    python -m ccxt_venues.preview connection > preview/connection.html
    python -m ccxt_venues.preview datasets > preview/datasets.html
    python -m ccxt_venues.preview venues > preview/venues.html

The page links the kit where the dashboard serves it, /.meridian/ui/<version>/,
so serve it beside the kit to see it styled; opened on its own it is the page
without the kit, unstyled, which works too.

There is no sidecar here: the SDK's `Recorder` answers as one would, the
deployment holding a custodian's bitcoin and ether, OKX and Bybit turned on,
the others off, and the lake asking OKX for a week of closes and keeping
bitcoin's live prices current, so Datasets has wants to page through.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data import pairs
from meridian.roles.data.testing import Instruments, held
from meridian.suites import Recorder
from meridian.testing import PageClient

from .feed import Lake, VenueFeed
from .page import hold, pages
from .transport import Replay, made
from .venues import VENUES

INSTANCE = "ccxt"
#: 2026-10-10 12:00 UTC.
NOW_NS = 1_791_633_600 * 1_000_000_000


async def worked(on: frozenset[str] = frozenset({"okx", "bybit"})) -> tuple[Lake, Recorder]:
    """The plugin after the lake asked OKX for a week of closes and bitcoin's
    live prices, standing; `on` the venues turned on."""
    import tempfile
    from pathlib import Path

    from meridian.edge import RawStore

    from .market import CcxtMarket

    recorder = Recorder(INSTANCE)
    store = Instruments().answering(recorder)
    lake = Lake()
    recorder.bind(lake)
    for venue in VENUES:
        raw = RawStore(Path(tempfile.mkdtemp(prefix="ccxt-preview-")))
        exchange = made(venue.id, venue.options, raw, replay=Replay.synthetic(venue.id),
                        clock_ns=lambda: NOW_NS)  # fmt: skip
        market = CcxtMarket(venue, exchange, "synthetic", clock_ns=lambda: NOW_NS)
        lake.feeds[venue.id] = VenueFeed(market, pairs.ProductMap(), clock_ns=lambda: NOW_NS,
                                         owner=lake, offers=venue.offers)  # fmt: skip
    lake.enable(set(on))
    okx = lake.feeds["okx"]
    btc = await held(store, okx, "BTC")
    eth = await held(store, okx, "ETH")
    for want_id, dataset, extra in (
        ("WNT-D", "ccxt:okx_daily", {"valid_from_ns": NOW_NS - 6 * 86_400 * 10**9}),
        ("WNT-L", "ccxt:okx_live", {"standing": True}),
    ):
        event = ops.ObservationsWantedEvent(
            want_id=want_id, dataset=dataset, data_type="meridian.v1.Price",
            subjects=[ops.SubjectRef(entity_id=s) for s in (btc, eth)], **extra,
        )  # fmt: skip
        recorder.answer("ObservationsWanted", _answering(event))
        await recorder._hear({"ObservationsWanted": lake.on_observations_wanted})
    daily = ops.DatasetLicence(dataset="ccxt:okx_daily", kept=True)
    recorder.answer("ListDatasets", lambda _: ops.ListDatasetsResult(licences=[daily]))
    await lake.read_licences()
    return lake, recorder


def _answering(event: ops.ObservationsWantedEvent) -> Any:
    def answer(_: Any) -> ops.ObservationsWantedEvent:
        return event

    return answer


PATHS = {"connection": "/", "datasets": "/datasets", "venues": "/venues"}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in PATHS:
        print(f"usage: python -m ccxt_venues.preview {'|'.join(PATHS)}", file=sys.stderr)
        return 2
    lake, _ = asyncio.run(worked())
    hold(lake)
    answered: Any = PageClient(pages, deployment_admin=True).get(PATHS[argv[1]], "admin")
    sys.stdout.write(answered.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
