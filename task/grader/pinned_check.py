#!/usr/bin/env python3
"""Verify the pinned unsharded-cursor tests are untouched.

Usage: pinned_check.py <pristine Aggregate.test.ts> <current Aggregate.test.ts>

The two pinned tests lock the unsharded cursor wire format (base64 raw
LastEvaluatedKey JSON). Each test body is extracted from its title string to
the start of the next `it.effect(` call and compared whitespace-normalized,
so inserting new tests around them is fine but editing or deleting them is
not. Exit 0 if both are intact, 1 otherwise.
"""

import re
import sys

TITLES = [
    "pagination: returns cursor when limit is set and more items exist",
    "pagination: uses cursor to resume from previous position",
]


def extract(text: str, title: str) -> str | None:
    start = text.find(title)
    if start < 0:
        return None
    end = text.find("it.effect(", start + 1)
    block = text[start : end if end > 0 else len(text)]
    return re.sub(r"\s+", " ", block).strip()


def main() -> int:
    pristine_path, current_path = sys.argv[1], sys.argv[2]
    pristine = open(pristine_path, encoding="utf-8").read()
    current = open(current_path, encoding="utf-8").read()
    for title in TITLES:
        expected = extract(pristine, title)
        actual = extract(current, title)
        if expected is None:
            print(f"pinned_check: title missing from pristine copy: {title}", file=sys.stderr)
            return 1
        if actual != expected:
            print(f"pinned_check: pinned test modified or removed: {title}", file=sys.stderr)
            return 1
    print("pinned_check: pinned cursor tests intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
