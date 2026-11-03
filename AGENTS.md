# Career OS — Agent Instructions (model-agnostic)

This file is for any coding agent working on `career-os/` — Claude Code,
Codex/ChatGPT, Gemini, Cursor, a local-model agent, or a human. It states
the same rules as `CLAUDE.md` in provider-neutral form, since the whole
point of this subsystem is that it must not depend on one specific model.

## Ground truth

- The database schema is `schemas/schema.sql`. Read it before writing any
  query — don't infer the schema from this document, which may drift.
- The service layer (`src/career_os/services/*.py`) is the only place
  business logic should live. Any client — CLI, MCP tool, script — should
  call these functions rather than writing raw SQL inline, so behavior
  stays consistent across clients.

## Rules every agent must follow

1. **No fabrication.** Don't invent companies, metrics, thresholds,
   interview outcomes, contact details, or application/referral events.
   Use `'unknown'` / `'needs_evidence'` for missing data.
2. **Label inferences.** Anything a model (any model) concludes — "this
   role is Archetype B", "this looks like a strong fit" — is written as a
   `claims` row with `source_type = 'model_inference'`, not as a plain
   fact. Only write `source_type = 'user_confirmed'` when the user
   explicitly confirmed it.
3. **Preserve raw input.** Always go through `services/sources.py` so the
   original text/file is retained, independent of whatever structured
   fields get extracted from it.
4. **Never silently delete or overwrite raw evidence.** Flag duplicates
   (`duplicates` table); don't delete rows to "clean up."
5. **Qualitative fit only.** `role_tier` (1/2/3), `fit_confidence`
   (High/Medium/Low), `interview_signals.signal`
   (Strong/Mixed/Weak/Unknown). No invented numeric percentages.
6. **Stdlib-first.** Core V0.1 depends on nothing beyond the Python
   standard library (`sqlite3`, `argparse`, `hashlib`, `re`, `dataclasses`).
   Adding a dependency is a decision for the user, not something to do
   silently. The one sanctioned exception is `typesafe-sdk` (the Jev
   classifier) — optional, fail-open (see `classify.py` /
   `providers/jev.py`): it's tried first when configured, and any failure
   falls back to the stdlib heuristic rather than raising. Don't remove
   that fallback, and don't add further dependencies without asking.
7. **Keep personal files private.** `profile.md`, `data/` and `inbox/` are the user's private files and stay
   gitignored. Code may read `profile.md` (for seeding) but must not write outside `data/` and `inbox/`.
8. **One system of record.** `data/career.db` is authoritative. Any
   Markdown/CSV/HTML export is a presentation layer generated from the DB,
   never a second place that holds state the DB doesn't also have.

## How to extend safely

- New entity → add a table to `schemas/schema.sql` (idempotent
  `CREATE TABLE IF NOT EXISTS`), add a service module under
  `src/career_os/services/`, add a test in `tests/`.
- New CLI command → thin wrapper in `cli.py` calling a service function.
  Don't put logic in the CLI handler itself.
- New classifier/model → implement it as an alternate function the caller
  can select, keep `heuristics.py`'s no-dependency default working, and
  write results as `model_inference` claims exactly like the heuristic
  does today.
- Before a schema change, run the existing tests
  (`python -m unittest discover -s tests -v`) so a regression is caught
  immediately, not discovered later against the real database.
