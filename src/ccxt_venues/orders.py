"""Our own client order ID on every order, for a later stage that places
orders (ruling 164). Stage A places none; this is built now so the trading
stage inherits it, and the tests hold CCXT's request to it.

A venue sees the placement's identifier as its client order ID
(spec/one-order-lifecycle-in-the-book, identifiers), passed to CCXT as the
unified `clientOrderId`. Where the venue limits the ID's form, a
deterministic derivation of it is passed instead, the same every time, and
reported back as the placement's external reference. Passing one always also
stops CCXT generating its own (Binance's carries CCXT's broker prefix).
"""

from __future__ import annotations

import hashlib
import re

#: What each venue accepts as a client order ID, by CCXT id: a pattern, and
#: how a derivation is written where the placement's own does not fit.
FORMS: dict[str, tuple[re.Pattern[str], str]] = {
    "okx": (re.compile(r"[A-Za-z0-9]{1,32}"), "hex32"),
    "bybit": (re.compile(r"[A-Za-z0-9_-]{1,36}"), "hex32"),
    "binance": (re.compile(r"[.A-Za-z0-9:/_-]{1,36}"), "hex32"),
    "bitstamp": (re.compile(r"[A-Za-z0-9_-]{1,180}"), "hex32"),
    "deribit": (re.compile(r"[ -~]{1,64}"), "hex32"),
    "hyperliquid": (re.compile(r"0x[0-9a-f]{32}"), "cloid"),
}


def client_order_id(venue: str, placement_id: str) -> str:
    """The client order ID `venue` is sent for a placement: its own
    identifier where the venue accepts it, else a derivation from it."""
    if not placement_id:
        raise ValueError("a placement's identifier is needed: CCXT never chooses one")
    pattern, derived = FORMS.get(venue, (re.compile(r"[A-Za-z0-9]{1,32}"), "hex32"))
    if pattern.fullmatch(placement_id):
        return placement_id
    digest = hashlib.sha256(placement_id.encode("utf-8")).hexdigest()
    return f"0x{digest[:32]}" if derived == "cloid" else digest[:32]


def order_params(venue: str, placement_id: str) -> dict[str, str]:
    """The parameters every order carries: our own client order ID."""
    return {"clientOrderId": client_order_id(venue, placement_id)}
