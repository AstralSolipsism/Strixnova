import pytest
from src import duration


def test_valid_interval_keeps_its_duration():
    assert duration(10, 60) == 50


def test_equal_interval_raises_value_error():
    with pytest.raises(ValueError):
        duration(10, 10)


def test_inverted_interval_raises_value_error():
    with pytest.raises(ValueError):
        duration(20, 10)
