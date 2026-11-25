from dataclasses import dataclass
import json
import sqlite3


@dataclass(frozen=True)
class ReportEvidence:
    strip_id: str
    start: int
    end: int
    source_start: int
    source_end: int


@dataclass(frozen=True)
class SignedReport:
    report_number: int
    receipt_id: int
    issue_number: int
    packet_checksum: str
    line_id: str
    revision_id: int
    start: int
    end: int
    suspended_batch: str | None
    pass_id: str
    batch_id: str
    evidence: tuple[ReportEvidence, ...]


@dataclass(frozen=True)
class InitialReceipt:
    receipt_number: str
    report_number: int


def init_reports(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    with db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_number INTEGER PRIMARY KEY,
                receipt_id INTEGER NOT NULL REFERENCES accepted_packets(receipt_id),
                issue_number INTEGER NOT NULL,
                packet_checksum TEXT NOT NULL,
                line_id TEXT NOT NULL,
                revision_id INTEGER NOT NULL,
                start_m TEXT NOT NULL,
                end_m TEXT NOT NULL,
                suspended_batch TEXT,
                pass_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                evidence_json TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS initial_receipts (
                receipt_number TEXT PRIMARY KEY NOT NULL,
                report_number INTEGER NOT NULL UNIQUE REFERENCES reports(report_number)
            )
        ''')


def allocate_report_number(db: sqlite3.Connection) -> int:
    return db.execute('SELECT COALESCE(MAX(report_number), 0) FROM reports').fetchone()[0] + 1


def insert_report(db: sqlite3.Connection, report: SignedReport) -> None:
    evidence = [
        [part.strip_id, part.start, part.end, part.source_start, part.source_end]
        for part in report.evidence
    ]
    db.execute('''
        INSERT INTO reports (report_number, receipt_id, issue_number, packet_checksum,
                             line_id, revision_id, start_m, end_m, suspended_batch,
                             pass_id, batch_id, evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        report.report_number, report.receipt_id, report.issue_number, report.packet_checksum,
        report.line_id, report.revision_id, str(report.start), str(report.end),
        report.suspended_batch, report.pass_id, report.batch_id, json.dumps(evidence),
    ))


def insert_initial_receipt(db: sqlite3.Connection, receipt: InitialReceipt) -> None:
    db.execute('''
        INSERT INTO initial_receipts (receipt_number, report_number) VALUES (?, ?)
    ''', (receipt.receipt_number, receipt.report_number))


def load_report_bundle(
    db: sqlite3.Connection, report_number: int,
) -> tuple[SignedReport, InitialReceipt] | None:
    if type(report_number) is not int or not 0 < report_number < 2**63:
        return None
    row = db.execute('''
        SELECT r.receipt_id, r.issue_number, r.packet_checksum, r.line_id, r.revision_id,
               r.start_m, r.end_m, r.suspended_batch, r.pass_id, r.batch_id,
               r.evidence_json, f.receipt_number
        FROM reports AS r JOIN initial_receipts AS f ON f.report_number = r.report_number
        WHERE r.report_number = ?
    ''', (report_number,)).fetchone()
    if row is None:
        return None
    (receipt_id, issue_number, checksum, line_id, revision_id, start, end, suspended_batch,
     pass_id, batch_id, evidence_json, first_number) = row
    report = SignedReport(
        report_number, receipt_id, issue_number, checksum, line_id, revision_id, int(start), int(end),
        suspended_batch, pass_id, batch_id,
        tuple(ReportEvidence(*part) for part in json.loads(evidence_json)),
    )
    return report, InitialReceipt(first_number, report_number)
