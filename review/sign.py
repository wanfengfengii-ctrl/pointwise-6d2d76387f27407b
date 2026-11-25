from dataclasses import dataclass
import sqlite3
from typing import Literal

from review.eligibility import ReviewDecision, ReviewRequest, decide_review
from review.repository import (
    InitialReceipt, ReportEvidence, SignedReport, allocate_report_number,
    insert_initial_receipt, insert_report,
)


class SigningError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReviewResult:
    status: Literal['signed', 'resurvey']
    report: SignedReport | None = None
    initial_receipt: InitialReceipt | None = None


def sign_report(db: sqlite3.Connection, decision: ReviewDecision) -> ReviewResult:
    witness = decision.witness
    if witness is None:
        raise SigningError('no coverage witness to sign')
    request = decision.request
    evidence = tuple(
        ReportEvidence(part.strip_id, part.window.start, part.window.end,
                       part.source_window.start, part.source_window.end)
        for part in witness.pieces
    )
    try:
        db.execute('BEGIN IMMEDIATE')
        with db:
            report_number = allocate_report_number(db)
            report = SignedReport(
                report_number, request.receipt_id, decision.issue_number, decision.packet_checksum,
                decision.line_id, decision.revision_id, request.window.start, request.window.end,
                request.suspended_batch, witness.pass_id, witness.batch_id, evidence,
            )
            first_receipt = InitialReceipt(f'FIRST-{report_number}', report_number)
            insert_report(db, report)
            insert_initial_receipt(db, first_receipt)
    except (sqlite3.Error, ValueError, OverflowError) as error:
        raise SigningError(str(error)) from error
    return ReviewResult('signed', report, first_receipt)


def review(db: sqlite3.Connection, request: ReviewRequest) -> ReviewResult:
    decision = decide_review(db, request)
    if decision.witness is None:
        return ReviewResult('resurvey')
    return sign_report(db, decision)
