"""Finite Decimal values at persistence/execution boundaries."""

from decimal import Decimal, InvalidOperation


def decimal_value(value, *, positive=False):
    try:
        if isinstance(value, bool):
            raise ValueError("Boolean is not a financial value.")
        result = Decimal(str(value))
        if not result.is_finite() or (positive and result <= 0):
            raise ValueError("Expected a finite positive financial value.")
        return result
    except (InvalidOperation, TypeError) as error:
        raise ValueError("Invalid financial value.") from error
