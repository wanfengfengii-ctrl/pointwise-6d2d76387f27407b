from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class QualityRule:
    min_mm: int
    max_mm: int


class QualityStatus(str, Enum):
    QUALIFIED = 'qualified'
    MISSING = 'missing'
    OUT_OF_RANGE = 'out_of_range'


def validate_rule(rule: QualityRule) -> None:
    if not isinstance(rule, QualityRule):
        raise ValueError('expected a QualityRule')
    if type(rule.min_mm) is not int or type(rule.max_mm) is not int:
        raise ValueError('quality thresholds must be integer millimetres')
    if rule.min_mm > rule.max_mm:
        raise ValueError('quality thresholds are inverted')


def classify_depth(depth_mm: int | None, rule: QualityRule) -> QualityStatus:
    validate_rule(rule)
    if depth_mm is None:
        return QualityStatus.MISSING
    if type(depth_mm) is not int:
        raise ValueError('depth must be integer millimetres')
    if rule.min_mm <= depth_mm <= rule.max_mm:
        return QualityStatus.QUALIFIED
    return QualityStatus.OUT_OF_RANGE
