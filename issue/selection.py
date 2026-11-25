from dataclasses import dataclass
import sqlite3

from quality.process import Qualification, load_qualification
from quality.ranges import MeterInterval, validate_window
from source.revisions import RevisionSnapshot, load_revision


@dataclass(frozen=True)
class IssueSelection:
    revision: RevisionSnapshot
    qualification: Qualification
    window: MeterInterval


def select_issue(db: sqlite3.Connection, revision_id: int, window: MeterInterval) -> IssueSelection:
    validate_window(window)
    revision = load_revision(db, revision_id)
    qualification = load_qualification(db, revision_id)
    if qualification.frozen != (revision.state == 'frozen'):
        raise ValueError(f'freeze state mismatch for revision {revision_id}')
    return IssueSelection(revision, qualification, window)
