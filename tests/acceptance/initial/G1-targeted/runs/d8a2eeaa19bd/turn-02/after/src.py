def duration(start: int, end: int) -> int:
    """Return the duration between integer minute marks."""
    if end <= start:
        raise ValueError("End must be greater than start")
    return end - start

