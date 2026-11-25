from dataclasses import dataclass
import sqlite3

from source.lines import SurveyLine, load_line
from source.passes import SurveyPass, load_revision_passes
from source.strips import RawStrip, load_revision_strips


@dataclass(frozen=True)
class RevisionSnapshot:
    revision_id: int
    line: SurveyLine
    state: str
    passes: tuple[SurveyPass, ...]
    strips: tuple[RawStrip, ...]


def init_revisions(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            revision_id INTEGER PRIMARY KEY,
            line_id TEXT NOT NULL REFERENCES survey_lines(line_id),
            state TEXT NOT NULL CHECK (state IN ('working', 'frozen'))
        )
    ''')


def create_working_revision(db: sqlite3.Connection, line: SurveyLine) -> int:
    cursor = db.execute(
        "INSERT INTO revisions (line_id, state) VALUES (?, 'working')", (line.line_id,)
    )
    return cursor.lastrowid


def load_revision(db: sqlite3.Connection, revision_id: int) -> RevisionSnapshot:
    if type(revision_id) is not int or not 0 < revision_id < 2**63:
        raise KeyError(f'unknown revision {revision_id!r}')
    row = db.execute(
        'SELECT line_id, state FROM revisions WHERE revision_id = ?', (revision_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown revision {revision_id}')
    return RevisionSnapshot(
        revision_id, load_line(db, row[0]), row[1],
        load_revision_passes(db, revision_id), load_revision_strips(db, revision_id),
    )


def freeze_revision(db: sqlite3.Connection, revision_id: int) -> None:
    cursor = db.execute('''
        UPDATE revisions SET state = 'frozen' WHERE revision_id = ? AND state = 'working'
    ''', (revision_id,))
    if cursor.rowcount != 1:
        raise ValueError(f'revision {revision_id} is not working')
