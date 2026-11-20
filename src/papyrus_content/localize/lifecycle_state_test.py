import pytest

from papyrus_content import lifecycles
from papyrus_content.localize import desired_state, lifecycle_state

SOURCE = {"lineageId": "story", "versionNumber": 2, "contentHash": "h2"}


def request(state, version=2):
    return {"id": "story#es", "state": state, "sourceVersionNumber": version, "reason": None}


def test_every_state_a_request_can_have_has_one_lifecycle_state():
    assert set(lifecycle_state.OF_REQUEST) == set(desired_state.STATES)
    assert set(lifecycle_state.OF_REQUEST.values()) <= set(lifecycle_state.STATES)


def test_the_states_are_the_stages_of_the_lifecycle_file():
    assert {stage.id for stage in lifecycles.load("Translation").stages} == set(lifecycle_state.STATES)


@pytest.mark.parametrize("version, expected", [(1, "stale"), (2, "published")])
def test_a_request_for_an_older_source_is_stale(version, expected):
    assert lifecycle_state.state_of(request("published", version), SOURCE)["state"] == expected


def test_no_request_is_wanted_with_a_reason():
    assert lifecycle_state.state_of(None, SOURCE) == {"state": "wanted", "reason": "no translation has been requested for this language yet"}


def test_an_unknown_request_state_is_refused():
    with pytest.raises(ValueError, match="does not know"):
        lifecycle_state.state_of(request("paused"), SOURCE)
