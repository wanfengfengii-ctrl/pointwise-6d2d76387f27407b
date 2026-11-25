from dataclasses import dataclass
import sqlite3

from quality.ranges import MeterInterval
from quality.rules import QualityRule, QualityStatus, classify_depth, validate_rule
from quality.units import depth_to_mm
from source.revisions import RevisionSnapshot, load_revision


class QualityError(ValueError):
    pass


@dataclass(frozen=True)
class QualifiedSlice:
    strip_id: str
    pass_id: str
    batch_id: str
    window: MeterInterval
    depth_mm: int | None
    status: QualityStatus


@dataclass(frozen=True)
class Qualification:
    revision_id: int
    rule: QualityRule
    frozen: bool
    slices: tuple[QualifiedSlice, ...]


def init_quality(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    with db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS quality_rules (
                revision_id INTEGER PRIMARY KEY REFERENCES revisions(revision_id),
                min_mm TEXT NOT NULL,
                max_mm TEXT NOT NULL,
                frozen INTEGER NOT NULL CHECK (frozen IN (0, 1))
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS quality_slices (
                revision_id INTEGER NOT NULL REFERENCES quality_rules(revision_id),
                strip_id TEXT NOT NULL,
                depth_mm TEXT,
                status TEXT NOT NULL CHECK (status IN ('qualified', 'missing', 'out_of_range')),
                PRIMARY KEY (revision_id, strip_id),
                FOREIGN KEY (revision_id, strip_id) REFERENCES raw_strips(revision_id, strip_id)
            )
        ''')


def _process(revision: RevisionSnapshot, rule: QualityRule) -> tuple[QualifiedSlice, ...]:
    batches = {survey_pass.pass_id: survey_pass.batch_id for survey_pass in revision.passes}
    results = []
    for strip in revision.strips:
        depth_mm = depth_to_mm(strip.depth, strip.unit)
        results.append(QualifiedSlice(
            strip.strip_id, strip.pass_id, batches[strip.pass_id], strip.window,
            depth_mm, classify_depth(depth_mm, rule),
        ))
    return tuple(results)


def qualify(db: sqlite3.Connection, revision_id: int, rule: QualityRule) -> Qualification:
    try:
        validate_rule(rule)
        db.execute('BEGIN IMMEDIATE')
        with db:
            revision = load_revision(db, revision_id)
            if revision.state != 'working':
                raise ValueError(f'revision {revision_id} is frozen')
            slices = _process(revision, rule)
            db.execute('''
                INSERT INTO quality_rules (revision_id, min_mm, max_mm, frozen)
                VALUES (?, ?, ?, 0)
                ON CONFLICT (revision_id) DO UPDATE SET
                    min_mm = excluded.min_mm, max_mm = excluded.max_mm
            ''', (revision_id, str(rule.min_mm), str(rule.max_mm)))
            db.execute('DELETE FROM quality_slices WHERE revision_id = ?', (revision_id,))
            db.executemany('''
                INSERT INTO quality_slices (revision_id, strip_id, depth_mm, status)
                VALUES (?, ?, ?, ?)
            ''', (
                (revision_id, part.strip_id,
                 None if part.depth_mm is None else str(part.depth_mm), part.status.value)
                for part in slices
            ))
    except (KeyError, ValueError, sqlite3.Error) as error:
        raise QualityError(str(error)) from error
    return Qualification(revision_id, rule, False, slices)


def load_qualification(db: sqlite3.Connection, revision_id: int) -> Qualification:
    if type(revision_id) is not int or not 0 < revision_id < 2**63:
        raise QualityError(f'unknown revision {revision_id!r}')
    rows = db.execute('''
        SELECT q.min_mm, q.max_mm, q.frozen, s.strip_id, r.pass_id, p.batch_id,
               r.start_m, r.end_m, s.depth_mm, s.status
        FROM quality_rules AS q
        LEFT JOIN quality_slices AS s ON s.revision_id = q.revision_id
        LEFT JOIN raw_strips AS r ON r.revision_id = s.revision_id AND r.strip_id = s.strip_id
        LEFT JOIN survey_passes AS p ON p.pass_id = r.pass_id
        WHERE q.revision_id = ? ORDER BY s.strip_id
    ''', (revision_id,)).fetchall()
    if not rows:
        raise QualityError(f'revision {revision_id} has no successful qualification')
    min_mm, max_mm, frozen = rows[0][:3]
    slices = []
    for row in rows:
        strip_id, pass_id, batch_id, start, end, depth, status = row[3:]
        if strip_id is not None:
            slices.append(QualifiedSlice(
                strip_id, pass_id, batch_id, MeterInterval(int(start), int(end)),
                None if depth is None else int(depth), QualityStatus(status),
            ))
    return Qualification(revision_id, QualityRule(int(min_mm), int(max_mm)), bool(frozen), tuple(slices))


def freeze_qualification(db: sqlite3.Connection, revision_id: int) -> None:
    cursor = db.execute('''
        UPDATE quality_rules SET frozen = 1 WHERE revision_id = ? AND frozen = 0
    ''', (revision_id,))
    if cursor.rowcount != 1:
        raise QualityError(f'revision {revision_id} has no working qualification')
