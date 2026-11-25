import sqlite3

from issue.envelope import encode_v1
from issue.evidence import project_evidence
from issue.repository import IssuedPacket, allocate_issue_number, store_issued_packet
from issue.selection import select_issue
from quality.process import freeze_qualification
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
