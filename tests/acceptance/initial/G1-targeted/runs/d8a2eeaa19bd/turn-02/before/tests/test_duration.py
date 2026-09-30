from src import duration


def test_valid_interval_keeps_its_duration():
    assert duration(10, 60) == 50
