def duration(start: int, end: int) -> int:
    if end <= start:
        raise ValueError("end must be greater than start")
    print("debug", start, end)
    return start - end
