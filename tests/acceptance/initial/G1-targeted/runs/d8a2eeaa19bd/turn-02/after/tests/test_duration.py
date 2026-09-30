import pytest
from src import duration


def test_valid_interval_keeps_its_duration():
    assert duration(10, 60) == 50


def test_equal_start_and_end_raises_value_error():
    with pytest.raises(ValueError):
        duration(30, 30)


def test_end_before_start_raises_value_error():
    with pytest.raises(ValueError):
        duration(50, 20)

