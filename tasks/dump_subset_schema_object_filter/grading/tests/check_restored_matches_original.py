"""Criterion 4 -- the restored database behaves as the original did.

Scored as a verdict: the scoreboard (tasks.py) reads the exit code, not the
GRADER_SCORE line, which is printed only so the trace shows how far a failing
tree got and which pairs it failed.  The contract is the ticket's own binary
sentence -- restoring the file gives you the database that was backed up, or
it does not -- and a backup the operator cannot trust on 4 requests out of 25
is not 84% of a backup.  The gradient lives in criterion 5, family by family.

The ticket asks for one thing and this criterion is that thing: "restoring it
gives you what restoring a whole-database backup would have given you, minus
the tables you did not ask for ... the same rows, the same answers to the same
questions, the same errors where the original had errors".

A pair counts only in full, and every part of it is a comparison of two
answers, never a test for success:

  * the schema objects of the restored database are exactly the reference set
    -- nothing lost, nothing that reaches outside the requested tables, each
    one carried through with its text as it was ("what comes along comes along
    as it is");
  * every view answers what it answered in the original: the same rows, or the
    same error;
  * every requested table answers the frozen write probes exactly as the
    original answers them.

That last pair of points is what makes an already-broken database gradeable.
A view whose table was dropped years ago fails in the original too; carrying it
is what keeps the restored database the same database, and quietly dropping it
"repairs" a database that was only meant to be copied. Both are caught here,
in the same comparison, from opposite directions.

The reference is not read off any implementation: it is the largest set of
objects the two databases agree about, discovered by experiment outside the
container and proved maximal there (tools/build_corpus.py).

Scoring. Some pairs are already right in the untouched tree -- a subset that
happens to be the whole database, or a fixture whose every object needs only
the requested table. Those carry no credit: they are the anti-vacuum controls,
there to make sure "throw every view and trigger away" is not a solution, and
they can only be lost, never earned.

    score = max(0, earned - regressed) / (pairs the base tree gets wrong)

so an untouched checkout scores exactly zero, a change that drops everything
scores exactly zero, and only pairs the base gets wrong are worth anything.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("GRADER_DIR", ""), "lib") or "lib")
import checkbase as cb  # noqa: E402
import oracle  # noqa: E402

r = cb.Report("criterion 4: the restored database answers as the original does")
results = cb.produce()

free = set(cb.EXPECTED["base_pass"])          # already right without any change
earnable = sorted(set(cb.PAIRS) - free)

earned = 0
regressed = 0
for pid in sorted(cb.PAIRS):
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

total = len(earnable)
score = max(0, earned - regressed) / float(total) if total else 0.0
print("\n%d of %d earnable pairs, %d regression(s) on the %d control pair(s)"
      % (earned, total, regressed, len(free)))
r.finish(score=score)
