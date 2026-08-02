import sys

# Never write .pyc bytecode caches for this project. Stale bytecode can
# mask source edits during rapid iterative testing (e.g. patch-a-file,
# rerun-tests, restore-the-file cycles used to verify a test actually
# discriminates a bug) -- pytest would then silently run against old
# code and report misleading results. See CLAUDE.md.
#
# This covers pytest-driven runs (conftest.py loads before test modules
# are imported). For ad-hoc `python3 -c` / script runs outside pytest,
# set the PYTHONDONTWRITEBYTECODE=1 environment variable instead -- this
# flag has no effect on an interpreter that has already started.
sys.dont_write_bytecode = True
