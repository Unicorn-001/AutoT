"""
File: max_positions.py
Project: AutoT

Purpose:
    Determine whether a new position can be opened.
"""


def can_open_new_position(
    current_open_positions: int,
    maximum_open_positions: int,
) -> bool:
    """
    Check whether another trade can be opened.

    Example:
        Current positions = 3
        Maximum positions = 5

        Result = True
    """

    if maximum_open_positions <= 0:
        raise ValueError(
            "Maximum open positions must be greater than zero."
        )

    return current_open_positions < maximum_open_positions