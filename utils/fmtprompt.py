#!/usr/bin/env python3
"""
Prints the prompt for a given problem id.
"""

from __future__ import annotations

import argparse
import os

# Ensure MCP tools do not load during import
os.environ["MCP_TESTING_MODE"] = "0"

import hud_controller.app as app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("problem_id")

    parser.add_argument("--hints", action="store_true", default=False)
    args = parser.parse_args()

    if args.hints:
        os.environ["HINTS"] = "all"
    else:
        os.environ["HINTS"] = "none"

    spec = app._get_spec(args.problem_id)
    prompt = app.spec_to_statement(spec)
    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
