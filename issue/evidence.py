from issue.selection import IssueSelection
from quality.ranges import intersect
from quality.rules import QualityStatus


def project_evidence(selection: IssueSelection) -> list[dict]:
    evidence = []
    for part in selection.qualification.slices:
        if part.status != QualityStatus.QUALIFIED:
            continue
        clipped = intersect(part.window, selection.window)
        if clipped is not None:
            evidence.append({
                'pass_id': part.pass_id,
                'batch_id': part.batch_id,
                'strip_id': part.strip_id,
                'window': [clipped.start, clipped.end],
                'source_window': [part.window.start, part.window.end],
            })
    return sorted(evidence, key=lambda item: (item['pass_id'], item['window'], item['strip_id']))
