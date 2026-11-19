"""What this version declares (declared.py, declaration.py): every venue's
datasets on the UTC day, naming the venue as vendor and no aggregator, its
terms described within the bound; a switch per venue, off; the broker
attribution off; stage B's credentials secret; sample data last."""

from __future__ import annotations

from ccxt_venues.declaration import DECLARATION
from ccxt_venues.declared import CATALOGUE, SETTINGS, STAGE_B_CREDENTIALS
from ccxt_venues.venues import VENUES


def test_each_venue_declares_its_own_datasets() -> None:
    assert list(DECLARATION.catalogue) == list(CATALOGUE)
    by_key = {d.key: d for d in CATALOGUE}
    for venue in VENUES:
        for key in venue.offers:
            entry = by_key[f"{venue.id}_{key}"]
            assert entry.vendor == venue.name and entry.aggregator == ""
            assert (entry.day_time_zone, entry.day_end_minute) == ("Etc/UTC", 0)
            assert venue.name in entry.terms_and_pricing and venue.restricted[:20] in (
                entry.terms_and_pricing
            )
            assert len(entry.terms_and_pricing) <= 2000
    assert all("meridian.v1.Quote" not in d.data_types for d in CATALOGUE)
    assert not [d for d in CATALOGUE if d.key.endswith("_trades")]


def test_every_venue_is_off_until_a_deployment_admin_turns_it_on() -> None:
    named = {s.name: s for s in SETTINGS}
    for venue in VENUES:
        switch = named[f"venue_{venue.id}"]
        assert switch.kind is bool and switch.default is False and not switch.secret
    assert named["broker_tags"].default is False
    for venue_id, held in STAGE_B_CREDENTIALS.items():
        for name, _ in held:
            assert named[f"{venue_id}_{name}"].secret
    assert SETTINGS[-1].name == "sample_data"
