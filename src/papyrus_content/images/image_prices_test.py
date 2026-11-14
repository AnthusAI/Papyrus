from .image_prices import actual_cost, estimate_cost


def test_flare_has_no_per_image_price_so_the_estimate_is_unpriced_never_free():
    assert estimate_cost("gpt-image-2.5-flare", 4, "standard")["priced"] is False
    assert estimate_cost("some-unlisted-model", 1, "standard")["priced"] is False


def test_cost_is_worked_out_from_reported_tokens_at_the_published_rates():
    assert actual_cost("gpt-image-2.5-flare", 40, 1000, "standard") == 0.03032


def test_batch_cost_is_not_guessed_because_batch_input_is_not_published():
    assert actual_cost("gpt-image-2.5-flare", 40, 1000, "batch") is None
    assert actual_cost("some-unlisted-model", 40, 1000, "standard") is None
