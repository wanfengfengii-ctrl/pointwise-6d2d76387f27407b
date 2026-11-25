from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from intake.receive import receive
from intake.repository import init_intake
from issue.publish import publish
from issue.repository import init_issued_packets
from quality.process import init_quality, qualify
from quality.ranges import MeterInterval
from quality.rules import QualityRule
from review.eligibility import ReviewRequest
from review.repository import init_reports
from review.sign import review
from samples.demo import load_day, prepare_day
from source.registration import init_source, register


def fail_initial_receipt_after_report(db):
    db.execute('''
        CREATE TEMP TRIGGER reject_initial_receipt
        BEFORE INSERT ON initial_receipts
        WHEN EXISTS (SELECT 1 FROM reports WHERE report_number = NEW.report_number)
        BEGIN
            SELECT RAISE(ABORT, 'receipt write failed after report insert');
        END
    ''')


class HandoffCase(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory(prefix='handoff-test-')
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.station = self._connect('station.sqlite')
        self.center = self._connect('center.sqlite')
        self.initialize()

    def _connect(self, filename):
        db = sqlite3.connect(self.root / filename)
        self.addCleanup(db.close)
        db.execute('PRAGMA foreign_keys = ON')
        return db

    def initialize(self):
        init_source(self.station)
        init_quality(self.station)
        init_issued_packets(self.station)
        init_intake(self.center)
        init_reports(self.center)

    def close_station(self):
        self.station.close()

    def reopen_station(self):
        self.close_station()
        self.station = self._connect('station.sqlite')

    def reopen_center(self):
        self.center.close()
        self.center = self._connect('center.sqlite')

    def issue_day(self, filename='day1.json'):
        return prepare_day(self.station, load_day(filename))

    def issue_rows(self, rows, window=MeterInterval(0, 6)):
        revision_id = register(self.station, *rows)
        qualify(self.station, revision_id, QualityRule(900, 1100))
        return publish(self.station, revision_id, window)

    def receive_day(self, filename='day1.json'):
        _, packet = self.issue_day(filename)
        return receive(self.center, packet.original)

    def request(self, receipt_id, start, end, suspended_batch=None):
        return review(self.center, ReviewRequest(receipt_id, MeterInterval(start, end), suspended_batch))

    def report_counts(self):
        return self.center.execute('''
            SELECT (SELECT COUNT(*) FROM reports), (SELECT COUNT(*) FROM initial_receipts)
        ''').fetchone()

    def assert_resurvey(self, result):
        self.assertEqual(result.status, 'resurvey')
        self.assertIsNone(result.report)
        self.assertIsNone(result.initial_receipt)

    def assert_signed(self, result, pass_id, strips):
        self.assertEqual(result.status, 'signed')
        self.assertIsNotNone(result.report)
        self.assertIsNotNone(result.initial_receipt)
        self.assertEqual(result.report.pass_id, pass_id)
        self.assertEqual([part.strip_id for part in result.report.evidence], strips)
        self.assertEqual(result.report.report_number, result.initial_receipt.report_number)
