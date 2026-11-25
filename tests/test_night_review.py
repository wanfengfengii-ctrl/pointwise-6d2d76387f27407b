import json
import sqlite3

from intake.dedup import PacketConflict
from intake.receive import receive
from intake.repository import get_accepted
from intake.verify import PacketVerificationError
from issue.envelope import parse_v1
from quality.ranges import MeterInterval
from review.eligibility import ReviewRequestError
from review.retrieve import ReportMissing, retrieve
from review.sign import SigningError
from tests.fixtures import half_pass_rows, independent_packet, survey_rows, wrap_independent_body
from tests.support import HandoffCase, fail_initial_receipt_after_report


class TestNightReview(HandoffCase):
    def test_adjacent_segments_one_pass(self):
        receipt = self.receive_day()
        self.close_station()
        signed = self.request(receipt, 0, 6)
        self.assert_signed(signed, 'A', ['a1', 'a2'])
        self.assertEqual([(part.start, part.end) for part in signed.report.evidence], [(0, 3), (3, 6)])
        self.assertEqual(signed.report.receipt_id, receipt)
        self.assertEqual(retrieve(self.center, signed.report.report_number), (signed.report, signed.initial_receipt))

    def test_damaged_envelope_and_replay(self):
        _, packet = self.issue_day()
        receipt = receive(self.center, packet.original)
        self.assertEqual(receive(self.center, packet.original), receipt)
        for field, value in [('checksum', 'bad'), ('version', 2), ('issue_number', 600)]:
            damaged = json.loads(packet.original)
            damaged[field] = value
            with self.subTest(field=field), self.assertRaises(PacketVerificationError):
                receive(self.center, json.dumps(damaged).encode('ascii'))
        with self.assertRaises(PacketVerificationError):
            receive(self.center, b'not JSON')
        self.assertEqual(get_accepted(self.center, receipt).original, packet.original)
        self.assertEqual(self.center.execute('SELECT COUNT(*) FROM accepted_packets').fetchone(), (1,))

    def test_gap_requires_resurvey(self):
        receipt = self.receive_day()
        self.close_station()
        self.assert_resurvey(self.request(receipt, 5, 7))
        self.assert_resurvey(self.request(receipt, 7, 8))
        self.assertEqual(self.report_counts(), (0, 0))

    def test_batch_suspension_uses_other_pass(self):
        packet = self.issue_rows(survey_rows(
            {'A': 'K', 'Z': 'L'}, [('a', 'A', 0, 6), ('z', 'Z', 0, 6)]
        ))
        receipt = receive(self.center, packet.original)
        self.close_station()
        result = self.request(receipt, 0, 6, 'K')
        self.assert_signed(result, 'Z', ['z'])
        self.assertEqual((result.report.batch_id, result.report.suspended_batch), ('L', 'K'))
        self.assertEqual(self.report_counts(), (1, 1))

    def test_report_commit_failure(self):
        receipt = self.receive_day()
        self.close_station()
        old = self.request(receipt, 0, 6)
        fail_initial_receipt_after_report(self.center)
        with self.assertRaisesRegex(SigningError, 'receipt write failed'):
            self.request(receipt, 0, 6)
        self.reopen_center()
        self.assertEqual(self.report_counts(), (1, 1))
        self.assertEqual(retrieve(self.center, old.report.report_number), (old.report, old.initial_receipt))

    def test_cross_pass_union_is_not_clearance(self):
        packet = self.issue_rows(half_pass_rows())
        control = self.issue_rows(half_pass_rows('A'))
        receipt = receive(self.center, packet.original)
        control_receipt = receive(self.center, control.original)
        self.close_station()
        self.assert_resurvey(self.request(receipt, 0, 6, 'K_K'))
        self.assertEqual(self.report_counts(), (0, 0))
        signed = self.request(receipt, 0, 6)
        self.assert_signed(signed, 'C', ['a3'])
        self.assertEqual((signed.report.start, signed.report.end), (0, 6))
        self.assertEqual(signed.report.batch_id, 'K_K')
        self.assert_signed(self.request(control_receipt, 0, 6, 'K_K'), 'A', ['a1', 'a2'])
        self.assertEqual(self.report_counts(), (2, 2))

    def test_invalid_request(self):
        receipt = self.receive_day()
        self.close_station()
        for args in [(receipt, 3, 3), (receipt, 6, 0), (receipt, False, 1), (receipt + 1, 0, 6)]:
            with self.subTest(args=args), self.assertRaises(ReviewRequestError):
                self.request(*args)
        self.assertEqual(self.report_counts(), (0, 0))

    def test_same_number_conflict(self):
        _, packet = self.issue_day()
        receipt = receive(self.center, packet.original)
        body = parse_v1(packet.original).body
        self.assertEqual(receive(self.center, wrap_independent_body(body)), receipt)
        modified = wrap_independent_body(dict(body, line_id='other-line'))
        self.assertEqual(parse_v1(modified).issue_number, packet.issue_number)
        with self.assertRaises(PacketConflict):
            receive(self.center, modified)
        self.reopen_center()
        self.assertEqual(get_accepted(self.center, receipt).original, packet.original)
        self.assertEqual(self.center.execute('SELECT COUNT(*) FROM accepted_packets').fetchone(), (1,))

    def test_outside_issue_range(self):
        packet = self.issue_rows(survey_rows({'A': 'K'}, [('a', 'A', 0, 8)]), MeterInterval(2, 6))
        receipt = receive(self.center, packet.original)
        self.close_station()
        self.assert_resurvey(self.request(receipt, 1, 6))
        self.assertEqual(self.report_counts(), (0, 0))

    def test_same_batch_alternatives(self):
        base_rows = [('c', 'C', 0, 6), ('d', 'D', 0, 6)]
        with_other = self.issue_rows(survey_rows(
            {'C': 'K', 'D': 'K', 'E': 'L'}, base_rows + [('e1', 'E', 0, 3), ('e2', 'E', 3, 6)]
        ))
        without_other = self.issue_rows(survey_rows({'C': 'K', 'D': 'K'}, base_rows))
        receipt_with = receive(self.center, with_other.original)
        receipt_without = receive(self.center, without_other.original)
        self.close_station()
        self.assert_signed(self.request(receipt_with, 0, 6, 'K'), 'E', ['e1', 'e2'])
        self.assert_resurvey(self.request(receipt_without, 0, 6, 'K'))
        self.assertEqual(self.report_counts(), (1, 1))

    def test_after_report_write(self):
        receipt = self.receive_day()
        self.close_station()
        old = self.request(receipt, 0, 3)
        fail_initial_receipt_after_report(self.center)
        with self.assertRaises(SigningError) as raised:
            self.request(receipt, 3, 6)
        self.assertIsInstance(raised.exception.__cause__, sqlite3.IntegrityError)
        self.assertIn('after report insert', str(raised.exception))
        self.assertFalse(self.center.in_transaction)
        self.reopen_center()
        self.assertEqual(self.report_counts(), (1, 1))
        with self.assertRaises(ReportMissing):
            retrieve(self.center, old.report.report_number + 1)
        self.assertEqual(retrieve(self.center, old.report.report_number), (old.report, old.initial_receipt))
        self.assert_signed(self.request(receipt, 3, 6), 'A', ['a2'])

    def test_consumer_independent_packet(self):
        original = independent_packet()
        receipt = receive(self.center, original)
        self.close_station()
        self.assert_resurvey(self.request(receipt, 0, 6, 'K_K'))
        self.assertEqual(self.report_counts(), (0, 0))
        valid = self.request(receipt, 0, 6)
        self.assert_signed(valid, 'C', ['a3'])
        self.assertEqual((valid.report.issue_number, valid.report.revision_id), (501, 43))
        self.assertEqual(get_accepted(self.center, receipt).original, original)
        self.assertEqual(self.report_counts(), (1, 1))

    def test_wrong_business_body_never_signs(self):
        envelope = json.loads(independent_packet())
        envelope['body']['evidence'][0]['window'] = [0, 4]
        wrong = receive(self.center, wrap_independent_body(envelope['body']))
        self.close_station()
        with self.assertRaisesRegex(ReviewRequestError, 'issued cut'):
            self.request(wrong, 0, 3)
        self.assertEqual(self.report_counts(), (0, 0))

    def test_overlapping_strips_report_only_used_contributions(self):
        packet = self.issue_rows(survey_rows({'A': 'K'}, [
            ('short', 'A', -1, 2), ('long', 'A', 0, 5), ('tail', 'A', 4, 9),
        ]))
        receipt = receive(self.center, packet.original)
        self.close_station()
        result = self.request(receipt, 1, 6)
        self.assert_signed(result, 'A', ['long', 'tail'])
        self.assertEqual([
            (part.start, part.end, part.source_start, part.source_end) for part in result.report.evidence
        ], [(1, 5, 0, 5), (5, 6, 4, 9)])
