"""Helpers for correction packets that carry meter-by-meter equality grounds."""

from quality.ranges import MeterInterval, intersect
from quality.rules import QualityStatus


CONTINUATION_TYPE = 'continuation'


def is_continuation_body(body: object) -> bool:
    return isinstance(body, dict) and (
        body.get('packet_type') == CONTINUATION_TYPE
        or body.get('kind') == CONTINUATION_TYPE
    )


def build_equality_basis(old_body: dict, old_qualification, new_qualification,
                         new_evidence: list[dict]) -> list[dict]:
    """Record overlaps where the old and new strips have the same mm value.

    The packet deliberately contains neither raw soundings nor converted mm
    values.  An overlap entry is the station's attested equality ground for the
    integer metres in that integer-bounded interval.
    """
    old_slices = {part.strip_id: part for part in old_qualification.slices}
    new_slices = {part.strip_id: part for part in new_qualification.slices}
    basis = []

    for old_item in old_body.get('evidence', []):
        old_strip_id = old_item['strip_id']
        old_slice = old_slices[old_strip_id]
        if old_slice.status != QualityStatus.QUALIFIED or old_slice.depth_mm is None:
            continue
        old_window = MeterInterval(*old_item['window'])

        for new_item in new_evidence:
            new_strip_id = new_item['strip_id']
            new_slice = new_slices[new_strip_id]
            if new_slice.status != QualityStatus.QUALIFIED or new_slice.depth_mm is None:
                continue
            if old_slice.pass_id != new_slice.pass_id:
                continue
            if old_slice.depth_mm != new_slice.depth_mm:
                continue

            new_window = MeterInterval(*new_item['window'])
            overlap = intersect(old_window, new_window)
            if overlap is None:
                continue

            basis.append({
                'old_strip_id': old_strip_id,
                'new_strip_id': new_strip_id,
                'pass_id': new_item['pass_id'],
                'batch_id': new_item['batch_id'],
                'window': [overlap.start, overlap.end],
            })

    return sorted(basis, key=lambda item: (
        item['old_strip_id'], item['window'][0], item['new_strip_id'], item['window'][1]
    ))
