"""The plugin's pages (page.py): the data role's Connection and Datasets for
the venue chosen, and Venues; under Manage alone, one-line tables, no market
figure, no word on a venue's terms, and each a tool answering what it shows."""

from __future__ import annotations

import asyncio
import re

from meridian.testing import PageClient

from ccxt_venues import page
from ccxt_venues.preview import worked

PATHS = {"read_connection": "/", "read_datasets": "/datasets", "read_venues": "/venues"}


def _client() -> PageClient:
    lake, _ = asyncio.run(worked())
    page.hold(lake)
    return PageClient(page.pages)


def test_each_page_is_served_under_manage_alone() -> None:
    client = _client()
    served = {(r.page.path, r.level): r.response.status for r in client.every_page()}
    assert {path for path, _ in served} == set(PATHS.values())
    for (_, level), status in served.items():
        assert status == (200 if level == "admin" else 403), (level, status)


def test_every_table_is_one_line_rows_and_no_page_shows_a_price() -> None:
    client = _client()
    for path in PATHS.values():
        text = client.get(path, "admin").text
        tables = re.findall(r"<table[^>]*>", text)
        assert tables and all('class="one-line"' in t for t in tables), (path, tables)
        for figure in ("62001.4", "61988.9", "61991.7", "62100.9"):
            assert figure not in text, (path, figure)
        lowered = text.lower()
        assert "terms allow" not in lowered and "regulat" not in lowered
        assert "complian" not in lowered


def test_a_venue_is_chosen_on_the_page_and_the_tool() -> None:
    client = _client()
    shown = client.get("/datasets", "admin", venue="bybit").text
    assert "ccxt:bybit_daily" in shown and "ccxt:okx_daily" not in shown
    assert '<option value="bybit" selected>' in shown
    first = client.get("/datasets", "admin").text
    assert "ccxt:okx_daily" in first, "the first venue on is shown where none is asked"
    answered = client.call_tool("read_datasets", {"venue": "okx"}, level="admin").data
    assert [s["dataset"] for s in answered["served"]] == ["ccxt:okx_daily", "ccxt:okx_live"]
    assert len(answered["wants"]) == 2


def test_a_venue_off_says_so() -> None:
    client = _client()
    text = client.get("/", "admin", venue="binance").text
    assert "Binance is off" in text


def test_venues_says_each_venue_on_or_off_and_what_it_does_not_serve() -> None:
    client = _client()
    answered = client.call_tool("read_venues", level="admin").data
    on = {row["ccxt_id"]: row["on"] for row in answered["venues"]}
    assert on == {"okx": True, "bybit": True, "bitstamp": False, "deribit": False,
                  "hyperliquid": False, "binance": False}  # fmt: skip
    hyper = next(r for r in answered["venues"] if r["ccxt_id"] == "hyperliquid")
    assert "no last trade price" in hyper["not_served"]
    okx = next(r for r in answered["venues"] if r["ccxt_id"] == "okx")
    assert okx["listed"] == 7 and okx["serves"] == "okx_daily, okx_live"


def test_a_tool_is_refused_below_manage() -> None:
    client = _client()
    for name in PATHS:
        assert client.call_tool(name, level="read").status == 403
