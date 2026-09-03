"""The branches of the ticket, and which measurement belongs to which.

The frozen ticket names five things the subset backup has to get right.  This
file is the ONLY place that mapping is written down; the checks, tasks.py and
calibrate.py all read it, so a branch cannot mean one thing in the grader and
another on the scoreboard.

Each branch is measured twice, by two separate criteria:

  * the CONTRACT half -- "restoring it gives you the database that was backed
    up" -- over the fixture classes that exercise this branch.  This is the
    sentence the ticket actually writes;
  * the LEGS half -- the named minimal cases of that same sentence, so a run
    that got the shape of the branch and missed one case is not scored like a
    run that missed the branch.

Keeping the two halves apart, and keeping the branches apart, is the whole
point: under the previous scoreboard all 22 earnable pairs sat inside ONE
all-or-nothing criterion worth 0.60, so 21 of 22 and 0 of 22 scored the same
and the rubric stopped seeing the difference between the runs.
"""

# fixture classes -> the branch whose sentence they exercise
PAIR_CLASSES = {
    # "On any database that has indexes, views or triggers in it": what a kept
    # table drags along, and what it must not drag along.
    "dependency_closure": ["F1_shop", "F2_chain", "F5_shapes"],
    # "Whatever schema sqlite3 accepts, a backup of it has to work.  The
    # databases people hand us are not the ones we wrote our tests against."
    "schema_breadth": ["F7_parser", "F8_wild"],
    # "the same errors where the original had errors" -- databases that were
    # already broken before the backup was taken.
    "broken_originals": ["F9_broken", "F10_errshapes"],
    # "It takes whatever the caller sends -- a repeated name, an empty one, a
    # name that is not a table, one of SQLite's own, a name with punctuation
    # in it", and what the database does next on those requests.
    "request_shapes": ["F11_requests", "F12_next", "F3_seq"],
}

# named legs -> branch.  Grouped by the mechanism the leg exercises, not by
# the fixture it happens to live in: L3/L4/L5/L11/L12/L13 are all "find the
# table reference in SQL a reader does not expect", which is the schema-
# breadth sentence, even though three of them use the shop fixture.
LEG_GROUPS = {
    "dependency_closure":   ["L1", "L2", "L6", "L7", "L8"],
    "reference_recognition": ["L3", "L4", "L5", "L11", "L12", "L13"],
    "broken_originals":     ["L14", "L15", "L16", "L17", "L18",
                             "L20", "L21", "L22", "L23", "L24"],
    "request_shapes":       ["L10", "L19", "L25", "L26", "L27", "L28"],
    "next_write":           ["L9", "L29"],
}

# Which criterion belongs to which branch, for the weight audit.  The point of
# the audit is the programme rule the previous rubric broke in the other
# direction: the branches the ticket names as equals may not weigh 2% and 32%.
BRANCH_OF_CRITERION = {
    "restored_dependency_closure": "dependency_closure",
    "legs_dependency_closure":     "dependency_closure",
    "restored_schema_breadth":     "schema_breadth",
    "legs_reference_recognition":  "schema_breadth",
    "restored_broken_originals":   "broken_originals",
    "legs_broken_originals":       "broken_originals",
    "restored_request_shapes":     "request_shapes",
    "legs_request_shapes":         "request_shapes",
    "next_write_matches_original": "next_write",
    "legs_next_write":             "next_write",
}


def fixture_of(pair_id):
    return pair_id.split("__")[0]
