"""Shared cron expression parsing utilities.

Used by platform backends to convert cron fields into integer lists
for schedule generation.
"""

from __future__ import annotations


def parse_cron_field(field: str, lo: int, hi: int) -> list[int] | None:
    """Parse a single cron field into a sorted list of ints, or None for '*'.

    Supports: *, */N, A-B, A-B/N, comma-separated lists, and combinations.

    Args:
        field: A single cron field string (e.g., '*/5', '1-5', '0,15,30').
        lo: Minimum valid value for this field (inclusive).
        hi: Maximum valid value for this field (inclusive).

    Returns:
        Sorted list of integer values, or None if the field is '*' (wildcard).
    """
    if field == "*":
        return None
    nums: list[int] = []
    for part in field.split(","):
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            step = int(step_str)
            if range_part == "*":
                r_lo, r_hi = lo, hi
            elif "-" in range_part:
                r_lo_s, r_hi_s = range_part.split("-", 1)
                r_lo, r_hi = int(r_lo_s), int(r_hi_s)
            else:
                r_lo = int(range_part)
                r_hi = hi
            nums.extend(range(r_lo, r_hi + 1, step))
        elif "-" in part:
            a, b = part.split("-", 1)
            nums.extend(range(int(a), int(b) + 1))
        else:
            nums.append(int(part))
    return sorted(set(nums))
