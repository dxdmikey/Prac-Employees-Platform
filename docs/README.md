# Documentation

- `TODO.md` - the roadmap: every stage, what was built, how it was verified,
  and the checkpoint findings. This is the project-level progress tracker.
- `../CLAUDE.md` - the architecture rules, conventions and the "how it is
  built" notes for each subsystem. Read this before changing anything.
- `../README.md` - what the project is, how to set it up and run it.

Design notes for the metadata model, RBAC + business-unit scoping, the
workflow engine and the dashboard/widget pipeline live in the module docstrings
of the code they describe (for example `backend/app/workflows/engine.py`),
so they cannot drift from the implementation.
