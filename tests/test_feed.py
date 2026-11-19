"""The plugin's one data role class over every venue's feed (feed.py): each
venue's datasets named for it, each want handed to its venue, a venue left
off declining, and its work run only while it is on."""

from __future__ import annotations

import asyncio

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data import pairs
from meridian.roles.data.testing import Instruments, held
from meridian.suites import Recorder

from ccxt_venues.declared import CATALOGUE
from ccxt_venues.feed import Lake, VenueFeed
from ccxt_venues.venues import VENUES

import venue_cases

INSTANCE = "ccxt"
NOW = venue_cases.NOW_NS


def _lake() -> tuple[Lake, Recorder, Instruments]:
    recorder = Recorder(INSTANCE)
    store = Instruments().answering(recorder)
    lake = Lake()
    recorder.bind(lake)
    for venue in VENUES:
        case = venue_cases.CASES[venue.id]
        lake.feeds[venue.id] = VenueFeed(case.market(), pairs.ProductMap(), clock_ns=lambda: NOW,
                                         owner=lake, offers=venue.offers)  # fmt: skip
    return lake, recorder, store


def _want(dataset: str, subject: str, **kw: object) -> ops.ObservationsWantedEvent:
    return ops.ObservationsWantedEvent(
        want_id="WNT-1", dataset=dataset, data_type="meridian.v1.Price",
        subjects=[ops.SubjectRef(entity_id=subject)], **kw,  # type: ignore[arg-type]
    )  # fmt: skip


async def _hear(recorder: Recorder, lake: Lake, event: ops.ObservationsWantedEvent) -> None:
    recorder.answer("ObservationsWanted", lambda _: event)
    await recorder._hear({"ObservationsWanted": lake.on_observations_wanted})


def test_each_venues_datasets_are_named_for_it() -> None:
    lake, _, _ = _lake()
    okx = lake.feeds["okx"]
    assert okx.dataset("daily") == "ccxt:okx_daily"
    assert okx.wants.key_of("ccxt:okx_live") == "live"
    assert okx.wants.key_of("ccxt:bybit_live") == ""
    assert lake.feed_of("ccxt:bitstamp_daily") is lake.feeds["bitstamp"]
    assert {d.key for d in CATALOGUE} == {f"{v.id}_{k}" for v in VENUES for k in v.offers}


async def test_a_want_is_recorded_by_its_venue_alone() -> None:
    lake, recorder, store = _lake()
    lake.enable({"okx", "bybit"})
    okx = lake.feeds["okx"]
    subject = await held(store, okx, "BTC")
    await _hear(recorder, lake, _want("ccxt:okx_daily", subject,
                                      business_date=venue_cases.CLOSED.isoformat(),
                                      kinds=[ops.PRICE_KIND_CLOSE]))  # fmt: skip
    prices = [p for s in recorder.sent if s.row == "RecordPrices" for p in s.params.prices]
    assert prices and {p.meta.source.dataset for p in prices} == {"ccxt:okx_daily"}
    assert okx.sent_to("okx_daily").recorded == okx.sent_to("daily").recorded > 0
    assert lake.feeds["bybit"].counts.wants == 0


async def test_a_venue_left_off_declines_not_covered_and_is_never_called() -> None:
    lake, recorder, _ = _lake()
    lake.enable({"okx"})
    await _hear(recorder, lake, _want("ccxt:bybit_live", "INS-X"))
    declined = [s for s in recorder.sent if s.row == "DeclineWant"]
    assert [d.params.reason for d in declined] == [ops.UNANSWERED_REASON_NOT_COVERED]
    replay = lake.feeds["bybit"].market.exchange.session.get_adapter("https://x")  # type: ignore[attr-defined]
    assert replay.asked == []


async def test_a_perpetuals_daily_want_is_not_covered() -> None:
    lake, recorder, store = _lake()
    lake.enable({"okx"})
    okx = lake.feeds["okx"]
    subject = await held(store, okx, "BTC-USDT-SWAP")
    await _hear(recorder, lake, _want("ccxt:okx_daily", subject,
                                      business_date=venue_cases.CLOSED.isoformat()))  # fmt: skip
    declined = [s for s in recorder.sent if s.row == "DeclineWant"]
    assert [d.params.reason for d in declined] == [ops.UNANSWERED_REASON_NOT_COVERED]
    assert not [s for s in recorder.sent if s.row == "RecordPrices"]


async def test_a_quote_want_is_not_covered_live_records_prices() -> None:
    lake, recorder, store = _lake()
    lake.enable({"okx"})
    subject = await held(store, lake.feeds["okx"], "BTC")
    event = _want("ccxt:okx_live", subject)
    event.data_type = "meridian.v1.Quote"
    await _hear(recorder, lake, event)
    declined = [s for s in recorder.sent if s.row == "DeclineWant"]
    assert [d.params.reason for d in declined] == [ops.UNANSWERED_REASON_NOT_COVERED]


async def test_only_the_venues_on_are_run_and_one_turned_off_stops() -> None:
    lake, _, _ = _lake()
    started: list[str] = []

    for venue, feed in lake.feeds.items():

        async def run(venue: str = venue) -> None:
            started.append(venue)
            await asyncio.Event().wait()

        feed.run = run  # type: ignore[method-assign]
    lake.enable({"okx"})
    task = asyncio.create_task(lake.run())
    await asyncio.sleep(0.01)
    assert started == ["okx"] and set(lake._running) == {"okx"}
    lake.enable({"bybit"})
    await asyncio.sleep(0.01)
    assert set(lake._running) == {"bybit"} and started == ["okx", "bybit"]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert lake._running == {}


async def test_licences_are_read_for_each_venues_datasets() -> None:
    lake, recorder, _ = _lake()
    daily = ops.DatasetLicence(dataset="ccxt:okx_daily", kept=True)
    recorder.answer("ListDatasets", lambda _: ops.ListDatasetsResult(licences=[daily]))
    await lake.read_licences()
    assert lake.feeds["okx"].licensed == frozenset({"ccxt:okx_daily"})
    assert lake.feeds["bybit"].licensed == frozenset()
