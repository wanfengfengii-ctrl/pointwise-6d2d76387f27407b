import sqlite3

from review.repository import InitialReceipt, SignedReport, load_report_bundle


class ReportMissing(KeyError):
    pass


def retrieve(db: sqlite3.Connection, report_number: int) -> tuple[SignedReport, InitialReceipt]:
    bundle = load_report_bundle(db, report_number)
    if bundle is None:
        raise ReportMissing(f'unknown report {report_number!r}')
    return bundle
