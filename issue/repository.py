from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class IssuedPacket:
    issue_number: int
    revision_id: int
    original: bytes


def init_issued_packets(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS issued_packets (
            issue_number INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            original BLOB NOT NULL
        )
    ''')


def allocate_issue_number(db: sqlite3.Connection) -> int:
    return db.execute('SELECT COALESCE(MAX(issue_number), 0) FROM issued_packets').fetchone()[0] + 1


def store_issued_packet(db: sqlite3.Connection, packet: IssuedPacket) -> None:
    db.execute('''
        INSERT INTO issued_packets (issue_number, revision_id, original) VALUES (?, ?, ?)
    ''', (packet.issue_number, packet.revision_id, packet.original))


def load_issued_packet(db: sqlite3.Connection, issue_number: int) -> IssuedPacket:
    if type(issue_number) is not int or not 0 < issue_number < 2**63:
        raise KeyError(f'unknown issue number {issue_number!r}')
    row = db.execute('''
        SELECT issue_number, revision_id, original FROM issued_packets WHERE issue_number = ?
    ''', (issue_number,)).fetchone()
    if row is None:
        raise KeyError(f'unknown issue number {issue_number}')
    return IssuedPacket(*row)
