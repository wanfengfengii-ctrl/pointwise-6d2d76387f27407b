from collections.abc import Iterable
from dataclasses import dataclass, replace

from quality.ranges import MeterInterval, validate_window


@dataclass(frozen=True)
class EvidenceSlice:
    pass_id: str
    batch_id: str
    strip_id: str
    window: MeterInterval
    source_window: MeterInterval


@dataclass(frozen=True)
class CoverageWitness:
    pass_id: str
    batch_id: str
    pieces: tuple[EvidenceSlice, ...]


def _cover_one_pass(slices: list[EvidenceSlice], window: MeterInterval) -> tuple[EvidenceSlice, ...] | None:
    ordered = sorted(slices, key=lambda part: (part.window.start, part.strip_id))
    cursor = window.start
    pending = 0
    pieces = []
    while cursor < window.end:
        farthest = None
        while pending < len(ordered) and ordered[pending].window.start <= cursor:
            candidate = ordered[pending]
            pending += 1
            if candidate.window.end > cursor and (
                farthest is None or candidate.window.end > farthest.window.end
            ):
                farthest = candidate
        if farthest is None:
            return None
        stop = min(window.end, farthest.window.end)
        pieces.append(replace(farthest, window=MeterInterval(cursor, stop)))
        cursor = stop
    return tuple(pieces)


def find_witness(
    evidence: Iterable[EvidenceSlice], window: MeterInterval, suspended_batch: str | None = None,
) -> CoverageWitness | None:
    validate_window(window)
    by_pass: dict[tuple[str, str], list[EvidenceSlice]] = {}
    for part in evidence:
        if part.batch_id != suspended_batch:
            by_pass.setdefault((part.pass_id, part.batch_id), []).append(part)
    for (pass_id, batch_id), slices in sorted(by_pass.items()):
        pieces = _cover_one_pass(slices, window)
        if pieces is not None:
            return CoverageWitness(pass_id, batch_id, pieces)
    return None
