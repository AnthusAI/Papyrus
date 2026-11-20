"""The period a periodic Delivery names to Caducus (behaviour: features_backend/announcements/cadence-family.feature)."""
from datetime import datetime, timezone

import pytest

from papyrus_content.list_cadence.list_cadence_test import entry

from .email_channel import CaducusEmail
from .records import RecordError

LISTS = {"every-item": entry("each", family="new-stories"), "daily": entry("daily", family="new-stories", sendAt={"time": "06:00"}),
         "weekly": entry("weekly", sendAt={"day": "monday", "time": "04:00"})}


def channel():
    return CaducusEmail(None, None, "alpha", lambda row, text: {}, clock=lambda: datetime(2026, 11, 5, tzinfo=timezone.utc), lists=LISTS)


def row(*audience, release="2026-11-06T11:00:00Z"):
    return {"id": "d1", "audience": list(audience), "releaseAt": release}


def test_a_daily_delivery_names_the_start_of_its_period():
    assert channel().audience_as_of(row("daily")) == "2026-11-05T11:00:00Z"


def test_a_weekly_delivery_names_the_start_of_its_week():
    assert channel().audience_as_of(row("weekly", release="2026-11-16T09:00:00Z")) == "2026-11-09T09:00:00Z"


def test_an_every_item_delivery_names_none():
    assert channel().audience_as_of(row("every-item")) is None


@pytest.mark.parametrize("audience", [("daily", "every-item"), ("daily", "weekly")])
def test_a_summary_names_one_periodic_list(audience):
    with pytest.raises(RecordError):
        channel().audience_as_of(row(*audience))
