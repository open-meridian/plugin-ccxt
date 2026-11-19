"""The guards every CCXT instance carries (transport.py, orders.py; rulings
164 to 166): no credential, no builder fee and never its approval, CCXT's
broker attribution off unless the setting turns it on, our own client order
ID always, every answer kept as a raw record before it is read, and an exact
CCXT pin whose snapshot matches the installed CCXT."""

from __future__ import annotations

import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import ccxt
import pytest
from meridian.edge import RawStore

from ccxt_venues import snapshot
from ccxt_venues.market import CcxtMarket, offered
from ccxt_venues.orders import client_order_id, order_params
from ccxt_venues.transport import Refused, Replay, attribution, guard, made
from ccxt_venues.venues import BY_ID, CCXT_VERSION, VENUES
from ccxt_venues.venues import snapshot as held_snapshot

import venue_cases

ROOT = Path(__file__).parent.parent


def _made(venue: str, **kw: Any) -> Any:
    store = RawStore(Path(tempfile.mkdtemp()))
    return made(venue, BY_ID[venue].options, store, replay=Replay.synthetic(venue), **kw)


def test_ccxt_is_pinned_exactly_in_one_version_everywhere() -> None:
    pinned = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert f"ccxt=={CCXT_VERSION}" in pinned
    assert ccxt.__version__ == CCXT_VERSION
    assert held_snapshot()["ccxt"] == CCXT_VERSION


def test_the_snapshot_is_what_the_pinned_ccxt_says() -> None:
    """A bump that changes a venue's methods fails here until venues.json is
    written again (README, "Bumping CCXT")."""
    assert held_snapshot() == snapshot.written()


@pytest.mark.parametrize("venue", [v.id for v in VENUES])
def test_each_venue_reads_only_what_ccxt_says_it_has(venue: str) -> None:
    entry, exchange = BY_ID[venue], _made(venue)
    if "daily" in entry.offers:
        assert offered(exchange, "fetchOHLCV")
    for source in {*entry.last_from.values(), *entry.top_from.values()} - {""}:
        assert offered(exchange, {"ticker": "fetchTicker", "book": "fetchOrderBook"}[source])
    assert "trades" in entry.not_offered


def test_hyperliquids_ticker_is_emulated_so_its_last_price_is_not_offered() -> None:
    exchange = _made("hyperliquid")
    assert exchange.has["fetchTicker"] == "emulated" and not offered(exchange, "fetchTicker")
    assert set(BY_ID["hyperliquid"].last_from.values()) == {""}


def test_a_credential_is_refused() -> None:
    exchange = _made("okx")
    exchange.apiKey = "set"
    with pytest.raises(Refused):
        guard(exchange)


def test_the_builder_fee_is_off_and_its_approval_never_signed() -> None:
    exchange = _made("hyperliquid")
    assert exchange.options["builderFee"] is False
    with pytest.raises(Refused):
        exchange.handle_builder_fee_approval()
    with pytest.raises(Refused):
        made("hyperliquid", {"builderFee": True, "fetchMarkets": {"types": ["spot"]}}, None)


def test_okx_sends_our_client_order_id_and_no_broker_tag() -> None:
    exchange = _made("okx")
    exchange.load_markets()
    request = exchange.create_order_request(
        "BTC/USDT", "limit", "buy", 0.01, 60000, order_params("okx", "PLC-1")
    )
    assert request["clOrdId"] == "PLC1" or request["clOrdId"] == client_order_id("okx", "PLC-1")
    assert "tag" not in request


def test_okx_without_our_id_would_send_ccxts_broker_tag_only_when_turned_on() -> None:
    exchange = _made("okx")
    exchange.load_markets()
    assert "tag" not in exchange.create_order_request("BTC/USDT", "limit", "buy", 0.01, 60000)
    attribution(exchange, True)
    assert exchange.create_order_request("BTC/USDT", "limit", "buy", 0.01, 60000)["tag"]


def test_binance_sends_our_client_order_id_never_ccxts_prefix() -> None:
    exchange = _made("binance")
    exchange.load_markets()
    request = exchange.create_order_request(
        "BTC/USDT", "limit", "buy", 0.01, 60000, order_params("binance", "PLC-1")
    )
    assert request["newClientOrderId"] == "PLC-1"


def test_bybits_referer_is_sent_only_when_attribution_is_on() -> None:
    exchange = _made("bybit")
    exchange.apiKey, exchange.secret = "k", "s"  # signing only: no call is made
    signed = exchange.sign("v5/order/create", ["private"], "POST", {"symbol": "BTCUSDT"})
    assert "Referer" not in (signed["headers"] or {})
    attribution(exchange, True)
    signed = exchange.sign("v5/order/create", ["private"], "POST", {"symbol": "BTCUSDT"})
    assert signed["headers"]["Referer"] == "CCXT"


def test_a_client_order_id_the_venue_refuses_is_derived_the_same_every_time() -> None:
    long = "PLC-" + "x" * 60
    assert client_order_id("okx", long) == client_order_id("okx", long)
    assert re.fullmatch(r"[0-9a-f]{32}", client_order_id("okx", long))
    assert re.fullmatch(r"0x[0-9a-f]{32}", client_order_id("hyperliquid", "PLC-1"))
    with pytest.raises(ValueError):
        client_order_id("okx", "")


def test_every_answer_is_kept_before_it_is_read() -> None:
    case = venue_cases.CASES["deribit"]
    market = case.market()
    assert isinstance(market, CcxtMarket)
    market.listing()
    kept = list(market.exchange.store.records())
    assert {r["call"] for r in kept} >= {"/api/v2/public/get_instruments"}
    assert all("headers" in r and "body" in r and "Authorization" not in r["headers"]
               for r in kept)  # fmt: skip


def test_a_request_not_held_never_leaves_and_is_said() -> None:
    exchange = _made("okx")
    with pytest.raises(ccxt.BaseError):
        exchange.fetch_ticker("ZZZ/USDT")
    replay = exchange.session.get_adapter("https://x")
    assert isinstance(replay, Replay)
