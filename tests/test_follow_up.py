from intake.receive import receive
from intake.repository import get_accepted
from issue.envelope import parse_v1
from issue.publish import publish
from issue.repository import load_issued_packet
from quality.process import QualityError, load_qualification, qualify
from quality.ranges import MeterInterval
from quality.rules import QualityRule
from review.retrieve import ReportMissing, retrieve
from samples.demo import load_day, register_day
from source.revisions import load_revision
from tests.support import HandoffCase


class TestFollowUp(HandoffCase):
    def test_new_revision_and_old_report(self):
        old_quality, old_packet = self.issue_day()
        old_receipt = receive(self.center, old_packet.original)
        self.close_station()
        old = self.request(old_receipt, 0, 6)
        self.assert_signed(old, 'A', ['a1', 'a2'])
        self.reopen_station()
        new_quality, new_packet = self.issue_day('day2.json')
        new_receipt = receive(self.center, new_packet.original)
        self.assertNotEqual(new_quality.revision_id, old_quality.revision_id)
        self.assertNotEqual(new_receipt, old_receipt)
        self.close_station()
        self.reopen_center()
        new = self.request(new_receipt, 5, 7)
        self.assert_signed(new, 'A', ['a2', 'a3'])
        self.assertEqual(new.report.revision_id, new_quality.revision_id)
        self.assertEqual(retrieve(self.center, old.report.report_number), (old.report, old.initial_receipt))
        self.assertEqual(self.report_counts(), (2, 2))

    def test_frozen_revision(self):
        first, packet = self.issue_day()
        frozen = load_revision(self.station, first.revision_id)
        locked = load_qualification(self.station, first.revision_id)
        second, _ = self.issue_day('day2.json')
        self.reopen_station()
        self.assertNotEqual(first.revision_id, second.revision_id)
        self.assertEqual(frozen.state, 'frozen')
        self.assertTrue(locked.frozen)
        self.assertEqual(load_revision(self.station, first.revision_id), frozen)
        self.assertEqual(load_qualification(self.station, first.revision_id), locked)
        self.assertEqual(load_issued_packet(self.station, packet.issue_number), packet)
        with self.assertRaises(QualityError):
            qualify(self.station, first.revision_id, QualityRule(0, 3000))
        reissue = publish(self.station, first.revision_id, MeterInterval(5, 7))
        self.assertNotEqual(reissue.issue_number, packet.issue_number)
        self.assertEqual([part['strip_id'] for part in parse_v1(reissue.original).body['evidence']], ['a2'])
        self.assertEqual(load_issued_packet(self.station, packet.issue_number).original, packet.original)

    def test_explicit_receipt(self):
        old_receipt = self.receive_day()
        old = self.request(old_receipt, 0, 6)
        new_receipt = self.receive_day('day2.json')
        new_packet = get_accepted(self.center, new_receipt)
        self.close_station()
        self.assert_resurvey(self.request(old_receipt, 5, 7))
        self.assertEqual(self.report_counts(), (1, 1))
        new = self.request(new_receipt, 5, 7)
        self.assert_signed(new, 'A', ['a2', 'a3'])
        self.assertEqual(new.report.receipt_id, new_receipt)
        self.assertEqual(new.report.issue_number, new_packet.issue_number)
        self.assertEqual(new.report.packet_checksum, new_packet.checksum)
        self.assert_resurvey(self.request(old_receipt, 5, 7))
        self.assertEqual(self.report_counts(), (2, 2))
        self.assertEqual(retrieve(self.center, old.report.report_number), (old.report, old.initial_receipt))

    def test_repeat_initialization(self):
        quality, packet = self.issue_day()
        receipt = receive(self.center, packet.original)
        report = self.request(receipt, 0, 6)
        user_revision = register_day(self.station, load_day('day2.json'))
        before = load_revision(self.station, user_revision)
        self.initialize()
        self.reopen_station()
        self.reopen_center()
        self.assertEqual(load_revision(self.station, user_revision), before)
        self.assertEqual(before.state, 'working')
        self.assertEqual(load_revision(self.station, quality.revision_id).state, 'frozen')
        self.assertTrue(load_qualification(self.station, quality.revision_id).frozen)
        self.assertEqual(load_issued_packet(self.station, packet.issue_number), packet)
        self.assertEqual(get_accepted(self.center, receipt).original, packet.original)
        self.assertEqual(retrieve(self.center, report.report.report_number), (report.report, report.initial_receipt))
        self.assertEqual(self.report_counts(), (1, 1))

    def test_missing_report(self):
        receipt = self.receive_day()
        self.close_station()
        saved = self.request(receipt, 0, 6)
        self.reopen_center()
        with self.assertRaises(ReportMissing):
            retrieve(self.center, saved.report.report_number + 1)
        self.assertEqual(self.report_counts(), (1, 1))
