import hashlib
import json

from quality.ranges import MeterInterval
from source.calibrations import CalibrationBatch
from source.lines import SurveyLine
from source.passes import SurveyPass
from source.strips import RawStrip


def survey_rows(pass_batches, strips):
    return (
        SurveyLine('Q'),
        [CalibrationBatch(batch) for batch in sorted(set(pass_batches.values()))],
        [SurveyPass(pass_id, batch) for pass_id, batch in pass_batches.items()],
        [RawStrip(strip_id, pass_id, MeterInterval(start, end), '1000', 'mm')
         for strip_id, pass_id, start, end in strips],
    )


def half_pass_rows(right_pass='B'):
    return survey_rows(
        {'A': 'K_L', 'B': 'K_L', 'C': 'K_K'},
        [('a1', 'A', 0, 3), ('a2', right_pass, 3, 6), ('a3', 'C', 0, 6)],
    )


def wrap_independent_body(body):
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    return json.dumps({
        'version': 1,
        'issue_number': body['issue_number'],
        'body': body,
        'checksum': hashlib.sha256(canonical.encode('ascii')).hexdigest(),
    }, ensure_ascii=True, indent=2).encode('utf-8')


def independent_packet(issue_number=501):
    body = {
        'issue_number': issue_number,
        'line_id': 'Q',
        'revision_id': 43,
        'window': [0, 6],
        'evidence': [
            {'pass_id': 'A', 'batch_id': 'K_L', 'strip_id': 'a1',
             'window': [0, 3], 'source_window': [0, 3]},
            {'pass_id': 'B', 'batch_id': 'K_L', 'strip_id': 'a2',
             'window': [3, 6], 'source_window': [3, 6]},
            {'pass_id': 'C', 'batch_id': 'K_K', 'strip_id': 'a3',
             'window': [0, 6], 'source_window': [0, 6]},
        ],
    }
    return wrap_independent_body(body)
