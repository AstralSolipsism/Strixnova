import pytest
from src import duration


def test_valid_interval_keeps_its_duration():
    assert duration(10, 60) == 50


def test_duration_equal_scale_raises_value_error():
    with pytest.raises(ValueError, match="end must be greater than start"):
        duration(10, 10)


def test_duration_end_before_start_raises_value_error():
    with pytest.raises(ValueError, match="end must be greater than start"):
        duration(20, 10)
