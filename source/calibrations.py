from collections.abc import Iterable
from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class CalibrationBatch:
    batch_id: str


def init_calibrations(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS calibration_batches (
            batch_id TEXT PRIMARY KEY NOT NULL
        )
    ''')


def store_calibrations(db: sqlite3.Connection, batches: Iterable[CalibrationBatch]) -> None:
    db.executemany('''
        INSERT INTO calibration_batches (batch_id) VALUES (?)
        ON CONFLICT (batch_id) DO NOTHING
    ''', ((batch.batch_id,) for batch in batches))


def require_batch(db: sqlite3.Connection, batch_id: str) -> CalibrationBatch:
    row = db.execute(
        'SELECT batch_id FROM calibration_batches WHERE batch_id = ?', (batch_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f'unknown calibration batch {batch_id!r}')
    return CalibrationBatch(row[0])
