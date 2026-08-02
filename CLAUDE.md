# CLAUDE.md

Guidance for Claude Code (and any other agent) working in this repo.

## Working conventions

- **RULES.md is the single source of truth for game logic.** Never invent
  fan values, tile counts, or rules not stated there. If something is
  ambiguous or missing, STOP and ask -- don't guess and encode the guess
  as if it were verified.
- **Tests before implementation.** Write the tests first, show them for
  review, and only implement once they're confirmed correct. A test file
  that only fails on a missing import (not on wrong logic) is the
  checkpoint that it's ready to review.
- **Correctness-critical logic is verified by breaking it, not just
  asserted.** For anything where a test could pass "by coincidence" (e.g.
  shanten formulas, claim-priority grouping), temporarily patch the
  implementation to the wrong-but-plausible behavior, confirm the
  relevant test fails as predicted, then restore and confirm green again.
  A test that can't be made to fail this way isn't proven to discriminate
  -- see the bytecode-caching section below for a real case where this
  step caught a false negative.
- **`mahjong/shanten_bruteforce.py` is a regression oracle -- do not
  delete or "clean up" it.** It's an intentionally independent
  reimplementation (no shared helpers with `mahjong/shanten.py`) used to
  cross-check the fast shanten calculator against thousands of random
  hands. Its value is entirely in being a second, differently-derived
  source of truth; it looking redundant with `shanten.py` is the point,
  not a sign it's dead code.

## Always disable Python bytecode caching in this repo

Set `PYTHONDONTWRITEBYTECODE=1` in the shell before running any Python
command here (`export PYTHONDONTWRITEBYTECODE=1`, or prefix individual
commands with it, or use `python3 -B ...`).

**Why this matters, concretely:** during "patch-and-verify" testing --
temporarily editing a source file to introduce a known bug, rerunning the
tests to confirm they actually catch it, then restoring the original --
stale `.pyc` bytecode can get reused across the edit, silently running
tests against the *old* code. This produces a false "nothing failed"
result that looks exactly like a real gap in test coverage, and is very
easy to mistake for one. It has already happened twice in this project's
history. When rapidly overwriting a `.py` file more than once within the
same second, mtime-based cache invalidation is not reliable enough to
catch the change.

If a patch-and-verify experiment ever shows a suspiciously clean "no
tests failed" result, do not accept that at face value -- first rule out
stale bytecode (`find . -name "__pycache__" -exec rm -rf {} +`) before
concluding the test suite has a real gap.

`conftest.py` at the repo root also sets `sys.dont_write_bytecode = True`
as defense in depth for pytest-driven runs, but that only takes effect
for modules imported *after* conftest.py itself loads -- it does not
cover ad-hoc `python3 -c` / script invocations outside pytest (exactly
the kind used for patch-and-verify experiments), so the environment
variable is still the primary fix, not a backup.

## Bytecode caches must never be committed

`.gitignore` excludes `__pycache__/` and `*.pyc`. If `git status` ever
shows `.pyc` files as tracked or about to be added, stop and fix
`.gitignore`/unstage them rather than committing -- this repo's git
history already had 15 committed `.pyc` files at one point (now removed).
