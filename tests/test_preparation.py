from dataclasses import replace

from issue.envelope import parse_v1
from issue.publish import PublishError, publish
from issue.repository import load_issued_packet
from quality.process import QualityError, load_qualification, qualify
from quality.ranges import MeterInterval
from quality.rules import QualityRule, QualityStatus
from quality.units import depth_to_mm
from samples.demo import load_day, register_day
from source.lines import SurveyLine, load_line
from source.passes import SurveyPass
from source.registration import RegistrationError, register
from source.revisions import load_revision
from source.strips import RawStrip
from tests.fixtures import half_pass_rows, survey_rows
from tests.support import HandoffCase


class TestPreparation(HandoffCase):
    def test_units_and_quality_ranges(self):
        quality, packet = self.issue_day()
        self.assertEqual([(part.strip_id, part.depth_mm, part.status) for part in quality.slices], [
            ('a1', 1000, QualityStatus.QUALIFIED), ('a2', 1000, QualityStatus.QUALIFIED),
            ('a3', None, QualityStatus.MISSING), ('a4', 1200, QualityStatus.OUT_OF_RANGE),
        ])
        body = parse_v1(packet.original).body
        self.assertEqual(body['revision_id'], quality.revision_id)
        self.assertEqual(body['window'], [0, 8])
        self.assertEqual([(part['strip_id'], part['window']) for part in body['evidence']],
                         [('a1', [0, 3]), ('a2', [3, 6])])
        for field in ('depth', 'depth_mm', 'raw_depth', 'unit'):
            self.assertNotIn(field, body)
            for part in body['evidence']:
                self.assertNotIn(field, part)
        self.assertEqual(load_revision(self.station, quality.revision_id).strips[0].depth, '1.000')

    def test_unknown_calibration_batch(self):
        with self.assertRaisesRegex(RegistrationError, 'unknown calibration batch'):
            register(self.station, SurveyLine('Q'), [], [SurveyPass('A', 'no-batch')],
                     [RawStrip('a', 'A', MeterInterval(0, 3), '100', 'cm')])
        with self.assertRaises(KeyError):
            load_revision(self.station, 1)
        with self.assertRaises(KeyError):
            load_line(self.station, 'Q')

    def test_mixed_units_threshold(self):
        values = [('1.000', 'm'), ('100', 'cm'), ('900', 'mm'),
                  ('1.1004', 'm'), ('1.1005', 'm'), ('899.49', 'mm'), ('0', 'mm')]
        line, batches, passes, strips = survey_rows(
            {'A': 'K'}, [(f'a{index}', 'A', index, index + 1) for index in range(len(values))]
        )
        strips = [replace(part, depth=value, unit=unit) for part, (value, unit) in zip(strips, values)]
        revision = register(self.station, line, batches, passes, strips)
        quality = qualify(self.station, revision, QualityRule(900, 1100))
        self.assertEqual([part.depth_mm for part in quality.slices], [1000, 1000, 900, 1100, 1101, 899, 0])
        self.assertEqual([part.status.value for part in quality.slices],
                         ['qualified'] * 4 + ['out_of_range'] * 3)
        packet = publish(self.station, revision, MeterInterval(0, 7))
        self.assertEqual([item['strip_id'] for item in parse_v1(packet.original).body['evidence']],
                         ['a0', 'a1', 'a2', 'a3'])
        self.assertEqual(depth_to_mm('-0.0005', 'm'), -1)
        self.assertEqual(depth_to_mm('123456789012345678901234567890.5', 'mm'),
                         123456789012345678901234567891)

    def test_missing_depth(self):
        quality, packet = self.issue_day()
        snapshot = load_revision(self.station, quality.revision_id)
        self.assertIsNone(next(strip for strip in snapshot.strips if strip.strip_id == 'a3').depth)
        stored = load_qualification(self.station, quality.revision_id)
        missing = next(part for part in stored.slices if part.strip_id == 'a3')
        self.assertEqual((missing.status, missing.depth_mm, missing.window),
                         (QualityStatus.MISSING, None, MeterInterval(6, 7)))
        self.assertNotIn('a3', [part['strip_id'] for part in parse_v1(packet.original).body['evidence']])

    def test_bad_rule(self):
        for value, unit, rule in [('1000', 'in', QualityRule(900, 1100)),
                                  ('NaN', 'mm', QualityRule(900, 1100)),
                                  ('1000', 'mm', QualityRule(1100, 900))]:
            with self.subTest(value=value, unit=unit, rule=rule):
                line, batches, passes, strips = survey_rows({'A': 'K'}, [('a', 'A', 0, 6)])
                revision = register(self.station, line, batches, passes,
                                    [replace(strips[0], depth=value, unit=unit)])
                with self.assertRaises(QualityError):
                    qualify(self.station, revision, rule)
                with self.assertRaises(QualityError):
                    load_qualification(self.station, revision)
                with self.assertRaises(PublishError):
                    publish(self.station, revision, MeterInterval(0, 6))
                self.assertEqual(load_revision(self.station, revision).state, 'working')
        valid = register_day(self.station, load_day('day1.json'))
        prior = qualify(self.station, valid, QualityRule(1000, 1000))
        with self.assertRaises(QualityError):
            qualify(self.station, valid, QualityRule(1, 0))
        self.assertEqual(load_qualification(self.station, valid), prior)
        replaced = qualify(self.station, valid, QualityRule(1200, 1200))
        self.assertEqual(load_qualification(self.station, valid), replaced)
        self.assertEqual([part.strip_id for part in replaced.slices if part.status == QualityStatus.QUALIFIED],
                         ['a4'])
        with self.assertRaises(KeyError):
            load_issued_packet(self.station, 1)

    def test_pass_projection(self):
        separate = self.issue_rows(half_pass_rows('B'))
        adjacent = self.issue_rows(half_pass_rows('A'))

        def bindings(packet):
            return {item['strip_id']: (item['pass_id'], item['batch_id'], item['window'])
                    for item in parse_v1(packet.original).body['evidence']}

        self.assertEqual(bindings(separate), {
            'a1': ('A', 'K_L', [0, 3]), 'a2': ('B', 'K_L', [3, 6]), 'a3': ('C', 'K_K', [0, 6]),
        })
        self.assertEqual(bindings(adjacent), {
            'a1': ('A', 'K_L', [0, 3]), 'a2': ('A', 'K_L', [3, 6]), 'a3': ('C', 'K_K', [0, 6]),
        })

    def test_issue_clip(self):
        packet = self.issue_rows(survey_rows({'A': 'K'}, [('a', 'A', 0, 8)]), MeterInterval(2, 6))
        body = parse_v1(packet.original).body
        self.assertEqual(body['window'], [2, 6])
        self.assertEqual(len(body['evidence']), 1)
        part, = body['evidence']
        self.assertEqual((part['window'], part['source_window'], part['strip_id']), ([2, 6], [0, 8], 'a'))

    def test_invalid_issue(self):
        revision = register_day(self.station, load_day('day1.json'))
        prior = qualify(self.station, revision, QualityRule(900, 1100))
        with self.assertRaises(PublishError):
            publish(self.station, revision, MeterInterval(8, 2))
        self.station.execute('''
            CREATE TEMP TRIGGER reject_freeze BEFORE UPDATE OF state ON revisions
            BEGIN SELECT RAISE(ABORT, 'freeze rejected'); END
        ''')
        with self.assertRaisesRegex(PublishError, 'freeze rejected'):
            publish(self.station, revision, MeterInterval(0, 8))
        self.station.execute('DROP TRIGGER reject_freeze')
        self.station.execute('''
            CREATE TEMP TRIGGER reject_issue BEFORE INSERT ON issued_packets
            BEGIN SELECT RAISE(ABORT, 'archive rejected'); END
        ''')
        with self.assertRaisesRegex(PublishError, 'archive rejected'):
            publish(self.station, revision, MeterInterval(0, 8))
        self.reopen_station()
        self.assertEqual(load_revision(self.station, revision).state, 'working')
        self.assertEqual(load_qualification(self.station, revision), prior)
        with self.assertRaises(KeyError):
            load_issued_packet(self.station, 1)
        packet = publish(self.station, revision, MeterInterval(0, 8))
        self.assertEqual(load_issued_packet(self.station, packet.issue_number), packet)
        self.assertTrue(load_qualification(self.station, revision).frozen)

    def test_mixed_batch_atomic(self):
        original = register_day(self.station, load_day('day1.json'))
        line, batches, passes, strips = survey_rows(
            {'B': 'new', 'C': 'absent'}, [('b', 'B', 0, 3), ('c', 'C', 3, 6)]
        )
        with self.assertRaisesRegex(RegistrationError, 'absent'):
            register(self.station, line, [part for part in batches if part.batch_id == 'new'], passes, strips)
        self.reopen_station()
        self.assertEqual([part.strip_id for part in load_revision(self.station, original).strips],
                         ['a1', 'a2', 'a3', 'a4'])
        self.assertEqual(self.station.execute('SELECT batch_id FROM calibration_batches').fetchall(), [('K',)])
        self.assertEqual(self.station.execute('SELECT pass_id FROM survey_passes').fetchall(), [('A',)])
        self.assertEqual(self.station.execute('SELECT revision_id FROM revisions').fetchall(), [(original,)])
        self.assertEqual(self.station.execute('SELECT COUNT(*) FROM raw_strips').fetchone(), (4,))

    def test_registered_pass_keeps_batch_across_revisions(self):
        original = register_day(self.station, load_day('day1.json'))
        conflicting = survey_rows({'A': 'alternate'}, [('a', 'A', 0, 6)])
        with self.assertRaisesRegex(RegistrationError, 'already has batch'):
            register(self.station, *conflicting)
        self.assertEqual(load_revision(self.station, original).passes, (SurveyPass('A', 'K'),))
        self.assertEqual(self.station.execute('SELECT batch_id FROM calibration_batches').fetchall(), [('K',)])
