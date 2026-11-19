"""The venue suite: the SDK's data suite, unchanged, once per venue, on that
venue's synthetic exchange through its real CCXT class (venue_cases.py);
then what this plugin adds past the suite's cases, for every venue: figures
read from the venue's own text, never through CCXT's floats; a perpetual's
last, bid and ask only; what a venue does not state, not offered; and no
call ever leaving the process."""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data import pairs
from meridian.roles.data.testing import (
    PAIRS_NOT_PRESENTED,
    Instruments,
    held,
    pairs_producers,
)
from meridian.suites import ANSWERED_BY_SDK, Recorder, names, run

from ccxt_venues.market import CcxtMarket, NotOffered

import venue_cases

CASES = sorted(venue_cases.CASES)
PRICE = "meridian.v1.Price"


def _not_presented(case: venue_cases.Case) -> dict[str, str]:
    return {**PAIRS_NOT_PRESENTED, **case.NOT_PRESENTED}


@pytest.mark.parametrize("venue", CASES)
def test_the_data_suite_passes_unchanged_for_each_venue(venue: str) -> None:
    case = venue_cases.CASES[venue]
    skipped = _not_presented(case)
    made = pairs_producers(case)
    assert set(names("data")) == set(made) | set(skipped) | set(ANSWERED_BY_SDK)
    report = run("data", made, not_presented=skipped, instance_id=venue)
    assert report.passed, report.failures
    assert len(report.passed_cases) == len(list(names("data"))) - len(skipped)


async def _feed(case: venue_cases.Case, **kw: Any) -> tuple[pairs.Feed, Recorder, Instruments]:
    recorder = Recorder(case.VENUE)
    store = Instruments().answering(recorder)
    feed = recorder.bind(pairs.Feed(case.market(**kw), pairs.ProductMap(),
                                    clock_ns=lambda: case.NOW_NS))  # fmt: skip
    return feed, recorder, store


def _rows(recorder: Recorder, row: str, field: str) -> list[Any]:
    return [r for sent in recorder.sent if sent.row == row for r in getattr(sent.params, field)]


@pytest.mark.parametrize("venue", CASES)
async def test_a_close_is_the_venues_own_text_exactly(venue: str) -> None:
    case = venue_cases.CASES[venue]
    feed, recorder, store = await _feed(case)
    subject = await held(store, feed, case.EXACT_BASE)
    await feed.record_days([subject], case.CLOSED, case.CLOSED, PRICE)
    (close,) = _rows(recorder, "RecordPrices", "prices")
    said = Decimal("0.000012345678901234")
    assert Decimal(float(said)) != said, "the case's close is past a float"
    assert as_decimal(close.price.amount) == said


@pytest.mark.parametrize("venue", CASES)
async def test_live_records_last_bid_and_ask_as_the_venue_states_them(venue: str) -> None:
    case = venue_cases.CASES[venue]
    feed, recorder, store = await _feed(case)
    subject = await held(store, feed, case.BASE)
    declined = await feed.record_live([subject])
    assert not declined

    said: dict[tuple[str, str], Decimal] = {}
    for price in _rows(recorder, "RecordPrices", "prices"):
        product = price.meta.row_key.split(":")[0]
        said[(product, ops.PriceKind.Name(price.kind))] = as_decimal(price.price.amount)
    expected = {}
    for product, (last, bid, ask) in case.LIVE.items():
        for kind, text in (("PRICE_KIND_LAST", last), ("PRICE_KIND_BID", bid),
                           ("PRICE_KIND_ASK", ask)):  # fmt: skip
            if text is not None:
                expected[(product, kind)] = Decimal(text)
    assert {k: v for k, v in said.items() if k[0] in case.LIVE} == expected


@pytest.mark.parametrize("venue", [v for v in CASES if venue_cases.CASES[v].PERPETUAL])
async def test_a_perpetual_is_priced_live_and_never_daily(venue: str) -> None:
    """Ruling 163: a perpetual's last, bid and ask, against its record; its
    daily candles never read."""
    case = venue_cases.CASES[venue]
    feed, recorder, store = await _feed(case)
    await feed.ensure_mapped()
    market = feed.market
    assert isinstance(market, CcxtMarket) and market.perpetual(case.PERPETUAL)
    subject = await held(store, feed, case.PERPETUAL)
    assert not await feed.record_live([subject])
    kinds = {ops.PriceKind.Name(p.kind) for p in _rows(recorder, "RecordPrices", "prices")}
    wanted = {"PRICE_KIND_BID", "PRICE_KIND_ASK"}
    if market.entry.last_from.get("swap"):
        wanted.add("PRICE_KIND_LAST")
    assert kinds == wanted
    with pytest.raises(NotOffered):
        market.candles(case.PERPETUAL, case.CLOSED, case.CLOSED)


@pytest.mark.parametrize("venue", CASES)
async def test_a_coins_record_is_never_named_as_a_perpetual(venue: str) -> None:
    """A custodian's bitcoin, by its own symbol BTC, names the venue's coin
    where it lists one, never a perpetual (Hyperliquid's is linear/BTC)."""
    case = venue_cases.CASES[venue]
    feed, _, store = await _feed(case)
    await feed.ensure_mapped()
    subject = store.hold("INS-HELD", ops.Identifier(scheme="symbol", value="BTC",
                                                    source="custodian"))  # fmt: skip
    await feed.name([subject])
    named = feed.products.subjects.get(subject, "")
    assert not named.startswith("linear/") and named != case.PERPETUAL


async def test_hyperliquid_states_no_last_price_so_none_is_recorded() -> None:
    case = venue_cases.CASES["hyperliquid"]
    feed, recorder, store = await _feed(case)
    subject = await held(store, feed, case.BASE)
    await feed.record_live([subject], [ops.PRICE_KIND_LAST])
    assert not _rows(recorder, "RecordPrices", "prices")
    market = feed.market
    assert isinstance(market, CcxtMarket)
    with pytest.raises(NotOffered):
        market.last("@1")


@pytest.mark.parametrize("venue", CASES)
async def test_no_call_leaves_the_process(venue: str) -> None:
    """Every request is answered by the synthetic exchange: none missed."""
    case = venue_cases.CASES[venue]
    feed, _, store = await _feed(case)
    subject = await held(store, feed, case.BASE)
    await feed.record_days([subject], date(2026, 10, 4), case.TODAY)
    await feed.record_live([subject])
    market = feed.market
    assert isinstance(market, CcxtMarket)
    replay = market.exchange.session.get_adapter("https://x")
    assert replay.asked and not replay.missed


def test_no_float_reaches_the_conversion() -> None:
    """The modules that read figures never call float()."""
    for path in venue_cases.CONVERSION:
        tree = ast.parse(path.read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "float"]  # fmt: skip
        assert not calls, path


@pytest.mark.parametrize("venue", CASES)
async def test_every_row_names_a_raw_record_its_storage_holds(venue: str) -> None:
    case = venue_cases.CASES[venue]
    feed, recorder, store = await _feed(case)
    subject = await held(store, feed, case.BASE)
    await feed.record_days([subject], case.CLOSED, case.CLOSED)
    await feed.record_live([subject])
    market = feed.market
    assert isinstance(market, CcxtMarket)
    rows = _rows(recorder, "RecordPrices", "prices") + _rows(recorder, "RecordBars", "bars")
    assert rows
    for row in rows:
        key = row.meta.raw.key
        assert key and market.exchange.store.get(key) is not None, row.meta.raw
