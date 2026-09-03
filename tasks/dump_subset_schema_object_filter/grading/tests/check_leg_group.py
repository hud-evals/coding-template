"""The legs half of one branch: which named cases of it actually work.

    check_leg_group.py <dependency_closure|reference_recognition
                        |broken_originals|request_shapes|next_write>

This is the old criterion 5, unchanged in what it measures and split into the
five groups of `branches.LEG_GROUPS`.  Every leg keeps its identity, its cases
and its verdict; what changes is that a run no longer gets one number for all
29 of them.  A run that has the dependency closure right and the broken
originals wrong now says so in two criteria instead of averaging into one.

Score = the fraction of this group's legs whose every case is green.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("GRADER_DIR", ""), "lib") or "lib")
import branches  # noqa: E402
import checkbase as cb  # noqa: E402
import legs as legrun  # noqa: E402

group = sys.argv[1] if len(sys.argv) > 1 else ""
if group not in branches.LEG_GROUPS:
    raise SystemExit("usage: check_leg_group.py <%s>"
                     % "|".join(sorted(branches.LEG_GROUPS)))
wanted = set(branches.LEG_GROUPS[group])

known = {leg["id"] for leg in cb.LEGS}
missing = wanted - known
if missing:
    raise SystemExit("branches.py names legs the corpus does not have: %s"
                     % sorted(missing))

r = cb.Report("branch %s: the named legs of the restored behaviour" % group)
results = cb.produce()
runner = legrun.Runner(results)

green = 0
mine = [leg for leg in cb.LEGS if leg["id"] in wanted]
for leg in mine:
    bad = runner.run(leg)
    if bad:
        r.fail("%s (%s): %s", leg["id"], leg["what"], bad)
    else:
        green += 1
        r.ok("%s (%s)", leg["id"], leg["what"])

print("\n%s: %d of %d legs green" % (group, green, len(mine)))
r.finish(score=green / float(len(mine)))
