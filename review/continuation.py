from collections import defaultdict
from dataclasses import dataclass
import sqlite3

from intake.repository import get_accepted
from issue.continuation import is_continuation_body
from issue.envelope import parse_v1
from quality.ranges import MeterInterval, intersect, validate_window
from review.eligibility import (
    ReviewRequestError, _parse_evidence, _parse_window, _require_text,
)
from review.repository import SignedReport, load_report_bundle
from review.witness import CoverageWitness, EvidenceSlice, _cover_one_pass


@dataclass(frozen=True)
class EqualityLink:
    old_strip_id: str
    new: EvidenceSlice
    window: MeterInterval


@dataclass(frozen=True)
class ContinuationDecision:
    old_report: SignedReport
    receipt_id: int
    issue_number: int
    packet_checksum: str
    line_id: str
    revision_id: int
    witness: CoverageWitness | None


def _parse_binding(body: dict) -> tuple[int, str]:
    if not is_continuation_body(body):
        raise ReviewRequestError('receipt is not a continuation correction packet')

    nested = body.get('continuation_binding')
    binding = nested if isinstance(nested, dict) else body
    old_issue = binding.get('old_issue_number', body.get('old_issue_number'))
    checksum = binding.get('old_body_checksum', body.get('old_body_checksum'))

    if type(old_issue) is not int or not 0 < old_issue < 2**63:
        raise ReviewRequestError('continuation binding has an invalid old issue number')
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise ReviewRequestError('continuation binding has an invalid old body checksum')
    try:
        int(checksum, 16)
    except ValueError as error:
        raise ReviewRequestError('continuation binding has an invalid old body checksum') from error
    return old_issue, checksum


def _parse_links(body: dict, evidence: tuple[EvidenceSlice, ...]) -> tuple[EqualityLink, ...]:
    raw_links = body.get('equality_basis', [])
    if raw_links is None:
        raw_links = []
    if not isinstance(raw_links, list):
        raise ReviewRequestError('continuation equality basis must be a list')

    evidence_by_strip = {part.strip_id: part for part in evidence}
    links = []
    for raw in raw_links:
        if not isinstance(raw, dict):
            raise ReviewRequestError('equality basis item must be an object')
        old_strip_id = _require_text(raw['old_strip_id'], 'old_strip_id')
        new_strip_id = _require_text(raw['new_strip_id'], 'new_strip_id')
        window = _parse_window(raw['window'])
        try:
            new_part = evidence_by_strip[new_strip_id]
        except KeyError as error:
            raise ReviewRequestError(f'equality basis refers to unknown strip {new_strip_id!r}') from error

        if intersect(window, new_part.window) != window:
            raise ReviewRequestError(f'equality basis for {new_strip_id!r} leaves its issued range')
        if 'pass_id' in raw and _require_text(raw['pass_id'], 'pass_id') != new_part.pass_id:
            raise ReviewRequestError(f'equality basis pass mismatch for {new_strip_id!r}')
        if 'batch_id' in raw and _require_text(raw['batch_id'], 'batch_id') != new_part.batch_id:
            raise ReviewRequestError(f'equality basis batch mismatch for {new_strip_id!r}')

        links.append(EqualityLink(old_strip_id, new_part, window))
    return tuple(links)


def _merge_intervals(windows: list[MeterInterval]) -> tuple[MeterInterval, ...]:
    ordered = sorted(windows, key=lambda item: (item.start, item.end))
    merged: list[MeterInterval] = []
    for window in ordered:
        if not merged or window.start > merged[-1].end:
            merged.append(MeterInterval(window.start, window.end))
        elif window.end > merged[-1].end:
            merged[-1] = MeterInterval(merged[-1].start, window.end)
    return tuple(merged)


def _continuation_witness(
    old_report: SignedReport, links: tuple[EqualityLink, ...],
) -> CoverageWitness | None:
    requested = MeterInterval(old_report.start, old_report.end)
    validate_window(requested)

    supported: dict[str, list[MeterInterval]] = defaultdict(list)
    new_parts: dict[str, EvidenceSlice] = {}

    for old_part in old_report.evidence:
        old_interval = MeterInterval(old_part.start, old_part.end)
        validate_window(old_interval)
        for link in links:
            if link.old_strip_id != old_part.strip_id:
                continue
            covered = intersect(link.window, old_interval)
            if covered is not None:
                supported[link.new.strip_id].append(covered)
                new_parts[link.new.strip_id] = link.new

    candidates = []
    for strip_id, intervals in supported.items():
        new_part = new_parts[strip_id]
        if (new_part.pass_id != old_report.pass_id
                or new_part.batch_id != old_report.batch_id):
            continue
        for window in _merge_intervals(intervals):
            candidates.append(EvidenceSlice(
                new_part.pass_id, new_part.batch_id, strip_id, window, new_part.source_window,
            ))

    pieces = _cover_one_pass(candidates, requested)
    if pieces is None or not pieces:
        return None
    batch_id = pieces[0].batch_id
    return CoverageWitness(old_report.pass_id, batch_id, pieces)


def decide_continuation(
    db: sqlite3.Connection, old_report_reference: object, receipt_id: int,
) -> ContinuationDecision:
    if isinstance(old_report_reference, tuple) and old_report_reference:
        old_report_reference = old_report_reference[0]
    old_report_number = getattr(old_report_reference, 'report_number', old_report_reference)
    receipt_number = getattr(receipt_id, 'receipt_id', receipt_id)
    old_bundle = load_report_bundle(db, old_report_number)
    if old_bundle is None:
        raise ReviewRequestError(f'unknown old report {old_report_reference!r}')
    old_report = old_bundle[0]
    if old_report.old_report_number is not None:
        raise ReviewRequestError(
            f'report {old_report.report_number} is already a continuation report'
        )

    try:
        accepted = get_accepted(db, receipt_number)
        envelope = parse_v1(accepted.original)
        if envelope.issue_number != accepted.issue_number or envelope.checksum != accepted.checksum:
            raise ValueError('stored receipt does not match its original packet')
        body = envelope.body
        old_issue_number, old_checksum = _parse_binding(body)
        line_id = _require_text(body['line_id'], 'line_id')
        revision_id = body['revision_id']
        if type(revision_id) is not int or not 0 < revision_id < 2**63:
            raise ValueError('invalid revision number')
        issue_window = _parse_window(body['window'])
        evidence = _parse_evidence(body['evidence'], issue_window)
        links = _parse_links(body, evidence)

        old_accepted = get_accepted(db, old_report.receipt_id)
        old_envelope = parse_v1(old_accepted.original)
        if (old_envelope.issue_number != old_accepted.issue_number
                or old_envelope.checksum != old_accepted.checksum):
            raise ValueError('stored old receipt does not match its original packet')
    except ReviewRequestError:
        raise
    except (KeyError, TypeError, ValueError, sqlite3.Error) as error:
        raise ReviewRequestError(str(error)) from error

    if old_envelope.issue_number != old_report.issue_number:
        raise ReviewRequestError('old report issue does not match its archived receipt')
    if old_envelope.checksum != old_report.packet_checksum:
        raise ReviewRequestError('old report checksum does not match its archived receipt')
    if old_envelope.body.get('line_id') != old_report.line_id:
        raise ReviewRequestError('old report line does not match its archived packet')
    if (old_issue_number != old_report.issue_number
            or old_checksum != old_report.packet_checksum
            or line_id != old_report.line_id):
        raise ReviewRequestError('continuation binding does not match the specified old report')

    witness = _continuation_witness(old_report, links)
    return ContinuationDecision(
        old_report, accepted.receipt_id, accepted.issue_number, accepted.checksum,
        line_id, revision_id, witness,
    )
