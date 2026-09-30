def duration(start: int, end: int) -> int:
    if end <= start:
        raise ValueError("end must be greater than start")
    return end - start
