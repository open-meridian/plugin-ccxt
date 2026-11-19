# plugin-ccxt

An Open Meridian data plugin that reads crypto venues' public market data
through [CCXT](https://github.com/ccxt/ccxt) (MIT) and records it in a
deployment's lake. No key and no account at any venue.

Venues it can read, each off until a deployment admin turns it on: **OKX,
Bybit, Bitstamp, Deribit, Hyperliquid and Binance.** Coinbase Exchange, Kraken,
Polymarket and Kalshi have plugins of their own and are not read through CCXT.

## What it does

For each venue turned on, two datasets, each on the UTC day:

| Dataset | Data |
|---|---|
| `<instance>:<venue>_daily` | Each spot market's daily close and bar |
| `<instance>:<venue>_live` | The last trade's price and the best bid and ask, as prices, for spot markets and perpetual swaps |

A perpetual swap is recorded in `live` only. Hyperliquid's public data states
no last trade price, so its `live` holds its best bid and ask alone. No
trades, quotes, order books or funding are recorded in this version.

Every figure is read from the text the venue sent, never from CCXT's parsed
numbers, which are floats: CCXT reaches the venue, and the plugin keeps each
answer as a raw record before CCXT reads it, then reads the venue's own fields
from that record.

## Deploying it

Upload it from this directory with `meridian plugin upload`, which builds its
image from the Dockerfile, and launch an instance of it as any other plugin
(`meridian plugin launch`); a deployment admin approves the `data` role it
asks for. Then, in the dashboard:

1. **Settings**: turn on each venue you use (`venue_okx`, `venue_bybit`, ...).
   Leave the key fields empty: this version reads no key.
2. **Data sources**: read each venue's terms there, then license the datasets
   you use and entitle the plugins that read them.
3. **Venues**, the plugin's page: each venue you turned on says On.

## Each venue's terms

Each venue's datasets describe its terms, who may not use it and where its
public API answers from, cited with the date they were read
(`src/ccxt_venues/venues.py`; `docs/terms.md` summarises them). The plugin
declares no licence: the deployment's licence on Data sources is the one
enforced. Some venues refuse some regions' IP addresses (Bybit refuses the
United States), and some exclude some persons (Binance: the United States,
Canada, the Netherlands and others). Not legal advice.

## Settings

| Setting | Default | What |
|---|---|---|
| `venue_okx` ... `venue_binance` | off | Read that venue |
| `broker_tags` | off | Send CCXT's own broker attribution with orders (OKX's tag, Bybit's Referer, KuCoin's partner, Gate's channel). This version places no orders; our own client order ID is always sent |
| `<venue>_key`, `<venue>_secret`, ... | empty | For trading, in a later version; never read by this one |
| `sample_data` | off | Development deployments only: answer from made-up answers |

## Guards

- No key is set on any CCXT instance in this version, and the plugin refuses
  one that carries one.
- Hyperliquid's builder fee, which CCXT charges by default, is off, and its
  approval is never signed.
- CCXT's broker attribution is off unless `broker_tags` turns it on.
- CCXT is pinned exactly (`pyproject.toml`, `venues.CCXT_VERSION`).

## Bumping CCXT

CCXT is bumped at most once per release train, security fixes excepted, with
the venue suite as the gate:

1. Change the pin in `pyproject.toml` and `CCXT_VERSION` in
   `src/ccxt_venues/venues.py` together.
2. Write the snapshot again: `python -m ccxt_venues.snapshot >
   src/ccxt_venues/venues.json`, and read its diff: a venue's `has` or
   `features` changing is a method gained or lost.
3. Check CCXT's changelog for each venue in the catalogue: a venue delisted,
   a default option changed (broker IDs, builder fees), an endpoint moved.
4. Run the tests: the venue suite runs the SDK's data suite for every venue on
   its synthetic exchange through the new CCXT. Any request CCXT now makes
   that the synthetic exchange does not hold fails it; add the answer, shaped
   as the venue documents it, with invented values.
5. Release it as a new version of the plugin.

## Working on it

`AGENTS.md` is for any coding agent working on the plugin. The tests run with
`make test` (in a container) or `python -m pytest` in a virtualenv with
`pip install -e '.[dev]'`; `make lint` runs ruff and mypy. A pull request's CI
runs those, `meridian plugin check` and the plugin on the runtime's harness.

No real venue answer is committed: `src/ccxt_venues/synthetic/` holds invented
values, shaped as each venue sends its answers.

## Licence

Apache-2.0. CCXT is MIT-licensed and installed as a dependency.
