"""The plugin, with sample data, on the plugin harness of the runtime the
Makefile pins, beside the e2e's reader (e2e/reader.py), each step checked:

1. The catalogue: the deployment admin's tool lists each venue's datasets,
   `ccxt:<venue>_daily` and `ccxt:<venue>_live`, each on the UTC day.
2. Off until turned on: with sample data on and no venue on, OKX's Venues
   row says Off; then OKX turned on, its listing is read and nothing is
   minted for an asset no subject is.
3. Licensed and entitled: the admin licenses OKX's daily dataset and
   entitles the reader.
4. A close wanted: the reader asks for bitcoin's close on OKX's daily
   dataset for a day the synthetic exchange states; the plugin names its
   record by its CAIP-19, and records BTC-USDT's close exactly as stated,
   against the want, with its raw record.
5. Its tools answer what its pages show: read_venues and read_datasets.

Run from the repository's root by the Makefile, which builds the image,
copies the harness out and writes the plugins' compose file first, and
exports what the compose files read. Standard library only.
"""

import json
import re
import subprocess
import sys
import time

INSTANCE = "ccxt"
DAY = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--day=")]
EXACT = not DAY
CLOSED = DAY[0] if DAY else "2026-10-08"
LOG = ".e2e/runner.log"
#: The harness's compose files and this plugin's, and any the Makefile adds
#: (e2e-recorded's), under the Makefile's project.
COMPOSE = ["docker", "compose", "-p", "ccxt-venues-e2e", "-f", ".e2e/harness/compose.yaml",
           "-f", ".e2e/harness/plugins.yaml", "-f", "e2e/plugin.yaml",
           *[a for a in sys.argv[1:] if not a.startswith("--day=")]]
#: BTC-USDT's close the synthetic exchange states for CLOSED.
CLOSE = ("BTC-USDT", "62001.4")
VENUES = ("okx", "bybit", "bitstamp", "deribit", "hyperliquid", "binance")
#: Assets no subject is: never minted for reading the listing.
UNASKED = r"(?<![A-Z])(ETH|TKN|PLY)(?![A-Z])"


class Failed(Exception):
    pass


def log(text):
    with open(LOG, "a", encoding="utf-8") as kept:
        kept.write(text + "\n")


def compose(*args, check=True):
    done = subprocess.run(COMPOSE + list(args), capture_output=True, text=True, timeout=600)
    log(f"$ compose {' '.join(args)[:300]}\n{done.stdout[-4000:]}{done.stderr[-2000:]}")
    if check and done.returncode != 0:
        raise Failed(f"compose {' '.join(args)[:200]}: {(done.stdout + done.stderr).strip()[-600:]}")
    return done


def runner(*args, check=True):
    done = compose("run", "--rm", "-T", "runner", *args, check=check)
    return done.stdout if check else done


def must(condition, why):
    if not condition:
        raise Failed(why)


def until(seconds, attempt, what):
    deadline = time.monotonic() + seconds
    last = None
    while True:
        try:
            answer = attempt()
        except Failed as failed:
            answer, last = None, failed
        if answer:
            return answer
        if time.monotonic() > deadline:
            raise Failed(f"{what}, in {seconds} seconds" + (f": {last}" if last else ""))
        time.sleep(2)


def page(instance, level, path):
    said = runner("page", "--instance", instance, "--level", level, path)
    status, _, body = said.partition("\n")
    must(status.strip() == "200", f"{instance} {path} answered {said[-600:]}")
    return body


def read(path):
    return json.loads(page("reader", "read", path))


def call(tool, arguments, *outcomes):
    done = runner("mcp", "call", tool, json.dumps(arguments), check=False)
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        raise Failed(f"{tool}: no answer: {(done.stdout + done.stderr)[-400:]}") from None
    must(answer.get("outcome") in outcomes,
         f"{tool} answered {answer.get('outcome')}, not {outcomes}: {done.stdout[-700:]}")
    return answer


def said(listed):
    """The identifiers each listed record carries, without its ID: a minted
    ID is random, and can spell an asset's code (LCL-...8ETH7...)."""
    return "\n".join(line.partition("\t")[2] for line in listed.splitlines())


def instrument(listed, pattern, required=True):
    for line in listed.splitlines():
        instrument_id, _, identifiers = line.partition("\t")
        if re.search(pattern, identifiers):
            return instrument_id
    if not required:
        return ""
    raise Failed(f"no record listed matches {pattern}: {listed}")


def run():
    started = time.time()
    compose("--profile", "runner", "down", "-v", "--remove-orphans", check=False)
    compose("up", "-d")
    for instance in (INSTANCE, "reader"):
        runner("ready", "--instance", instance)
    runner("grant", "--instance", "reader", "--level", "read", "--role", "reporting")
    runner("grant", "--instance", INSTANCE, "--level", "admin")
    runner("mcp", "connect", "--covers", "deployment_admin", "--covers", f"{INSTANCE}:admin")
    tools = runner("mcp", "list").split()
    named = {t.rsplit("__", 1)[-1]: t for t in tools}
    for name in ("dashboard__list_datasets", "read_connection", "read_datasets", "read_venues"):
        must(name.rsplit("__", 1)[-1] in named, f"step 1, {name} is listed: {tools}")

    # 1. The catalogue, as the deployment admin's tool lists it.
    wanted = {f"{INSTANCE}:{v}_{k}" for v in VENUES for k in ("daily", "live")}

    def datasets():
        held = {d["dataset"]: d for d in
                call("dashboard__list_datasets", {}, "read", "unchanged")["data"]["datasets"]}
        return held if wanted <= set(held) else None
    held = until(90, datasets, "step 1, each venue's datasets were not listed")
    for dataset in wanted:
        entry = held[dataset]["catalogue_entry"]
        must(entry["modes"] == ["pull", "push"] and entry["day_time_zone"] == "Etc/UTC"
             and entry.get("day_end_minute", 0) == 0, f"step 1, {dataset}'s entry: {entry}")

    # 2. Off until turned on; then OKX on, its listing read, nothing minted.
    runner("settings", "--instance", INSTANCE, "sample_data=true")
    venues = call(named["read_venues"], {}, "read", "unchanged")["data"]["venues"]
    must(not any(v["on"] for v in venues), f"step 2, every venue off by default: {venues}")
    runner("settings", "--instance", INSTANCE, "venue_okx=true")
    until(90, lambda: call(named["read_datasets"], {"venue": "okx"}, "read", "unchanged")
          ["data"]["products_listed"] >= 5, "step 2, OKX's listing was not read")
    listed = runner("instruments")
    log("instruments, the listing read:\n" + listed)
    must(not re.search(UNASKED, said(listed)), f"step 2, nothing minted unasked: {listed}")
    ids = read("/resolve")
    btc = ids["btc"]

    # 3. Licensed and entitled.
    runner("licence", f"{INSTANCE}:okx_daily", "kept=true", "retention_days=0",
           "derived_use=true", "display=true", "personal_use=false", "note=OKX's terms.")
    runner("grant", "--instance", "reader", "--level", "read", "--role", "signal")
    runner("entitle", "--instance", "reader", f"{INSTANCE}:okx_daily", "note=The e2e's reader.")

    # 4. A close wanted, recorded against the want, exactly as stated.
    daily = f"/prices?subject={btc}&date={CLOSED}&kind=close&dataset={INSTANCE}:okx_daily"
    closes = until(90, lambda: read(daily)["prices"],
                   "step 4, the plugin did not record the close wanted")
    by_product = {p["row_key"].split(":")[0]: p for p in closes}
    product, amount = CLOSE
    row = by_product.get(product)
    must(row is not None or not EXACT, f"step 4, {product}'s close: {closes}")
    if row is not None:
        must((row["amount"] == amount or not EXACT) and row["business_date"] == CLOSED,
             f"step 4, {product}'s close as the venue stated it: {row}")
        must(row["raw"].startswith("responses/"), f"step 4, its raw record: {row}")

    # 5. The tools answer what the pages show.
    venues = call(named["read_venues"], {}, "read", "unchanged")["data"]["venues"]
    must({v["ccxt_id"]: v["on"] for v in venues}["okx"], f"step 5, OKX on: {venues}")
    served = call(named["read_datasets"], {"venue": "okx"}, "read", "unchanged")["data"]
    must([d["dataset"] for d in served["served"]]
         == [f"{INSTANCE}:okx_daily", f"{INSTANCE}:okx_live"], f"step 5, read_datasets: {served}")
    print(f"e2e OK in {time.time() - started:.0f} s: each venue's datasets listed on the UTC "
          "day; every venue off until turned on; OKX's listing read, nothing minted unasked; "
          "its daily dataset licensed and the reader entitled; bitcoin's close wanted and "
          "recorded exactly as OKX states it, with its raw record; read_venues and "
          "read_datasets answering what the pages show")


def main():
    open(LOG, "w").close()
    try:
        run()
    except (Failed, subprocess.TimeoutExpired, KeyError, ValueError, IndexError) as failed:
        print(f"e2e FAILED: {failed}; the run is in {LOG}, the components' logs in "
              ".e2e/components.log", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
