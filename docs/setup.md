# Setup

## 1. Launch it

Upload and launch the plugin as any other. It asks for the `data` role and
storage for its raw responses, and no key.

## 2. Turn on the venues you use

In the plugin's **Settings**, turn on each venue you want: OKX, Bybit,
Bitstamp, Deribit, Hyperliquid, Binance. Every venue is off until you turn it
on, and a venue that is off answers nothing. Read each venue's terms and who
may not use it first ([Terms](terms.md)); they are on **Data sources** too.

Leave the API key fields empty: this version reads no key. They are for
trading, in a later version.

## 3. License its datasets

On **Data sources**, each venue's datasets are listed with its terms in words.
The plugin declares no licence: set your deployment's licence for each dataset
you use, and entitle the plugins that read it.

## 4. Check it

Open the plugin's **Venues** page: each venue you turned on says On. Its
**Connection** page, with the venue chosen, says whether the venue answers.
