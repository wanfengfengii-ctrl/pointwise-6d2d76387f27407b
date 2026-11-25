from collections.abc import Iterable
import sqlite3

from quality.ranges import validate_window
from source.calibrations import CalibrationBatch, init_calibrations, store_calibrations
from source.lines import SurveyLine, init_lines, store_line
from source.passes import SurveyPass, init_passes, store_revision_passes, validate_pass_bindings
from source.revisions import create_working_revision, init_revisions
from source.strips import RawStrip, init_strips, store_revision_strips


class RegistrationError(ValueError):
    pass


def init_source(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    with db:
        init_lines(db)
        init_calibrations(db)
        init_revisions(db)
        init_passes(db)
        init_strips(db)


def _require_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')


def _ids(records: tuple, model: type, field: str) -> set[str]:
    identifiers = set()
    for record in records:
        if not isinstance(record, model):
            raise ValueError(f'expected a {model.__name__} record')
        identifier = getattr(record, field)
        _require_id(identifier, field)
        if identifier in identifiers:
            raise ValueError(f'duplicate {field} {identifier!r}')
        identifiers.add(identifier)
    return identifiers


def _validate_records(
    line: SurveyLine, passes: tuple[SurveyPass, ...], strips: tuple[RawStrip, ...]
) -> None:
    if not isinstance(line, SurveyLine):
        raise ValueError('expected a SurveyLine record')
    _require_id(line.line_id, 'line_id')
    pass_ids = _ids(passes, SurveyPass, 'pass_id')
    _ids(strips, RawStrip, 'strip_id')
    for survey_pass in passes:
        _require_id(survey_pass.batch_id, 'batch_id')
    for strip in strips:
        _require_id(strip.pass_id, 'pass_id')
        if strip.pass_id not in pass_ids:
            raise ValueError(f'strip {strip.strip_id!r} refers to an unlisted pass')
        validate_window(strip.window)
        if strip.depth is not None and not isinstance(strip.depth, str):
            raise ValueError('raw depth must be decimal text or None')
        if not isinstance(strip.unit, str):
            raise ValueError('raw unit must be text')


def register(
    db: sqlite3.Connection, line: SurveyLine, calibrations: Iterable[CalibrationBatch],
    passes: Iterable[SurveyPass], strips: Iterable[RawStrip],
) -> int:
    try:
        batch_records = tuple(calibrations)
        pass_records = tuple(passes)
        strip_records = tuple(strips)
        new_batches = _ids(batch_records, CalibrationBatch, 'batch_id')
        _validate_records(line, pass_records, strip_records)
        db.execute('BEGIN IMMEDIATE')
        with db:
            validate_pass_bindings(db, pass_records, new_batches)
            store_line(db, line)
            store_calibrations(db, batch_records)
            revision_id = create_working_revision(db, line)
            store_revision_passes(db, revision_id, pass_records)
            store_revision_strips(db, revision_id, strip_records)
    except (ValueError, TypeError, sqlite3.Error) as error:
        raise RegistrationError(str(error)) from error
    return revision_id
