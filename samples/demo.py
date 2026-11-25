from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from intake.receive import receive
from intake.repository import init_intake
from issue.envelope import parse_v1
from issue.publish import publish
from issue.repository import init_issued_packets
from quality.process import init_quality, qualify
from quality.ranges import MeterInterval
from quality.rules import QualityRule
from review.eligibility import ReviewRequest
from review.repository import init_reports
from review.retrieve import retrieve
from review.sign import review
from source.calibrations import CalibrationBatch
from source.lines import SurveyLine
from source.passes import SurveyPass
from source.registration import init_source, register
from source.strips import RawStrip
from samples.continuation_demo import main as continuation_main


SAMPLE_DIR = Path(__file__).resolve().parent


def load_day(filename):
    return json.loads((SAMPLE_DIR / filename).read_text(encoding='utf-8'))


def register_day(db, data):
    return register(
        db, SurveyLine(data['line_id']),
        [CalibrationBatch(batch) for batch in data['calibrations']],
        [SurveyPass(*entry) for entry in data['passes']],
        [RawStrip(row['id'], row['pass'], MeterInterval(*row['window']), row['depth'], row['unit'])
         for row in data['strips']],
    )


def prepare_day(db, data):
    revision_id = register_day(db, data)
    qualification = qualify(db, revision_id, QualityRule(*data['rule_mm']))
    packet = publish(db, revision_id, MeterInterval(*data['issue_window']))
    return qualification, packet


def _scenario(case_id, input_data, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    assert actual == expected, (case_id, actual, expected)
    assert downstream_actual == downstream_expected, (case_id, downstream_actual, downstream_expected)
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id, 'input': input_data, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': paths, 'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


def main():
    day_one = load_day('day1.json')
    day_two = load_day('day2.json')
    with TemporaryDirectory(prefix='survey-handoff-') as directory:
        root = Path(directory)
        with closing(sqlite3.connect(root / 'center.sqlite')) as center:
            center.execute('PRAGMA foreign_keys = ON')
            init_intake(center)
            init_reports(center)
            with closing(sqlite3.connect(root / 'station.sqlite')) as station:
                station.execute('PRAGMA foreign_keys = ON')
                init_source(station)
                init_quality(station)
                init_issued_packets(station)
                old_quality, old_packet = prepare_day(station, day_one)
                old_receipt = receive(center, old_packet.original)
            coverage = parse_v1(old_packet.original).body['evidence']
            _scenario(
                'n01', day_one,
                {'a1': [1000, 'qualified'], 'a2': [1000, 'qualified'],
                 'a3': [None, 'missing'], 'a4': [1200, 'out_of_range']},
                {part.strip_id: [part.depth_mm, part.status.value] for part in old_quality.slices},
                [['a1', [0, 3]], ['a2', [3, 6]]],
                [[part['strip_id'], part['window']] for part in coverage],
                ['quality/units.py', 'quality/process.py', 'issue/evidence.py'],
                '1.000 m × 1000 与 100 cm × 10 均为 1000 mm，空值与 1200 mm 均不交付。',
            )
            old = review(center, ReviewRequest(old_receipt, MeterInterval(0, 6)))
            assert old.report is not None and old.initial_receipt is not None
            original_bundle = (old.report, old.initial_receipt)
            _scenario(
                'n03', {'receipt': old_receipt, 'window': [0, 6]},
                ['signed', 'A', [['a1', 0, 3], ['a2', 3, 6]]],
                [old.status, old.report.pass_id,
                 [[part.strip_id, part.start, part.end] for part in old.report.evidence]],
                True, retrieve(center, old.report.report_number) == original_bundle,
                ['review/eligibility.py', 'review/witness.py', 'review/sign.py', 'review/retrieve.py'],
                'A 的两个原段在 3 米端点接续，报告和首执应可同号取回。',
            )
            old_gap = review(center, ReviewRequest(old_receipt, MeterInterval(5, 7)))
            _scenario(
                'n05', {'receipt': old_receipt, 'window': [5, 7]}, 'resurvey', old_gap.status,
                [False, False], [old_gap.report is not None, old_gap.initial_receipt is not None],
                ['issue/evidence.py', 'review/witness.py', 'review/sign.py'],
                '缺测原段 a3 留下 [6,7) 的正长度空档。',
            )
            with closing(sqlite3.connect(root / 'station.sqlite')) as station:
                station.execute('PRAGMA foreign_keys = ON')
                _, new_packet = prepare_day(station, day_two)
                new_receipt = receive(center, new_packet.original)

        with closing(sqlite3.connect(root / 'center.sqlite')) as center:
            center.execute('PRAGMA foreign_keys = ON')
            target = MeterInterval(5, 7)
            old_again = review(center, ReviewRequest(old_receipt, target))
            fresh = review(center, ReviewRequest(new_receipt, target))
            assert fresh.report is not None
            _scenario(
                'n08', {'corrected_strip': day_two['strips'][2], 'window': [5, 7],
                        'old_receipt': old_receipt, 'new_receipt': new_receipt},
                ['resurvey', 'signed', ['a2', 'a3']],
                [old_again.status, fresh.status, [part.strip_id for part in fresh.report.evidence]],
                [True, True],
                [fresh.report.receipt_id == new_receipt,
                 retrieve(center, old.report.report_number) == original_bundle],
                ['source/registration.py', 'issue/publish.py', 'intake/repository.py', 'review/retrieve.py'],
                '更正只让新件补齐 [6,7)，旧实收结果与旧报告存档保持。',
            )

    continuation_main()


if __name__ == '__main__':
    main()
