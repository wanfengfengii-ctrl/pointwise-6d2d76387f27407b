from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class SurveyLine:
    line_id: str


def init_lines(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS survey_lines (
            line_id TEXT PRIMARY KEY NOT NULL
        )
    ''')


def store_line(db: sqlite3.Connection, line: SurveyLine) -> None:
    db.execute('''
        INSERT INTO survey_lines (line_id) VALUES (?)
        ON CONFLICT (line_id) DO NOTHING
    ''', (line.line_id,))


def load_line(db: sqlite3.Connection, line_id: str) -> SurveyLine:
    row = db.execute(
        'SELECT line_id FROM survey_lines WHERE line_id = ?', (line_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown survey line {line_id!r}')
    return SurveyLine(row[0])
