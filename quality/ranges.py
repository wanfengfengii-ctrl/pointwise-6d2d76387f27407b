from dataclasses import dataclass


@dataclass(frozen=True)
class MeterInterval:
    start: int
    end: int


def validate_window(window: MeterInterval) -> None:
    if not isinstance(window, MeterInterval):
        raise ValueError('expected a MeterInterval')
    if type(window.start) is not int or type(window.end) is not int:
        raise ValueError('window endpoints must be integer metres')
    if window.start >= window.end:
        raise ValueError('window must have positive length')


def intersect(left: MeterInterval, right: MeterInterval) -> MeterInterval | None:
    start = max(left.start, right.start)
    end = min(left.end, right.end)
    return MeterInterval(start, end) if start < end else None
