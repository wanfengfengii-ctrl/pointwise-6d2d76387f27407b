from dataclasses import dataclass
import sqlite3

from intake.repository import get_accepted
from issue.envelope import parse_v1
from quality.ranges import MeterInterval, intersect, validate_window
from review.witness import CoverageWitness, EvidenceSlice, find_witness


@dataclass(frozen=True)
class ReviewRequest:
    receipt_id: int
    window: MeterInterval
    suspended_batch: str | None = None


class ReviewRequestError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewDecision:
    request: ReviewRequest
    issue_number: int
    packet_checksum: str
    line_id: str
    revision_id: int
    witness: CoverageWitness | None


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    return value


def validate_request(request: ReviewRequest) -> None:
    try:
        if not isinstance(request, ReviewRequest):
            raise ValueError('expected a ReviewRequest')
        if type(request.receipt_id) is not int or not 0 < request.receipt_id < 2**63:
            raise ValueError('invalid receipt number')
        validate_window(request.window)
        if request.suspended_batch is not None:
            _require_text(request.suspended_batch, 'suspended batch')
    except ValueError as error:
        raise ReviewRequestError(str(error)) from error


def _parse_window(data: object) -> MeterInterval:
    if not isinstance(data, list) or len(data) != 2:
        raise ValueError('packet window must contain two endpoints')
    window = MeterInterval(*data)
    validate_window(window)
    return window


def _parse_evidence(data: object, issue_window: MeterInterval) -> tuple[EvidenceSlice, ...]:
    if not isinstance(data, list):
        raise ValueError('packet evidence must be a list')
    result = []
    batches = {}
    strips = set()
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError('packet evidence item must be an object')
        pass_id = _require_text(entry['pass_id'], 'pass_id')
        batch_id = _require_text(entry['batch_id'], 'batch_id')
        strip_id = _require_text(entry['strip_id'], 'strip_id')
        window = _parse_window(entry['window'])
        source = _parse_window(entry['source_window'])
        if intersect(source, issue_window) != window:
            raise ValueError(f'evidence for {strip_id!r} does not match the issued cut')
        if batches.setdefault(pass_id, batch_id) != batch_id:
            raise ValueError(f'inconsistent calibration batch for pass {pass_id!r}')
        if strip_id in strips:
            raise ValueError(f'duplicate evidence for strip {strip_id!r}')
        strips.add(strip_id)
        result.append(EvidenceSlice(pass_id, batch_id, strip_id, window, source))
    return tuple(result)


def decide_review(db: sqlite3.Connection, request: ReviewRequest) -> ReviewDecision:
    validate_request(request)
    try:
        accepted = get_accepted(db, request.receipt_id)
        envelope = parse_v1(accepted.original)
        if envelope.issue_number != accepted.issue_number or envelope.checksum != accepted.checksum:
            raise ValueError('stored receipt does not match its original packet')
        body = envelope.body
        line_id = _require_text(body['line_id'], 'line_id')
        revision_id = body['revision_id']
        if type(revision_id) is not int or not 0 < revision_id < 2**63:
            raise ValueError('invalid revision number')
        issue_window = _parse_window(body['window'])
        evidence = _parse_evidence(body['evidence'], issue_window)
    except (KeyError, ValueError, sqlite3.Error) as error:
        raise ReviewRequestError(str(error)) from error
    witness = None
    if intersect(request.window, issue_window) == request.window:
        witness = find_witness(evidence, request.window, request.suspended_batch)
    return ReviewDecision(request, accepted.issue_number, accepted.checksum, line_id, revision_id, witness)
