import sqlite3

from issue.continuation import CONTINUATION_TYPE, build_equality_basis, is_continuation_body
from issue.envelope import body_checksum, encode_v1, parse_v1
from issue.evidence import project_evidence
from issue.repository import IssuedPacket, allocate_issue_number, load_issued_packet, store_issued_packet
from issue.selection import select_issue
from quality.process import freeze_qualification, load_qualification
from quality.ranges import MeterInterval
from source.revisions import freeze_revision


class PublishError(ValueError):
    pass


def publish(db: sqlite3.Connection, revision_id: int, window: MeterInterval) -> IssuedPacket:
    try:
        db.execute('BEGIN IMMEDIATE')
        with db:
            selection = select_issue(db, revision_id, window)
            if selection.revision.state == 'working':
                freeze_revision(db, revision_id)
                freeze_qualification(db, revision_id)
            issue_number = allocate_issue_number(db)
            body = {
                'issue_number': issue_number,
                'line_id': selection.revision.line.line_id,
                'revision_id': revision_id,
                'window': [selection.window.start, selection.window.end],
                'evidence': project_evidence(selection),
            }
            packet = IssuedPacket(issue_number, revision_id, encode_v1(issue_number, body))
            store_issued_packet(db, packet)
    except (ValueError, KeyError, sqlite3.Error) as error:
        raise PublishError(str(error)) from error
    return packet


def publish_continuation(
    db: sqlite3.Connection, old_issue: int, new_revision: int, window: MeterInterval,
) -> IssuedPacket:
    old_issue_number = getattr(old_issue, 'issue_number', old_issue)
    new_revision_id = getattr(new_revision, 'revision_id', new_revision)
    try:
        db.execute('BEGIN IMMEDIATE')
        with db:
            old_packet = load_issued_packet(db, old_issue_number)
            old_envelope = parse_v1(old_packet.original)
            old_body = old_envelope.body
            if is_continuation_body(old_body):
                raise ValueError(f'old issue {old_issue_number} is not an ordinary V1 issue')
            if old_envelope.issue_number != old_packet.issue_number:
                raise ValueError('stored old issue does not match its envelope')

            old_revision_id = old_body['revision_id']
            old_line_id = old_body['line_id']
            if type(old_revision_id) is not int or not 0 < old_revision_id < 2**63:
                raise ValueError('old issue has an invalid revision number')
            if not isinstance(old_line_id, str) or not old_line_id:
                raise ValueError('old issue has an invalid line identifier')
            old_qualification = load_qualification(db, old_revision_id)

            selection = select_issue(db, new_revision_id, window)
            if selection.revision.state == 'working':
                freeze_revision(db, new_revision_id)
                freeze_qualification(db, new_revision_id)
            if selection.revision.line.line_id != old_line_id:
                raise ValueError('continuation revision is for a different survey line')
            if (type(new_revision_id) is not int
                    or new_revision_id <= old_revision_id):
                raise ValueError('continuation revision must be newer than the bound old issue')

            issue_number = allocate_issue_number(db)
            evidence = project_evidence(selection)
            equality_basis = build_equality_basis(
                old_body, old_qualification, selection.qualification, evidence,
            )
            old_checksum = body_checksum(old_body)
            body = {
                'issue_number': issue_number,
                'packet_type': CONTINUATION_TYPE,
                'kind': CONTINUATION_TYPE,
                'line_id': selection.revision.line.line_id,
                'revision_id': new_revision_id,
                'window': [selection.window.start, selection.window.end],
                'old_issue_number': old_issue_number,
                'old_body_checksum': old_checksum,
                'continuation_binding': {
                    'old_issue_number': old_issue_number,
                    'old_body_checksum': old_checksum,
                },
                'evidence': evidence,
                'equality_basis': equality_basis,
            }
            packet = IssuedPacket(
                issue_number, new_revision_id, encode_v1(issue_number, body),
            )
            store_issued_packet(db, packet)
    except (ValueError, KeyError, sqlite3.Error) as error:
        raise PublishError(str(error)) from error
    return packet
