"""Local calibration: run the whole grader over one or more trees, no Docker.

Reproduces exactly what tasks.py computes - the criteria list, the weights, the
blocker set, the fractional criteria and the two cap scales are read straight
out of tasks.py, so the numbers here cannot drift from the numbers the platform
will produce.

The untouched checkout is graded criterion by criterion like any other tree.
tasks.py would short-circuit it (an empty diff returns 0.0 before any grader
runs), and --base makes this script report that same number - but the short
circuit is never what the 0.00 rests on here: every criterion is executed over
the pristine tree, because "every semantic check is red on an untouched
checkout" is the calibration invariant that matters, and a base that only
scores zero through the empty-diff path is a broken grader wearing a clean
number.

Usage:
    python3 tools/calibrate.py --base ../repo-base \\
        gold=../repo base=../repo-base adv_tbl_name=../repo-adv1
    python3 tools/calibrate.py --json --base ... gold=... base=...
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SCORE_LINE = re.compile(r"^GRADER_SCORE\s+([0-9.]+)\s*$", re.M)


WANTED = ("GRADERS", "FRACTIONAL", "GATES", "BLOCKER_SCALE", "GATE_SCALE",
          "PRISTINE_GREEN")


def _literal(node):
    """ast.literal_eval, plus a plain division of two numbers so tasks.py can
    write BLOCKER_SCALE = 1 / 3 instead of a rounded decimal."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _literal(node.left) / _literal(node.right)
    return ast.literal_eval(node)


def load_scoreboard():
    """Read the scoreboard out of tasks.py without importing hud.

    tasks.py is the ONLY place the criteria, the weights, the blocker set, the
    fractional criteria, the scope gates, the two cap scales and the pristine-
    green names are written down; this script re-reads them rather than
    restating them, so a reweight is one edit and these numbers cannot drift
    from the platform's.  Everything read here has to be a literal --
    ast.literal_eval does not run comprehensions -- which is why FRACTIONAL is
    spelled out in tasks.py instead of being derived from GRADERS.
    """
    tree = ast.parse(open(os.path.join(ROOT, "tasks.py")).read())
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
        if name in WANTED:
            found[name] = _literal(node.value)
    missing = [n for n in WANTED if n not in found]
    if missing:
        raise SystemExit("could not read %s out of tasks.py" % ", ".join(missing))

    graders = found["GRADERS"]
    gates = found["GATES"]
    names = [n for n, _w, _b, _k, _t in graders]
    gate_names = [n for n, _k, _t in gates]
    pristine = list(found["PRISTINE_GREEN"])

    for name in found["FRACTIONAL"]:
        if name not in names:
            raise SystemExit("tasks.py calls %r fractional, but it is not a "
                             "criterion" % name)
    overlap = sorted(set(names) & set(gate_names))
    if overlap:
        raise SystemExit("tasks.py lists %s as both a scope gate and a scored "
                         "criterion; a gate carries no weight and produces no "
                         "subscore" % ", ".join(overlap))
    # v5: the pristine-green names are GATES, not criteria.  Under the previous
    # scoreboard they were criteria pinned to weight 0.00, which the programme
    # forbids outright -- a criterion worth nothing is a note pretending to be a
    # score.  They keep their calibration job: green on an untouched checkout by
    # design, so they may never carry weight, and every OTHER check -- gate or
    # criterion -- has to be flat red on the base tree.
    for name in pristine:
        if name in names:
            raise SystemExit(
                "tasks.py scores %s as a criterion and also calls it pristine-"
                "green; a check green on the base tree cannot carry weight, and "
                "a criterion at weight 0.00 is out of law -- it belongs in GATES"
                % name)
        if name not in gate_names:
            raise SystemExit("tasks.py calls %r pristine-green, but it is "
                             "neither a gate nor a criterion" % name)
    return (graders, list(found["FRACTIONAL"]), gates,
            (float(found["BLOCKER_SCALE"]), float(found["GATE_SCALE"])), pristine)


def run_criteria(label, repo, graders, fractional, gates):
    """Run the gates first, then the criteria -- the order tasks.py uses.

    Gates land in the same dict as the criteria, with weight 0.0 and a
    ``gate`` flag, because every consumer here wants to see all thirteen
    checks; ``score()`` is the one place the difference matters.
    """
    state = os.path.join(ROOT, ".calib", label)
    shutil.rmtree(state, ignore_errors=True)
    os.makedirs(state)
    env = dict(os.environ)
    env.update({
        "REPO_DIR": repo,
        "GRADER_DIR": ROOT,
        "GRADER_STATE_DIR": state,
        "GRADER_PYTHON": sys.executable,
    })
    checks = ([(n, 0.0, False, True, t) for n, _k, t in gates]
              + [(n, w, b, False, t) for n, w, b, _k, t in graders])
    results = {}
    for name, weight, blocker, is_gate, timeout in checks:
        start = time.monotonic()
        proc = subprocess.run(["bash", os.path.join(ROOT, "run_grading.sh"), name],
                              env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
        elapsed = time.monotonic() - start
        out = proc.stdout.decode("utf-8", "replace")
        passed = proc.returncode == 0
        value = 1.0 if passed else 0.0
        # A gate is a verdict: it never contributes a fraction to anything.
        if name in fractional and not is_gate:
            found = SCORE_LINE.findall(out)
            if found:
                value = max(0.0, min(1.0, float(found[-1])))
        results[name] = {
            "value": value,
            "passed": passed,
            "weight": weight,
            "blocker": blocker,
            "gate": is_gate,
            "seconds": round(elapsed, 1),
            "tail": out[-1500:],
        }
        print("  %-4s %-32s %-4s %5.3f %6.1fs"
              % ("GATE" if is_gate else "crit", name,
                 "PASS" if passed else "FAIL", value, elapsed))
    return results


def score(results, graders, gates, scales):
    """Exactly what tasks.py._grade computes: weighted sum over the criteria,
    then the uniform cap arithmetic -- u * BLOCKER_SCALE when any blocking
    criterion fails, then min(r, u * GATE_SCALE) when any gate fails.  Gates
    carry no weight, so they move the reward only through the scale.

    The anti-hack gate of tasks.py is not run here: it reads the agent's diff,
    and the calibration trees are whole checkouts.  It is exercised by the
    local sanity harness instead (see CHANGES.md)."""
    blocker_scale, gate_scale = scales
    uncapped = sum(r["value"] * r["weight"] for r in results.values()
                   if not r["gate"])
    failed = [n for n, _w, b, _k, _t in graders if b and not results[n]["passed"]]
    tripped = [n for n, _k, _t in gates if not results[n]["passed"]]
    if not failed and not tripped:
        return uncapped, uncapped, None, [], []
    reward = uncapped
    if failed:
        reward = uncapped * blocker_scale
    if tripped:
        reward = min(reward, uncapped * gate_scale)
    return max(0.0, reward), uncapped, reward, failed, tripped


def tree_differs(tree, base):
    """Does this tree differ from the base checkout the agent started from?"""
    if not base:
        return True
    proc = subprocess.run(
        ["diff", "-r", "-q", "--exclude=.git", base, tree],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    lines = [ln for ln in proc.stdout.decode("utf-8", "replace").splitlines()
             if ln.startswith("Files ") or ln.startswith("Only in ")]
    return bool(lines)


def check_invariants(report, graders, gates, scales, pristine_green):
    """The calibration invariants, asserted rather than eyeballed.

    Labels carry meaning, and that is deliberate -- the invariant a tree has to
    satisfy depends on what the tree is:

      gold      scores exactly 1.00, passes every criterion and clears every
                scope gate;
      base      scores exactly 0.00 through the criteria, with the pristine-
                green gates green (a gate that is red on an untouched checkout
                would be charging runs for the repo's own state) and EVERY
                other check -- gate or criterion -- flat red.  "Flat" is the
                word that matters under v5: nine of the ten criteria are
                fractional now, so a base that merely fails them is not
                enough; a base that scores 0.30 on a branch is a branch whose
                partial credit is free, and the pool mean rests on that never
                being true;
      noop      a cosmetic patch, scores exactly 0.00;
      adv_*     a plausible-but-wrong solution: must fail at least one blocker
                or trip a gate, so it is scaled down, and must never reach
                1.00 -- nor more than the larger scale times what it earned.
                adv_parser and adv_probe are singled out because they are the
                two sides of the fork -- the tree that reads the SQL itself,
                and the tree that asks SQLite but only whether things work.
                The v4 check was "neither may pass criterion 4"; criterion 4 is
                now the four branch contracts, whose union is exactly the pairs
                it graded, so the same assertion is "neither may hold all four
                at a full 1.00".  If either ever does, the oracle has stopped
                measuring the thing the task is about;
      fair_*    a tree that answered honestly in a way the ticket allows (an
                error instead of a broken file).  It must not be punished: it
                scores exactly what the gold scores.
    """
    problems = []
    all_names = [n for n, _w, _b, _k, _t in graders]
    gate_names = [n for n, _k, _t in gates]
    contracts = [n for n in all_names if not n.startswith("legs_")]
    semantic = all_names + [n for n in gate_names if n not in pristine_green]

    def crit(label, name):
        return report[label]["criteria"][name]

    if "gold" in report:
        if abs(report["gold"]["reward"] - 1.0) > 1e-9:
            problems.append("gold scores %.3f, not 1.000" % report["gold"]["reward"])
        for name in all_names:
            if not crit("gold", name)["passed"]:
                problems.append("gold fails %s" % name)
        for name in gate_names:
            if not crit("gold", name)["passed"]:
                problems.append("gold trips the scope gate %s" % name)

    for label in ("base", "noop"):
        if label not in report:
            continue
        if report[label]["reward"] > 1e-9:
            problems.append("%s scores %.3f, not 0.000" % (label, report[label]["reward"]))
        for name in semantic:
            kind = "gate" if crit(label, name)["gate"] else "criterion"
            if crit(label, name)["passed"]:
                problems.append(
                    "%s passes %s -- a %s that is green without any change "
                    "measures nothing" % (label, name, kind))
            elif crit(label, name)["value"] > 1e-9:
                problems.append("%s scores %.2f on %s; a semantic %s has to be "
                                "flat red on an untouched tree"
                                % (label, crit(label, name)["value"], name, kind))
        for name in pristine_green:
            if not crit(label, name)["passed"]:
                problems.append("%s fails the pristine-green gate %s -- runs would be "
                                "charged for the repo's own state" % (label, name))

    for label in report:
        if not label.startswith("adv_"):
            continue
        if report[label]["reward"] >= 1.0 - 1e-9:
            problems.append("%s scores 1.000: a wrong solution grades as gold" % label)
        if not report[label]["failed_blockers"] and not report[label]["failed_gates"]:
            problems.append("%s fails no blocker and trips no gate, so nothing "
                            "caps it" % label)
        ceiling = max(scales) * report[label]["uncapped"]
        if report[label]["reward"] > ceiling + 1e-9:
            problems.append("%s scores %.3f, above %.3f (the larger scale times "
                            "what it earned)" % (label, report[label]["reward"], ceiling))
    for label in ("adv_parser", "adv_probe"):
        if label not in report:
            continue
        if all(crit(label, n)["value"] >= 1.0 - 1e-9 for n in contracts):
            problems.append("%s holds every branch contract (%s) at 1.00: the "
                            "oracle no longer catches one side of the fork and "
                            "the task needs redesigning"
                            % (label, ", ".join(contracts)))

    for label in report:
        if not label.startswith("fair_"):
            continue
        if "gold" not in report:
            continue
        if abs(report[label]["reward"] - report["gold"]["reward"]) > 1e-9:
            problems.append("%s scores %.3f where the gold scores %.3f: an honest "
                            "answer the ticket allows is being punished"
                            % (label, report[label]["reward"], report["gold"]["reward"]))
    return problems


def main():
    argv = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    base_tree = ""
    if "--base" in argv:
        i = argv.index("--base")
        base_tree = os.path.abspath(argv[i + 1])
        del argv[i:i + 2]
    trees = []
    for arg in argv:
        label, path = arg.split("=", 1)
        trees.append((label, os.path.abspath(path)))
    if not trees:
        raise SystemExit(__doc__)

    graders, fractional, gates, scales, pristine = load_scoreboard()
    blockers = [(n, w) for n, w, b, _k, _t in graders if b]

    # ─── the enforced limits, checked against the scoreboard itself ────────
    # Every one of these is a rule of the programme's field manual, asserted
    # here rather than restated in a comment, and printed on a line the image
    # build greps for.  A build whose scoreboard drifts out of law does not
    # get to exist.
    limits = [
        ("weight-sum", sum(w for _n, w, _b, _k, _t in graders), "==", 1.00),
        ("max-single-blocker", max([w for _n, w in blockers] or [0.0]), "<=", 0.20),
        ("blocker-weight", sum(w for _n, w in blockers), "<=", 0.75),
        # the uniform cap arithmetic: a failed blocker keeps a third of what
        # was earned, a failed gate at most a fifth.  Pinned as equalities so
        # a softened scale cannot slip through the build.
        ("blocker-scale", scales[0], "==", 1.0 / 3.0),
        ("gate-scale", scales[1], "==", 0.20),
        ("zero-weight-criteria",
         float(sum(1 for _n, w, _b, _k, _t in graders if w == 0)), "==", 0.0),
    ]
    broken = []
    print("SCOREBOARD v6: %d scored criteria, %d scope gates + anti-hack gate, %d blockers"
          % (len(graders), len(gates), len(blockers)))
    for name, got, op, want in limits:
        ok = ((abs(got - want) < 1e-9) if op == "==" else
              (got <= want + 1e-9) if op == "<=" else (got >= want - 1e-9))
        print("LIMIT %-22s %6.2f %s %5.2f %s" % (name, got, op, want,
                                                 "OK" if ok else "BROKEN"))
        if not ok:
            broken.append("%s is %.2f, which is not %s %.2f" % (name, got, op, want))
    if broken:
        raise SystemExit("scoreboard is out of law:\n  * " + "\n  * ".join(broken))
    print("")

    report = {}
    violations = []
    for label, path in trees:
        print("=== %s (%s)" % (label, path))
        empty = not tree_differs(path, base_tree)
        results = run_criteria(label, path, graders, fractional, gates)
        reward, uncapped, cap, failed, tripped = score(results, graders, gates, scales)
        report[label] = {"criteria": results, "reward": reward,
                         "uncapped": uncapped, "cap": cap,
                         "failed_blockers": failed, "failed_gates": tripped,
                         "empty_diff": empty}
        print("  -> reward %.3f (uncapped %.3f, scaled to %s, failed blockers: %s, "
              "tripped gates: %s)"
              % (reward, uncapped, "-" if cap is None else "%.3f" % cap,
                 ", ".join(failed) or "none", ", ".join(tripped) or "none"))
        if empty:
            # The reward printed for a tree identical to the base is the one the
            # criteria produced, NOT the empty-diff short circuit: a base that
            # only reaches 0.00 because tasks.py never ran the graders is a
            # broken grader wearing a clean number.
            print("     (identical to the base checkout; tasks.py would also "
                  "short-circuit this to 0.000 on an empty diff, but the number "
                  "above was earned criterion by criterion)")
            if reward > 1e-9:
                violations.append(
                    "%s is byte-identical to the base checkout yet scores %.3f "
                    "through the criteria" % (label, reward))
        print("")

    violations += check_invariants(report, graders, gates, scales, pristine)

    if as_json:
        for label in report:
            for c in report[label]["criteria"].values():
                c.pop("tail", None)
        print(json.dumps({"trees": report, "violations": violations}, indent=2))
        return 1 if violations else 0

    labels = [label for label, _ in trees]

    def row(name, weight, kind):
        cells = []
        for l in labels:
            c = report[l]["criteria"][name]
            cells.append("PASS" if c["passed"] else
                         ("FAIL (%.2f)" % c["value"] if c["value"] else "FAIL"))
        print("| `%s` | %s | %s | %s |"
              % (name, "--" if weight is None else "%d%%" % round(weight * 100),
                 kind, " | ".join(cells)))

    print("| check | weight | blocker | " + " | ".join(labels) + " |")
    print("|---|---|---|" + "---|" * len(labels))
    for name, _kind, _t in gates:
        row(name, None, "GATE")
    for name, weight, blocker, _k, _t in graders:
        row(name, weight, "yes" if blocker else "no")
    print("| **reward** | | | " + " | ".join("**%.2f**" % report[l]["reward"]
                                             for l in labels) + " |")

    print("")
    if violations:
        print("CALIBRATION FAILED -- %d invariant(s) broken:" % len(violations))
        for v in violations:
            print("  * %s" % v)
        return 1
    print("CALIBRATION OK -- every invariant holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
