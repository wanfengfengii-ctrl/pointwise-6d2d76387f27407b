"""Offline demonstration of continuation signing after a sounding correction."""

from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory

from intake.receive import receive
from intake.repository import get_accepted, init_intake
from issue.envelope import parse_v1
from issue.publish import publish, publish_continuation
from issue.repository import init_issued_packets
from review.eligibility import ReviewRequest, ReviewRequestError
from review.repository import init_reports
from review.retrieve import retrieve
from review.sign import continue_review, review
from samples.continuation_case import CHANGED, OLD, SAME, WINDOW, prepare
from source.registration import init_source
from quality.process import init_quality


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys = ON')
    return db


def _witness(result):
    if result.report is None:
        return None
    return [
        [part.strip_id, part.start, part.end, part.source_start, part.source_end]
        for part in result.report.evidence
    ]


def run_demo(root: Path) -> dict:
    station_path = root / 'station.sqlite'
    center_path = root / 'center.sqlite'

    station = _connect(station_path)
    center = _connect(center_path)
    init_source(station)
    init_quality(station)
    init_issued_packets(station)
    init_intake(center)
    init_reports(center)

    old_revision = prepare(station, OLD)
    old_packet = publish(station, old_revision, WINDOW)
    alternate_packet = publish(station, old_revision, WINDOW)
    old_receipt = receive(center, old_packet.original)
    alternate_receipt = receive(center, alternate_packet.original)

    # The source station is closed before the night shift chooses its reports.
    station.close()
    old = review(center, ReviewRequest(old_receipt, WINDOW))
    alternate = review(center, ReviewRequest(alternate_receipt, WINDOW))
    assert old.status == alternate.status == 'signed'

    # The next day's correction issue is made after reopening the station.
    station = _connect(station_path)
    same_revision = prepare(station, SAME)
    changed_revision = prepare(station, CHANGED)
    same_correction = publish_continuation(
        station, old_packet.issue_number, same_revision, WINDOW,
    )
    changed_correction = publish_continuation(
        station, old_packet.issue_number, changed_revision, WINDOW,
    )
    same_correction_receipt = receive(center, same_correction.original)
    changed_correction_receipt = receive(center, changed_correction.original)
    same_binding = parse_v1(same_correction.original).body['continuation_binding']
    station.close()

    # All continuation decisions below are made with the source still offline.
    equal = continue_review(center, old.report.report_number, same_correction_receipt)
    different = continue_review(
        center, old.report.report_number, changed_correction_receipt,
    )
    try:
        continue_review(
            center, alternate.report.report_number, same_correction_receipt,
        )
    except ReviewRequestError as error:
        wrong_binding = f'{type(error).__name__}: {error}'
    else:
        raise AssertionError('alternate issue report must be rejected as a wrong binding')

    assert equal.status == 'signed'
    assert different.status == 'resurvey'
    assert equal.report.old_report_number == old.report.report_number
    report_count_before_reopen = center.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
    receipt_count_before_reopen = center.execute(
        'SELECT COUNT(*) FROM initial_receipts'
    ).fetchone()[0]
    center.close()

    # Reopen the central archive, then collect both generations by number.
    center = _connect(center_path)
    new_bundle = retrieve(center, equal.report.report_number)
    old_bundle = retrieve(center, old.report.report_number)
    correction_accepted = get_accepted(center, same_correction_receipt)
    correction_body = parse_v1(correction_accepted.original).body
    report_count_after_reopen = center.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
    center.close()

    result = {
        'stage': 'source closed for night continuation decisions',
        'old_issue_number': old_packet.issue_number,
        'old_report_number': old.report.report_number,
        'old_witness': _witness(old),
        'correction_binding': same_binding,
        'equal_value': {
            'receipt_id': same_correction_receipt,
            'status': equal.status,
            'continuation_report_number': equal.report.report_number,
            'initial_receipt_number': equal.initial_receipt.receipt_number,
            'witness': _witness(equal),
        },
        'changed_to_1001_mm': {
            'receipt_id': changed_correction_receipt,
            'status': different.status,
            'report': different.report,
            'initial_receipt': different.initial_receipt,
        },
        'wrong_binding': wrong_binding,
        'reopen_retrieval': {
            'new_by_number': new_bundle == (equal.report, equal.initial_receipt),
            'new_initial_receipt': new_bundle[1].receipt_number,
            'old_by_number': old_bundle == (old.report, old.initial_receipt),
            'old_initial_receipt': old_bundle[1].receipt_number,
            'new_source_receipt': correction_accepted.receipt_id,
            'new_source_issue': correction_body['issue_number'],
            'new_source_evidence': correction_body['evidence'],
        },
        'report_counts': [
            report_count_before_reopen, report_count_after_reopen,
            receipt_count_before_reopen,
        ],
        'narration_zh': {
            '关源后选报': f'站库已关闭；旧报告 #{old.report.report_number} 按实收 {old_receipt} 签发',
            '等值拆段': f'b1[0,3)+b2[3,6) 均为旧值，接续报告 #{equal.report.report_number} 签发',
            '异值拒签': 'b2 改为 1001 mm 后只能待复测，不写报告或首执',
            '错绑拒绝': wrong_binding,
            '重开复领': f'重开中心库后，新号 {equal.report.report_number} 与旧号 {old.report.report_number} 均可领取报告和首执',
        },
    }
    print('POINTWISE_CONTINUATION ' + json.dumps(result, ensure_ascii=False, sort_keys=True))
    assert report_count_before_reopen == report_count_after_reopen == 3
    assert receipt_count_before_reopen == 3
    assert result['reopen_retrieval']['new_by_number']
    assert result['reopen_retrieval']['old_by_number']
    return result


def main() -> None:
    with TemporaryDirectory(prefix='continuation-demo-') as directory:
        run_demo(Path(directory))


if __name__ == '__main__':
    main()
