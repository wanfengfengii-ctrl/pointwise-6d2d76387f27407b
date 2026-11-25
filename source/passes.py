from dataclasses import dataclass
import sqlite3

from source.calibrations import require_batch


@dataclass(frozen=True)
class SurveyPass:
    pass_id: str
    batch_id: str


def init_passes(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS survey_passes (
            pass_id TEXT PRIMARY KEY NOT NULL,
            batch_id TEXT NOT NULL REFERENCES calibration_batches(batch_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS revision_passes (
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            pass_id TEXT NOT NULL REFERENCES survey_passes(pass_id),
            PRIMARY KEY (revision_id, pass_id)
        )
    ''')


def validate_pass_bindings(
    db: sqlite3.Connection, passes: tuple[SurveyPass, ...], new_batches: set[str]
) -> None:
    for survey_pass in passes:
        if survey_pass.batch_id not in new_batches:
            require_batch(db, survey_pass.batch_id)
        recorded = db.execute(
            'SELECT batch_id FROM survey_passes WHERE pass_id = ?', (survey_pass.pass_id,)
        ).fetchone()
        if recorded is not None and recorded[0] != survey_pass.batch_id:
            raise ValueError(f'pass {survey_pass.pass_id!r} already has batch {recorded[0]!r}')


def store_revision_passes(
    db: sqlite3.Connection, revision_id: int, passes: tuple[SurveyPass, ...]
) -> None:
    db.executemany('''
        INSERT INTO survey_passes (pass_id, batch_id) VALUES (?, ?)
        ON CONFLICT (pass_id) DO NOTHING
    ''', ((survey_pass.pass_id, survey_pass.batch_id) for survey_pass in passes))
    db.executemany('''
        INSERT INTO revision_passes (revision_id, pass_id) VALUES (?, ?)
    ''', ((revision_id, survey_pass.pass_id) for survey_pass in passes))


def load_revision_passes(db: sqlite3.Connection, revision_id: int) -> tuple[SurveyPass, ...]:
    rows = db.execute('''
        SELECT p.pass_id, p.batch_id
        FROM revision_passes AS r JOIN survey_passes AS p ON p.pass_id = r.pass_id
        WHERE r.revision_id = ? ORDER BY p.pass_id
    ''', (revision_id,))
    return tuple(SurveyPass(*row) for row in rows)
