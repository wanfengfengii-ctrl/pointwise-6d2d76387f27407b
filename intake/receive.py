import sqlite3

from intake.dedup import resolve_reception
from intake.repository import find_by_issue_number, insert_accepted
from intake.verify import verify_packet


def receive(db: sqlite3.Connection, original: bytes) -> int:
    packet = verify_packet(original)
    db.execute('BEGIN IMMEDIATE')
    with db:
        existing = find_by_issue_number(db, packet.issue_number)
        receipt_id = resolve_reception(packet, existing)
        if receipt_id is None:
            receipt_id = insert_accepted(db, packet)
    return receipt_id
