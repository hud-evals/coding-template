# REDACTED IN THIS EXAMPLE

The real prompt is not included so this task can't be copied. This file
explains what belongs here.

**This file is mandatory.** `tasks.py` reads it and yields it verbatim as the
agent's first message.

## What a prompt contains

**The ticket** (the actual task): written the way a senior engineer would
assign the work. Intent-inferring, not solution-leaking:

- Describe symptoms and business context, not the fix
  (*"listing is slow and latency grows linearly with page size; an SDK-level
  trace shows queries executing strictly one after another"*)
- Include real-world constraints a teammate would mention
  (*"we've had throttling incidents; cursors held by deployed clients must
  keep working"*)
- Mention file/function names only if a real ticket naturally would
- Keep quality expectations realistic (*"all repo quality gates apply"*)

## What NOT to put here

- The intended solution or its shape (*"use a k-way merge..."*)
- Hints about hidden tests or grading criteria
- Anything an LLM would recognize as benchmark-speak - write like a human
