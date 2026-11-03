# Career OS — Claude Code instructions

This file governs work inside this project when you use Claude Code (or a similar coding agent) here.

## What this is

A local SQLite + Python system of record for a job search:
companies, roles, applications, contacts, interactions, interviews,
career evidence, skills, and a provenance ledger. See `README.md` for
architecture and commands, and `STRATEGY.md`
for the design rationale.

## Strategy model

Read `STRATEGY.md` before role analysis, interview prep, learning, or prioritization work. It defines the Generalist + Specialist Spike framework: `problem_shape` (+ rate of change, interconnectedness, critical depth lever, judgment requirement, depth match), SYSTEM -> LEVER -> MECHANISM -> DECISION -> OUTCOME, and the learning check. Shape fields are `model_inference` (the JD is the source). Depth match comes from linked Career Evidence only, never resume keywords. Still no numeric scores.

## Operating principles (referrals, learning sources, job sources)

- The user supplies context, links and updates. Career OS owns organization, relationships, prioritization and retrieval. Data entry should remain lightweight enough that maintaining Career OS never competes with the actual job search.
- Store information once, connect it automatically, and reuse it across pipeline management, referrals, learning, applications, interview preparation and career decisions.
- Do not create complexity until real usage demonstrates that the complexity is necessary.

How they show up in the code: `update` (free text) is the single input door for referrals, job sources and learning resources; incomplete input is preserved (`role_hint`, `raw_sources`, `claims`), never rejected. `roles.source` is the DISCOVERY source and `applications.channel` is the APPLICATION CHANNEL; never overwrite one with the other. Referral priority, source suggestions and learning plans are derived from stored facts (High/Medium/Low, no numeric scores) and source conclusions need 10+ roles. Learning plans recommend only stored resources that a role or interview demands, within a time budget (20% learning / 80% applying).

## Non-negotiable rules

1. **Never fabricate.** No invented companies, metrics, interview feedback,
   contact details, or claims that an application/referral happened when it
   didn't. If a fact isn't available, the value is `'unknown'` or
   `'needs_evidence'` — never a made-up number.
2. **Provenance is mandatory.** Any value a heuristic or LLM derives
   (archetype, fit tier, extracted requirement, fit reasoning) is written
   with `source_type = 'model_inference'` and gets a row in `claims`. It is
   never silently treated as `user_confirmed`. If you promote a guess to a
   confirmed fact because the user said so explicitly, write a new claim
   with `source_type = 'user_confirmed'` — don't just overwrite the old one
   silently.
3. **Preserve raw source.** `add-job`/`add-note`/`update` must go through
   `services/sources.py` so the original text survives independently of
   whatever gets extracted from it. Never write only the extracted fields.
4. **Never silently delete.** Duplicates are flagged in the `duplicates`
   table or merged only when unambiguous. Don't `DELETE` a row because it
   looks redundant — flag it and let a human decide.
5. **Business logic lives in `services/`, not in `cli.py`.** The CLI is a
   thin argument-parsing wrapper. Anything that touches the database or
   makes a decision belongs in a service function so an MCP server or
   another client can call it later without duplicating logic.
6. **No numeric fit scores.** `role_tier` (1/2/3) and `fit_confidence`
   (High/Medium/Low) only. Do not add a `fit_score: 87` style field.
7. **Keep personal files out of the code and the repo.** `profile.md`, `data/` and `inbox/`
   are the user's private files and stay gitignored. Code may read `profile.md` (for seeding) but
   must never write to files outside `data/` and `inbox/`.
8. **Don't add dependencies** without asking. V0.1 is deliberately stdlib
   Python + SQLite only. If a task seems to need `pip install X`, stop and
   confirm with the user first — that's a genuine architecture fork per the
   parent instructions' ambiguity-handling rule. **One sanctioned exception:**
   `typesafe-sdk` (the Jev classifier, see `providers/jev.py`) — explicitly
   approved by the project owner. It's optional and
   fail-open: `classify.py` checks `jev.is_configured()` and catches any
   exception from a Jev call, falling back to `heuristics.py` so the stdlib
   path keeps working with the package absent or the API unreachable. Any
   *other* new dependency still needs to be asked about.

## Development conventions

- Every schema change goes in `schemas/schema.sql` as an additional
  `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` — don't hand-edit
  `data/career.db`'s structure outside the schema file, since the schema
  file is what makes the system portable to a fresh machine.
- Service functions take `conn: sqlite3.Connection` as the first argument
  and commit their own writes. Callers (CLI, tests, future MCP tools) own
  connection lifecycle (open/close), not the service functions.
- Keep `heuristics.py` dependency-free (no LLM calls). If a smarter
  classifier is wanted, add it as an alternate function/class the caller
  can pass in — don't make the default path require an API key.
- Tests are stdlib `unittest`, isolated via a temp SQLite file per test
  (see `tests/test_career_os.py`). Add a test alongside any new service
  function that changes state.
- Real personal data (`data/career.db`) is gitignored; `schemas/schema.sql`
  is committed. Don't change that split without asking.

## When extending toward MCP / agents (deferred, but keep room for it)

The service layer in `services/` should remain the single place that owns
business logic, specifically so a thin MCP tool wrapper (`add_job`,
`add_note`, `get_pipeline`, etc.) can be added later without rewriting
anything. Don't build the MCP server itself unless asked — just don't make
decisions now that would make it hard later (e.g., don't put decision logic
in `cli.py` print statements; keep it in functions that return data).
