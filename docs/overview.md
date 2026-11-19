# Overview

This plugin reads crypto venues' public market data through CCXT, an
open-source library (MIT), and records it in your deployment's lake. It needs
no key and no account at any venue.

The venues it can read: OKX, Bybit, Bitstamp, Deribit, Hyperliquid and
Binance. Each is off until a deployment admin turns it on in Settings.

## Its role

It holds the `data` role: it records prices for what your deployment asks
for, and nothing else. It places no orders and reads no account.

## What it records

For each venue you turn on, two datasets:

| Dataset | What | When |
|---|---|---|
| `<instance>:<venue>_daily` | Each spot market's daily close and bar (open, high, low, close, volume) | For the days asked; the day still forming every five minutes while a reader keeps it current |
| `<instance>:<venue>_live` | The last trade's price and the best bid and ask, as prices | When asked, and once a second while a reader keeps it current |

Each day is the UTC day, ending at 00:00 UTC. A perpetual swap is recorded
in `live` only: its last price and best bid and ask. Hyperliquid's public data
states no last trade price, so its `live` holds its best bid and ask alone.

Trades and quotes with their sizes are not recorded yet.

## How it names what it prices

Each record your deployment asks about is named by the venue's own codes: a
currency by its ISO code, bitcoin and ether by their global identifiers, and
every other token as that venue's own. A stablecoin such as USDT is a token,
never the dollar. A perpetual swap is named by the venue's own ID for it, for
example `BTC-USDT-SWAP` at OKX, or `linear/BTCUSDT` at Bybit and Binance, whose
ID is shared with a spot market.

## What it never makes up

Every figure is read from the text the venue sent, never through a rounded
number. Something a venue does not state is not recorded: it is declined with
the reason, and the Venues page says what each venue does not serve.

## What it keeps

Each venue's answers, as received, in the plugin's own storage for 30 days by
default (Settings: the raw responses' window).
