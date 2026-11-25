from decimal import Decimal, DecimalException, ROUND_HALF_UP
import re


class MeasurementError(ValueError):
    pass


_DECIMAL_TEXT = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_UNIT_SHIFTS = {'m': 3, 'cm': 1, 'mm': 0}


def depth_to_mm(value: str | None, unit: str) -> int | None:
    if not isinstance(unit, str) or unit not in _UNIT_SHIFTS:
        raise MeasurementError(f'unknown depth unit {unit!r}')
    if value is None:
        return None
    if not isinstance(value, str) or _DECIMAL_TEXT.fullmatch(value) is None:
        raise MeasurementError(f'invalid depth {value!r}')
    try:
        sign, digits, exponent = Decimal(value).as_tuple()
        # Moving the decimal point by tuple construction preserves every digit.
        scaled = Decimal((sign, digits, exponent + _UNIT_SHIFTS[unit]))
        return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))
    except (DecimalException, ValueError, OverflowError) as error:
        raise MeasurementError(f'invalid depth {value!r}') from error
