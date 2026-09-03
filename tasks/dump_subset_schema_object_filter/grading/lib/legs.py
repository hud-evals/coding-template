"""Running one named leg. Lifted verbatim out of the old criterion 5.

The old check owned this code and ran all 29 legs in one criterion. It now
lives here so the five leg criteria run exactly the same code over exactly the
same cases; splitting the scoreboard must not change a single verdict, and the
offline regrade of the archived pool relies on that.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checkbase as cb  # noqa: E402
import oracle  # noqa: E402


class Runner:
    """Restores each pair once and answers "is this leg green?"."""

    def __init__(self, results):
        self.results = results
        self.restored = {}
        for pid in sorted(cb.PAIRS):
            self.restored[pid] = cb.restore_pair(results[pid])

    def check_case(self, case):
        pid = "%s__%s" % (case["fixture"],
                          "+".join(case["subset"]) if case["subset"] else "ALL")
        path, why = self.restored[pid]
        if path is None:
            return "%s: %s" % (pid, why)
        conn = oracle.connect(path)
        try:
            names = set(oracle.object_order(conn))
        finally:
            conn.close()
        for n in case.get("present", []):
            if n not in names:
                return "%s: %s was dropped, but the original has it and it belongs" % (pid, n)
        for n in case.get("absent", []):
            if n in names:
                return "%s: %s came back, but the restored database does not answer "\
                       "about it the way the original does" % (pid, n)
        for n in case.get("same_error", []):
            want = cb.PAIRS[pid]["views"][n]
            conn = oracle.connect_text(path)
            try:
                got = oracle.view_outcome(conn, n)
            finally:
                conn.close()
            if got != want:
                return "%s: %s answers %r, the original answers %r" % (
                    pid, n, got[0] if got[0] == "ok" else got[1],
                    want[0] if want[0] == "ok" else want[1])
        wanted = case.get("order", [])
        if wanted:
            conn = oracle.connect(path)
            try:
                order = oracle.object_order(conn)
            finally:
                conn.close()
            missing = [n for n in wanted if n not in order]
            if missing:
                return "%s: %s missing, so there is no order to check" % (pid, missing)
            idx = [order.index(n) for n in wanted]
            if idx != sorted(idx):
                return "%s: replay order %s does not follow the dependencies" % (
                    pid, [order[i] for i in sorted(idx)])
        if "seq" in case:
            conn = oracle.connect(path)
            try:
                got = oracle.sequence_rows(conn)
            finally:
                conn.close()
            if got != case["seq"]:
                return "%s: counters %s, expected %s" % (pid, got, case["seq"])
        return ""

    def check_odd(self):
        """One tables= request the HTTP surface passes through, three possible
        answers: a file that loads (fine), a clear error where the request
        names one of SQLite's own tables (fine), or a file that does not load
        (the only thing the ticket forbids)."""
        for odd in cb.ODD:
            internal = any(n.lower().startswith("sqlite_") for n in odd["subset"])
            res = self.results[odd["id"]]
            if res.get("panic"):
                return "tables=%r: the dump path panicked: %s" % (odd["subset"], res["panic"])
            if res.get("dump_error"):
                if internal:
                    continue
                return "tables=%r: Dump returned an error: %s" % (
                    odd["subset"], res["dump_error"])
            path, why = cb.restore_pair(res)
            if path is None:
                return "tables=%r: %s" % (odd["subset"], why)
            if res.get("repo_error"):
                return "tables=%r: the repo's own restore path rejects it: %s" % (
                    odd["subset"], res["repo_error"])
        return ""

    def run(self, leg):
        """"" if the leg is green, else the first thing that is wrong."""
        if leg.get("odd"):
            return self.check_odd()
        for case in leg["cases"]:
            bad = self.check_case(case)
            if bad:
                return bad
        return ""
