# Troubleshooting

## A venue answers nothing

It is off: turn it on in Settings. The Venues page says On or Off.

## A venue is not answering

Its Connection page says the last error. Bybit's public API refuses US IP
addresses, and Binance's refuses some regions: from there, its wants are
declined and nothing is recorded. Use a venue that answers from where your
deployment runs.

## A subject declined "not covered"

The venue lists no market for it, or it asks for something the venue does not
serve: a perpetual's daily candles, a quote with sizes, or trades. The Venues
page says what each venue does not serve.

## A price in USDT, not dollars

That market is quoted in USDT, a token, and its price says so. A stablecoin is
never recorded as the dollar.

## A venue is rate-limiting

CCXT keeps the plugin inside each venue's published limits; a limit hit is
counted on the Connection page and asked again later.

## Still stuck

Open an issue on the plugin's repository with the Connection page's last
error.
