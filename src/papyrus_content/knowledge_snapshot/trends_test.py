from .trends import change_of


def test_history_gates_the_percent_but_not_the_counts():
    values = [5, 5, 5, 5, 9, 9, 9, 9]
    assert change_of(values).percent == 80
    assert change_of(values, 8).percent == 80
    assert change_of(values, 7).percent is None
    assert change_of(values, 7).last4 == 36
