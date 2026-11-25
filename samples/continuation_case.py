"""Measured V1 comparisons and input rows for the continuation exercise."""
from contextlib import closing
import json
import sqlite3

from intake.receive import receive
from intake.repository import init_intake
from issue.envelope import parse_v1
from issue.publish import publish
from issue.repository import init_issued_packets
from quality.process import init_quality, load_qualification, qualify
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


WINDOW = MeterInterval(0, 6)
OLD = (("a1", 0, 6, "1.000", "m"),)
SAME = (("b1", 0, 3, "100", "cm"), ("b2", 3, 6, "1000", "mm"))
CHANGED = (("b1", 0, 3, "100", "cm"), ("b2", 3, 6, "1001", "mm"))
OVERLAP_OLD = (("a1", 0, 4, "1000", "mm"), ("a2", 2, 6, "1001", "mm"))
OVERLAP_NEW = (("b1", 0, 6, "1000", "mm"),)


def prepare(db, rows):
    strips = [RawStrip(name, "A", MeterInterval(start, end), depth, unit)
              for name, start, end, depth, unit in rows]
    revision = register(db, SurveyLine("Q"), [CalibrationBatch("K")],
                        [SurveyPass("A", "K")], strips)
    qualify(db, revision, QualityRule(900, 1100))
    return revision


def contributions(report):
    return [[part.strip_id, part.start, part.end] for part in report.evidence]


def main():
    with closing(sqlite3.connect(":memory:")) as center:
        center.execute("PRAGMA foreign_keys = ON")
        init_intake(center)
        init_reports(center)
        with closing(sqlite3.connect(":memory:")) as station:
            station.execute("PRAGMA foreign_keys = ON")
            init_source(station)
            init_quality(station)
            init_issued_packets(station)
            revisions = [prepare(station, rows)
                         for rows in (OLD, SAME, CHANGED, OVERLAP_OLD, OVERLAP_NEW)]
            packets = [publish(station, revision, WINDOW) for revision in revisions]
            alternate = publish(station, revisions[0], WINDOW)
            depths = [[part.depth_mm for part in load_qualification(station, r).slices]
                      for r in revisions]

        old, same, changed, overlap, overlap_new = [receive(center, p.original) for p in packets]
        alternate_receipt = receive(center, alternate.original)
        assert alternate_receipt != old
        same_body = parse_v1(packets[1].original).body
        changed_body = parse_v1(packets[2].original).body
        assert depths[:3] == [[1000], [1000, 1000], [1000, 1001]], depths
        assert same_body["evidence"] == changed_body["evidence"]
        requests = ((old, WINDOW), (same, WINDOW), (changed, WINDOW),
                    (overlap, MeterInterval(0, 4)), (overlap, MeterInterval(2, 6)),
                    (overlap_new, WINDOW))
        results = [review(center, ReviewRequest(receipt, window)) for receipt, window in requests]
        assert all(result.status == "signed" for result in results), results
        witnesses = [contributions(result.report) for result in results]
        assert witnesses == [
            [["a1", 0, 6]], [["b1", 0, 3], ["b2", 3, 6]], [["b1", 0, 3], ["b2", 3, 6]],
            [["a1", 0, 4]], [["a2", 2, 6]], [["b1", 0, 6]],
        ], witnesses
        first = results[0]
        assert retrieve(center, first.report.report_number) == (first.report, first.initial_receipt)
        print(json.dumps({"qualified_mm": depths, "ordinary_v1_status": [r.status for r in results],
                          "ordinary_v1_witnesses": witnesses, "same_v1_evidence": True},
                         sort_keys=True))


if __name__ == "__main__":
    main()
