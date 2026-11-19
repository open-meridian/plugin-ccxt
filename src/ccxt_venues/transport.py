"""Each venue's CCXT exchange, made by this plugin and nothing else: the one
module that builds a CCXT instance, and the guards every instance carries.

**One instance per venue** (CCXT's manual: one rate limiter per instance;
one key per instance, from stage B). `enableRateLimit` is on, and calls on
one instance are made one at a time (`Exchange.lock`), so CCXT's throttle is
never raced and the raw records an answer kept are the call's own.

**Every answer is a raw record first.** CCXT hands each REST answer's text to
`on_rest_response` before it parses anything; the plugin keeps it there
(`meridian.edge.RawStore`), with its status, its freshness headers and the
request's method and address, never its headers (a key would be in them from
stage B). What the plugin records is read from that kept text, never from
CCXT's parsed numbers, which are floats (read.py).

**Sample data** answers through the same instance: `Replay`, a `requests`
adapter mounted on the instance's session, answers each request from the
synthetic exchanges this package carries (`synthetic/<venue>.json`), shaped
as the venue sends its answers, with invented values, or from a developer's
recorded ones. A request it holds no answer for is refused as the venue
would refuse an unknown market, so nothing ever leaves the deployment.

**Guards** (rulings 164 to 166):

- No credential is ever set in stage A: `made` refuses an instance carrying
  one, and the secret settings declared for stage B are never read.
- Hyperliquid's builder fee is off (`builderFee` False) and its approval is
  never signed: `handle_builder_fee_approval` refuses, whatever the options
  say. CCXT signs that approval, at 0%, even with the fee off.
- CCXT's broker attribution -- OKX's `tag` and its generated `clOrdId`,
  Bybit's `Referer`, KuCoin's partner headers, Gate's channel header -- is
  off unless the plugin's `broker_tags` setting turns it on (`attribution`).
  Our own client order ID is always passed (orders.py), which also stops
  Binance generating one with CCXT's broker prefix.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import ccxt
import requests
from meridian.edge import RawStore
from requests.adapters import BaseAdapter

#: The headers kept with a raw record: freshness and rate limits.
KEPT_HEADERS = ("date", "cache-control", "age", "retry-after", "x-ratelimit-remaining")
#: The options that carry CCXT's broker attribution, by CCXT id, and their
#: value with attribution off (`attribution`).
BROKER_OPTIONS: dict[str, tuple[str, Any]] = {
    "okx": ("brokerId", None),
    "kucoin": ("partner", {}),
    "kucoinfutures": ("partner", {}),
}
#: The headers that carry it, stripped with attribution off.
BROKER_HEADERS: dict[str, tuple[str, ...]] = {
    "bybit": ("Referer",),
    "gate": ("X-Gate-Channel-Id",),
}
#: The credentials CCXT reads; none is set in stage A.
CREDENTIALS = ("apiKey", "secret", "password", "uid", "privateKey", "walletAddress", "token")


class Refused(Exception):
    """Something this plugin never does was asked of CCXT."""


class Kept:
    """Mixed into each venue's CCXT class (`made`): its answers kept, its
    attribution as the plugin's setting says, its builder fee never
    approved."""

    store: RawStore | None
    clock_ns: Callable[[], int]
    #: Each raw record kept by the call under way, in order.
    kept_now: list[tuple[str, int]]
    #: Whether the call under way reads something live (a ticker, a book):
    #: kept as the next line of its day's file, an unchanged answer named
    #: again by the key it was first kept under.
    as_line: bool
    broker_tags: bool
    lock: threading.Lock

    def on_rest_response(
        self,
        code: Any,
        reason: Any,
        url: str,
        method: str,
        response_headers: Any,
        response_body: str,
        request_headers: Any,
        request_body: Any,
    ) -> str:
        received = self.clock_ns()
        if self.store is not None:
            split = urllib.parse.urlsplit(url)
            record = {
                "venue": getattr(self, "id", ""),
                "call": split.path,
                "request": {
                    "method": method,
                    "url": url,
                    **({"body": str(request_body)} if request_body else {}),
                },
                "received_at_ns": received,
                "status": int(code or 0),
                "headers": {
                    h: str(response_headers[h])
                    for h in KEPT_HEADERS
                    if response_headers is not None and h in response_headers
                },
                "body": response_body,
            }
            name = split.path.strip("/").replace("/", "-") or "root"
            keep = self.store.keep_line if self.as_line else self.store.keep
            key = keep(str(getattr(self, "id", "venue")), name, record)
            self.kept_now.append((key, received))
        return str(response_body).strip()

    def handle_builder_fee_approval(self) -> bool:
        raise Refused("a builder fee is never approved or signed by this plugin (ruling 165)")

    def sign(self, *args: Any, **kwargs: Any) -> Any:
        signed = super().sign(*args, **kwargs)  # type: ignore[misc]
        if not self.broker_tags:
            said = signed.get("headers") or {}
            for header in BROKER_HEADERS.get(str(getattr(self, "id", "")), ()):
                said.pop(header, None)
        return signed


def attribution(exchange: Any, on: bool) -> None:
    """CCXT's broker attribution on or off for this instance (ruling 164):
    off, each option and header that carries it is cleared; on, CCXT's own
    value, as the instance was made with, is put back."""
    exchange.broker_tags = on
    venue = str(exchange.id)
    held: dict[str, Any] = exchange.attributed
    if venue in BROKER_OPTIONS:
        option, off = BROKER_OPTIONS[venue]
        exchange.options[option] = held.get(option) if on else off
    for header in BROKER_HEADERS.get(venue, ()):
        if exchange.headers is None:
            exchange.headers = {}
        if on and header in held:
            exchange.headers[header] = held[header]
        elif not on:
            exchange.headers.pop(header, None)


def made(
    venue: str,
    options: Mapping[str, Any],
    store: RawStore | None,
    *,
    replay: BaseAdapter | None = None,
    clock_ns: Callable[[], int] = time.time_ns,
    broker_tags: bool = False,
) -> Any:
    """The CCXT instance for `venue` (its CCXT id), every answer kept in
    `store`, answering from `replay` where it is given."""
    base = getattr(ccxt, venue)
    kept = type(f"Kept{base.__name__}", (Kept, base), {})
    exchange = kept({"enableRateLimit": True, "options": dict(options)})
    exchange.store, exchange.clock_ns, exchange.kept_now = store, clock_ns, []
    exchange.as_line = False
    exchange.lock = threading.Lock()
    # CCXT's own attribution, as the instance was made, before any is cleared.
    option = BROKER_OPTIONS.get(venue, ("", None))[0]
    exchange.attributed = {
        **({option: exchange.options.get(option)} if option else {}),
        **{h: v for h, v in (exchange.headers or {}).items() if h in BROKER_HEADERS.get(venue, ())},
    }
    if venue == "hyperliquid":
        if options.get("builderFee"):
            raise Refused(f"{venue}: a builder fee is refused (ruling 165)")
        exchange.options["builderFee"] = False
    attribution(exchange, broker_tags)
    if replay is not None:
        exchange.session.mount("https://", replay)
        exchange.session.mount("http://", replay)
    guard(exchange)
    return exchange


def guard(exchange: Any) -> None:
    """Refuse an instance carrying a credential, or a builder fee: stage A
    holds neither (rulings 165 and 166)."""
    if any(getattr(exchange, name, None) for name in CREDENTIALS):
        raise Refused(f"{exchange.id}: no credential is set in stage A")
    if exchange.options.get("builderFee"):
        raise Refused(f"{exchange.id}: a builder fee is refused (ruling 165)")


# ── Sample data ──────────────────────────────────────────────────────────


#: The parameters a held answer is found without: the range and the count a
#: request asks for. A held answer states what it holds, and the plugin keeps
#: what falls in the range it asked.
RANGE_PARAMS = frozenset({
    "since", "limit", "after", "before", "start", "end", "startTime", "endTime",
    "start_timestamp", "end_timestamp",
})  # fmt: skip


def _loose(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _loose(v) for k, v in value.items() if k not in RANGE_PARAMS}
    return value


def request_key(method: str, url: str, body: Any = None) -> str:
    """How a held answer is found: the method, the path, the query's
    parameters but the range (`RANGE_PARAMS`) sorted, and a POST's JSON body
    likewise, its keys sorted."""
    split = urllib.parse.urlsplit(url)
    pairs = [(k, v) for k, v in urllib.parse.parse_qsl(split.query) if k not in RANGE_PARAMS]
    query = urllib.parse.urlencode(sorted(pairs))
    key = f"{method} {split.path}" + (f"?{query}" if query else "")
    if body:
        text = body.decode() if isinstance(body, bytes) else str(body)
        try:
            key += " " + json.dumps(_loose(json.loads(text)), sort_keys=True, separators=(",", ":"))
        except ValueError:
            key += " " + text
    return key


class Replay(BaseAdapter):
    """A `requests` adapter answering from held answers, never the network:
    each a (status, body text) by `request_key`. One it does not hold is
    answered 404, as a venue answers an unknown market, and remembered in
    `missed`."""

    def __init__(self, answers: Mapping[str, tuple[int, str]]) -> None:
        super().__init__()
        self.answers = dict(answers)
        self.missed: list[str] = []
        self.asked: list[str] = []

    @classmethod
    def synthetic(cls, venue: str, directory: Path | None = None) -> Replay:
        """The synthetic exchanges this package carries for `venue`."""
        from importlib import resources

        root = directory or Path(str(resources.files("ccxt_venues") / "synthetic"))
        held: dict[str, Any] = json.loads((root / f"{venue}.json").read_text(encoding="utf-8"))
        return cls(
            {
                key: (int(answer.get("status", 200)), _text(answer["body"]))
                for key, answer in held.items()
            }
        )

    @classmethod
    def recorded(cls, directory: Path, venue: str) -> Replay:
        """A developer's recorded raw records of `venue` (never committed):
        the latest good answer kept for each request."""
        answers: dict[str, tuple[int, str]] = {}
        for path in sorted(directory.rglob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if record.get("venue") != venue or int(record.get("status", 0)) != 200:
                continue
            asked = record["request"]
            key = request_key(asked["method"], asked["url"], asked.get("body"))
            answers[key] = (200, str(record["body"]))
        return cls(answers)

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        key = request_key(str(request.method), str(request.url), request.body)
        self.asked.append(key)
        status, text = self.answers.get(key, (404, '{"error":"not held"}'))
        if key not in self.answers:
            self.missed.append(key)
        answer = requests.Response()
        answer.status_code = status
        answer.reason = "OK" if status == 200 else "Not Found"
        answer._content = text.encode("utf-8")
        answer.headers["content-type"] = "application/json"
        answer.headers["cache-control"] = "no-store"
        answer.url = str(request.url)
        answer.request = request
        return answer

    def close(self) -> None:
        return None


def _text(body: Any) -> str:
    """A held answer's body as the venue sends it: text as it is, else its JSON."""
    return body if isinstance(body, str) else json.dumps(body, separators=(",", ":"))
