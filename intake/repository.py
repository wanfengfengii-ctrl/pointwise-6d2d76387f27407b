from dataclasses import dataclass
import sqlite3

from intake.verify import VerifiedPacket


@dataclass(frozen=True)
class AcceptedPacket:
    receipt_id: int
    issue_number: int
    checksum: str
    original: bytes


def init_intake(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS accepted_packets (
            receipt_id INTEGER PRIMARY KEY,
            issue_number INTEGER NOT NULL UNIQUE,
            checksum TEXT NOT NULL,
            original BLOB NOT NULL
        )
    ''')


def find_by_issue_number(db: sqlite3.Connection, issue_number: int) -> AcceptedPacket | None:
    row = db.execute('''
        SELECT receipt_id, issue_number, checksum, original
        FROM accepted_packets WHERE issue_number = ?
    ''', (issue_number,)).fetchone()
    return None if row is None else AcceptedPacket(*row)


def insert_accepted(db: sqlite3.Connection, packet: VerifiedPacket) -> int:
    cursor = db.execute('''
        INSERT INTO accepted_packets (issue_number, checksum, original) VALUES (?, ?, ?)
    ''', (packet.issue_number, packet.checksum, packet.original))
    return cursor.lastrowid


def get_accepted(db: sqlite3.Connection, receipt_id: int) -> AcceptedPacket:
    if type(receipt_id) is not int or not 0 < receipt_id < 2**63:
        raise KeyError(f'unknown receipt {receipt_id!r}')
    row = db.execute('''
        SELECT receipt_id, issue_number, checksum, original
        FROM accepted_packets WHERE receipt_id = ?
    ''', (receipt_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown receipt {receipt_id}')
    return AcceptedPacket(*row)
