from papyrus_content.announcements.settle_after_post import delivery_of_event, settle_after_post


def test_the_delivery_is_read_from_an_attempt_event_id():
    assert delivery_of_event("delivery:announcement-1#x#2121#g1:a3") == "announcement-1#x#2121#g1"
    assert delivery_of_event("delivery:announcement-1#x#2121#g1:ax") is None
    assert delivery_of_event("story-published:slow-water") is None


def test_an_event_that_names_no_x_delivery_settles_nothing():
    class NoRows:
        def get(self, row_id):
            return {"id": row_id, "channel": "email", "accountId": "list"} if row_id == "email-delivery" else None

    assert settle_after_post(NoRows(), object(), "delivery:missing:a1") is None
    assert settle_after_post(NoRows(), object(), "delivery:email-delivery:a1") is None
