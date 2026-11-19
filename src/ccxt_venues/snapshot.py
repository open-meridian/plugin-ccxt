"""Write `venues.json`: what the pinned CCXT says each venue `has`, and its
`features` for spot and swap (ruling 166's bump checklist, README).

    python -m ccxt_venues.snapshot > src/ccxt_venues/venues.json

Nothing is asked of any venue: each CCXT class is made and read, offline.
The tests hold the file to what the installed CCXT says, so a bump that
changes a venue's methods fails until the file is written again and the
change read.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import ccxt

from .market import stated
from .venues import CCXT_VERSION, VENUES


def written() -> dict[str, Any]:
    return {
        "ccxt": CCXT_VERSION,
        "installed": ccxt.__version__,
        "venues": {
            venue.id: stated(getattr(ccxt, venue.id)({"options": dict(venue.options)}))
            for venue in VENUES
        },
    }


if __name__ == "__main__":
    json.dump(written(), sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
