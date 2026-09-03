"""The contract half of one branch: the restored database IS the original.

    check_restored_class.py <dependency_closure|schema_breadth
                             |broken_originals|request_shapes>

This is the old criterion 4, unchanged in what it measures and split by the
branch it measures it on.  Every comparison, every reference set and every
probe is byte-for-byte the one `check_restored_matches_original.py` used; the
only new thing is that the pairs are partitioned by the sentence of the ticket
they belong to, and each partition is its own criterion with its own weight.

For the pairs of this branch:

  * the schema objects of the restored database are exactly the reference set
    -- nothing lost, nothing that reaches outside the requested tables, each
    one carried through with its text as it was;
  * every view answers what it answered in the original: the same rows, or the
    same error;
  * every requested table answers the frozen write probes exactly as the
    original answers them.

Scoring, unchanged from criterion 4 and now applied inside the branch:

    score = max(0, earned - regressed) / (pairs of this branch the base tree
                                          gets wrong)

The control pairs (`base_pass`) of this branch carry no credit and can only be
lost, so "throw every view and trigger away" scores zero here rather than
buying a partial.  An untouched checkout scores exactly zero on every branch.

The exit code is the plain verdict (0 only at a full 1.0); tasks.py reads the
GRADER_SCORE line for the weighted value and the exit code for the blocker
rule.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("GRADER_DIR", ""), "lib") or "lib")
import branches  # noqa: E402
import checkbase as cb  # noqa: E402
import oracle  # noqa: E402

klass = sys.argv[1] if len(sys.argv) > 1 else ""
if klass not in branches.PAIR_CLASSES:
    raise SystemExit("usage: check_restored_class.py <%s>"
                     % "|".join(sorted(branches.PAIR_CLASSES)))
fixtures = set(branches.PAIR_CLASSES[klass])

r = cb.Report("branch %s: the restored database answers as the original does" % klass)
results = cb.produce()

free = set(cb.EXPECTED["base_pass"])
mine = [p for p in sorted(cb.PAIRS) if branches.fixture_of(p) in fixtures]
earnable = [p for p in mine if p not in free]
if not earnable:
    raise SystemExit("branch %s has no earnable pair; the corpus and "
                     "branches.py disagree" % klass)

earned = 0
regressed = 0
for pid in mine:
    p = cb.PAIRS[pid]
    path, why = cb.restore_pair(results[pid])
    ok, reason = (False, why) if path is None else oracle.judge_matches_original(path, p)

    if pid in free:
        if ok:
            r.ok("%s: %d object(s), every answer the original's (control: right "
                 "in the base tree too)", pid, len(p["objects"]))
        else:
            regressed += 1
            r.fail("%s: REGRESSION -- the base tree gets this pair right: %s", pid, reason)
        continue

    if ok:
        earned += 1
        r.ok("%s: %d object(s), %d view(s) and %d table(s) answer as the original",
             pid, len(p["objects"]), len(p["views"]), len(p["table_probes"]))
    else:
        r.fail("%s: %s", pid, reason)

score = max(0, earned - regressed) / float(len(earnable))
print("\n%s: %d of %d earnable pairs, %d regression(s) on the %d control pair(s)"
      % (klass, earned, len(earnable), regressed, len(mine) - len(earnable)))
r.finish(score=score)
