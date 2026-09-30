def duration(start: int, end: int) -> int:
    """Return the duration between integer minute marks."""
    if end <= start:
        raise ValueError(f"end ({end}) must be greater than start ({start})")
    return end - start
