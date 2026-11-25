from dataclasses import dataclass
import sqlite3

from quality.ranges import MeterInterval


@dataclass(frozen=True)
class RawStrip:
    strip_id: str
    pass_id: str
    window: MeterInterval
    depth: str | None
    unit: str


def init_strips(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS raw_strips (
            revision_id INTEGER NOT NULL,
            strip_id TEXT NOT NULL,
            pass_id TEXT NOT NULL,
            start_m TEXT NOT NULL,
            end_m TEXT NOT NULL,
            raw_depth TEXT,
            unit TEXT NOT NULL,
            PRIMARY KEY (revision_id, strip_id),
            FOREIGN KEY (revision_id, pass_id) REFERENCES revision_passes(revision_id, pass_id)
        )
    ''')


def store_revision_strips(
    db: sqlite3.Connection, revision_id: int, strips: tuple[RawStrip, ...]
) -> None:
    db.executemany('''
        INSERT INTO raw_strips
            (revision_id, strip_id, pass_id, start_m, end_m, raw_depth, unit)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        (revision_id, strip.strip_id, strip.pass_id, str(strip.window.start),
         str(strip.window.end), strip.depth, strip.unit)
        for strip in strips
    ))


def load_revision_strips(db: sqlite3.Connection, revision_id: int) -> tuple[RawStrip, ...]:
    rows = db.execute('''
        SELECT strip_id, pass_id, start_m, end_m, raw_depth, unit
        FROM raw_strips WHERE revision_id = ? ORDER BY strip_id
    ''', (revision_id,))
    return tuple(
        RawStrip(strip_id, pass_id, MeterInterval(int(start), int(end)), depth, unit)
        for strip_id, pass_id, start, end, depth, unit in rows
    )
