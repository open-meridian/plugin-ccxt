# Changelog

## 0.1.0 (draft)

The first version: OKX, Bybit, Bitstamp, Deribit, Hyperliquid and Binance's
public market data through CCXT 4.5.93, each venue off until turned on.

- Each venue's `daily` (spot closes and bars, UTC day) and `live` (last, bid
  and ask as prices; perpetual swaps too) datasets.
- Pages: Connection and Datasets for the venue chosen, and Venues.
- Guards: no key, Hyperliquid's builder fee off and never approved, CCXT's
  broker attribution off unless turned on, our own client order ID always,
  CCXT pinned exactly.
- Built on open-meridian 0.37.0, which waits for a lost sidecar; `meridian`
  0.1.61 in the check.

SDK 0.37.1: a raw record kept from two threads at once waits instead of being dropped.
