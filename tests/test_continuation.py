import json

from intake.receive import receive
from issue.envelope import parse_v1
from issue.publish import publish, publish_continuation, PublishError
from quality.process import load_qualification
from quality.ranges import MeterInterval
from quality.rules import QualityRule
from review.eligibility import ReviewRequestError
from review.retrieve import retrieve
from review.sign import SigningError, continue_review
from samples.continuation_case import (
    CHANGED, OLD, OVERLAP_NEW, OVERLAP_OLD, SAME, WINDOW, prepare,
)
from source.calibrations import CalibrationBatch
from source.lines import SurveyLine
from source.passes import SurveyPass
from source.registration import register
from source.strips import RawStrip
from tests.support import HandoffCase, fail_initial_receipt_after_report


THIRD_NEW = (
    ('b1', 0, 6, '1000', 'mm'),
    ('b2', 4, 6, '1001', 'mm'),
)


class ContinuationReviewTest(HandoffCase):
    def _publish_correction(self, old_packet, rows, window=WINDOW):
        revision = prepare(self.station, rows)
        packet = publish_continuation(
            self.station, old_packet.issue_number, revision, window,
        )
        return revision, packet, receive(self.center, packet.original)

    def test_equal_split_continues_and_value_change_requires_resurvey(self):
        old_revision = prepare(self.station, OLD)
        old_packet = publish(self.station, old_revision, WINDOW)
        old_receipt = receive(self.center, old_packet.original)
        self.close_station()

        old = self.request(old_receipt, 0, 6)
        self.assert_signed(old, 'A', ['a1'])
        old_number = old.report.report_number

        self.reopen_station()
        same_revision, same_packet, same_receipt = self._publish_correction(old_packet, SAME)
        _, changed_packet, changed_receipt = self._publish_correction(old_packet, CHANGED)
        self.assertNotEqual(same_packet.issue_number, changed_packet.issue_number)
        self.close_station()

        equal = continue_review(self.center, old_number, same_receipt)
        self.assertEqual(equal.status, 'signed')
        self.assertEqual(equal.report.old_report_number, old_number)
        self.assertEqual(equal.report.receipt_id, same_receipt)
        self.assertEqual(equal.report.issue_number, same_packet.issue_number)
        self.assertEqual(equal.report.packet_checksum, parse_v1(same_packet.original).checksum)
        self.assertEqual(equal.report.revision_id, same_revision)
        self.assertEqual(equal.report.line_id, 'Q')
        self.assertEqual(equal.report.start, 0)
        self.assertEqual(equal.report.end, 6)
        self.assertEqual(equal.report.pass_id, 'A')
        self.assertEqual(equal.report.batch_id, 'K')
        self.assertEqual(
            [(p.strip_id, p.start, p.end, p.source_start, p.source_end)
             for p in equal.report.evidence],
            [('b1', 0, 3, 0, 3), ('b2', 3, 6, 3, 6)],
        )

        changed = continue_review(self.center, old_number, changed_receipt)
        self.assert_resurvey(changed)
        self.assertEqual(self.report_counts(), (2, 2))

        self.reopen_center()
        self.assertEqual(
            retrieve(self.center, equal.report.report_number),
            (equal.report, equal.initial_receipt),
        )
        self.assertEqual(
            retrieve(self.center, old_number),
            (old.report, old.initial_receipt),
        )
        self.assertEqual(self.report_counts(), (2, 2))

    def test_overlapping_old_segments_select_actual_report_basis(self):
        old_revision = prepare(self.station, OVERLAP_OLD)
        new_revision = prepare(self.station, OVERLAP_NEW)
        old_packet = publish(self.station, old_revision, MeterInterval(0, 6))
        alternate_packet = publish(self.station, old_revision, MeterInterval(0, 6))
        correction = publish_continuation(
            self.station, old_packet.issue_number, new_revision, MeterInterval(0, 6),
        )
        old_receipt = receive(self.center, old_packet.original)
        alternate_receipt = receive(self.center, alternate_packet.original)
        correction_receipt = receive(self.center, correction.original)
        self.close_station()

        early = self.request(old_receipt, 0, 4)
        late = self.request(old_receipt, 2, 6)
        alternate = self.request(alternate_receipt, 0, 4)
        self.assert_signed(early, 'A', ['a1'])
        self.assert_signed(late, 'A', ['a2'])

        continued_early = continue_review(
            self.center, early.report.report_number, correction_receipt,
        )
        self.assertEqual(
            [(p.strip_id, p.start, p.end, p.source_start, p.source_end)
             for p in continued_early.report.evidence],
            [('b1', 0, 4, 0, 6)],
        )
        self.assert_resurvey(continue_review(
            self.center, late.report.report_number, correction_receipt,
        ))

        with self.assertRaises(ReviewRequestError):
            continue_review(
                self.center, alternate.report.report_number, correction_receipt,
            )
        self.assertEqual(self.report_counts(), (4, 4))

    def test_old_boundary_is_respected_when_new_cover_overlaps(self):
        old_revision = prepare(self.station, OVERLAP_OLD)
        new_revision = prepare(self.station, THIRD_NEW)
        old_packet = publish(self.station, old_revision, MeterInterval(0, 6))
        correction = publish_continuation(
            self.station, old_packet.issue_number, new_revision, MeterInterval(0, 6),
        )
        old_receipt = receive(self.center, old_packet.original)
        correction_receipt = receive(self.center, correction.original)
        self.close_station()

        old = self.request(old_receipt, 0, 6)
        self.assertEqual(
            [(p.strip_id, p.start, p.end, p.source_start, p.source_end)
             for p in old.report.evidence],
            [('a1', 0, 4, 0, 4), ('a2', 4, 6, 2, 6)],
        )

        continued = continue_review(self.center, old.report.report_number, correction_receipt)
        self.assertEqual(continued.status, 'signed')
        self.assertEqual(
            [(p.strip_id, p.start, p.end, p.source_start, p.source_end)
             for p in continued.report.evidence],
            [('b1', 0, 4, 0, 6), ('b2', 4, 6, 4, 6)],
        )

    def test_invalid_and_mismatched_references_are_rejected(self):
        old_revision = prepare(self.station, OLD)
        old_packet = publish(self.station, old_revision, WINDOW)
        old_receipt = receive(self.center, old_packet.original)
        old = self.request(old_receipt, 0, 6)

        new_revision = prepare(self.station, SAME)
        correction = publish_continuation(
            self.station, old_packet.issue_number, new_revision, WINDOW,
        )
        correction_receipt = receive(self.center, correction.original)
        continued = continue_review(
            self.center, old.report.report_number, correction_receipt,
        )

        for old_reference, receipt in [
            (old.report.report_number + 100, correction_receipt),
            (old.report.report_number, correction_receipt + 100),
            (old.report.report_number, old_receipt),
            (continued.report.report_number, correction_receipt),
        ]:
            with self.subTest(old_reference=old_reference, receipt=receipt):
                with self.assertRaises(ReviewRequestError):
                    continue_review(self.center, old_reference, receipt)
        self.assertEqual(self.report_counts(), (2, 2))

    def test_signing_failure_leaves_no_continuation_result(self):
        old_revision = prepare(self.station, OLD)
        old_packet = publish(self.station, old_revision, WINDOW)
        old_receipt = receive(self.center, old_packet.original)
        old = self.request(old_receipt, 0, 6)

        new_revision = prepare(self.station, SAME)
        correction = publish_continuation(
            self.station, old_packet.issue_number, new_revision, WINDOW,
        )
        correction_receipt = receive(self.center, correction.original)
        fail_initial_receipt_after_report(self.center)

        with self.assertRaisesRegex(SigningError, 'receipt write failed'):
            continue_review(self.center, old.report.report_number, correction_receipt)
        self.assertFalse(self.center.in_transaction)
        self.reopen_center()
        self.assertEqual(self.report_counts(), (1, 1))
        self.assertEqual(
            retrieve(self.center, old.report.report_number),
            (old.report, old.initial_receipt),
        )

    def test_publish_continuation_binds_and_preserves_station_state(self):
        old_revision = prepare(self.station, OLD)
        old_packet = publish(self.station, old_revision, WINDOW)
        new_revision = prepare(self.station, SAME)
        correction = publish_continuation(
            self.station, old_packet.issue_number, new_revision, WINDOW,
        )
        body = parse_v1(correction.original).body
        old_body = parse_v1(old_packet.original).body
        self.assertEqual(body['old_issue_number'], old_packet.issue_number)
        self.assertEqual(body['old_body_checksum'], parse_v1(old_packet.original).checksum)
        self.assertEqual(
            body['continuation_binding'],
            {'old_issue_number': old_packet.issue_number,
             'old_body_checksum': parse_v1(old_packet.original).checksum},
        )
        self.assertEqual(body['revision_id'], new_revision)
        self.assertEqual(body['window'], [0, 6])
        self.assertTrue(body['equality_basis'])
        serialized = json.dumps(body)
        self.assertNotIn('depth', serialized.lower())
        self.assertNotIn('raw_depth', serialized)

        with self.assertRaises(PublishError):
            publish_continuation(self.station, correction.issue_number, new_revision, WINDOW)
        with self.assertRaises(PublishError):
            publish_continuation(self.station, old_packet.issue_number + 100,
                                 new_revision, WINDOW)
        with self.assertRaises(PublishError):
            publish_continuation(self.station, old_packet.issue_number,
                                 old_revision, WINDOW)
        with self.assertRaises(PublishError):
            publish_continuation(self.station, old_packet.issue_number,
                                 new_revision, MeterInterval(6, 0))

        other_revision = register(
            self.station, SurveyLine('OTHER'), [CalibrationBatch('K')],
            [SurveyPass('A', 'K')],
            [RawStrip('x', 'A', MeterInterval(0, 6), '1000', 'mm')],
        )
        from quality.process import qualify
        qualify(self.station, other_revision, QualityRule(900, 1100))
        with self.assertRaisesRegex(PublishError, 'different survey line'):
            publish_continuation(
                self.station, old_packet.issue_number, other_revision, WINDOW,
            )

        pending_revision = prepare(self.station, SAME)
        self.station.execute('''
            CREATE TEMP TRIGGER reject_continuation_archive
            BEFORE INSERT ON issued_packets
            BEGIN SELECT RAISE(ABORT, 'continuation archive rejected'); END
        ''')
        with self.assertRaisesRegex(PublishError, 'continuation archive rejected'):
            publish_continuation(
                self.station, old_packet.issue_number, pending_revision, WINDOW,
            )
        self.reopen_station()
        qualification = load_qualification(self.station, pending_revision)
        self.assertFalse(qualification.frozen)
        self.assertEqual(
            self.station.execute('SELECT COUNT(*) FROM issued_packets').fetchone()[0], 2,
        )
        stored = publish_continuation(
            self.station, old_packet.issue_number, pending_revision, WINDOW,
        )
        self.assertEqual(
            parse_v1(stored.original).body['old_body_checksum'],
            parse_v1(old_packet.original).checksum,
        )

    def test_correction_reception_replay(self):
        old_revision = prepare(self.station, OLD)
        old_packet = publish(self.station, old_revision, WINDOW)
        new_revision = prepare(self.station, SAME)
        correction = publish_continuation(
            self.station, old_packet.issue_number, new_revision, WINDOW,
        )
        first = receive(self.center, correction.original)
        self.assertEqual(receive(self.center, correction.original), first)
        self.assertEqual(
            self.center.execute('SELECT COUNT(*) FROM accepted_packets').fetchone(), (1,),
        )
