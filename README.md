# Career OS

A local-first system of record for a job search. It keeps jobs, applications, interviews, contacts,
referrals, notes and career evidence in **one SQLite file on your computer**, and gives you:

- an **Action Center**: what needs doing this week, with deadlines and a "what not to do" list
- a **Dashboard**: weekly applications vs your target, funnel, channels, drill-down to the rows
- a **Data Browser** with themes, a collapsible sidebar and a plain-English update box
- a **CLI** for everything, and a service layer that any script or AI agent can call

No packages to install: Python 3.10+ and the standard library only. Nothing leaves your machine.
It runs at `http://127.0.0.1:8765/` and is not reachable from other devices.

> **Full guide:** [`docs/GUIDE.pdf`](docs/GUIDE.pdf) (screenshots, workflow, customizing).

## Quick start

```bash
git clone https://github.com/<owner>/career-os.git
cd career-os
python cli.py init            # creates data/career.db (empty, private, gitignored)
python cli.py serve           # open http://127.0.0.1:8765/
```

Want to look around first with fictional data (never touches your real database)?

```bash
# macOS / Linux
CAREER_OS_DB=/tmp/demo.db python cli.py init && CAREER_OS_DB=/tmp/demo.db python cli.py seed-demo
CAREER_OS_DB=/tmp/demo.db python cli.py serve

# Windows (PowerShell)
$env:CAREER_OS_DB = "$PWD\demo.db"; python cli.py init; python cli.py seed-demo; python cli.py serve
```

## Everyday use

Say what happened in plain English; Career OS files it for you.

```bash
python cli.py add-job --company "Acme" --title "Senior TPM" --jd-file jd.txt --url "https://..."
python cli.py update "Applied to Acme through a referral from Jordan."
python cli.py update "Acme recruiter screen scheduled Tuesday."
python cli.py update "Acme role rejected."
python cli.py add-note "Sam said Globex is hiring for search PMs."
python cli.py next-action 3 "Send thank-you note" --date 2026-11-05   # feeds the Action Center
python cli.py pipeline            # your pipeline as a table
python cli.py actions             # this week's actions (same as the Action Center tab)
python cli.py metrics             # dashboard numbers in the terminal
python cli.py role 3              # one role's full dossier
python cli.py review              # weekly review: stop / continue / start
python cli.py export-data --out backup.json
```

The same update box exists in the web UI. More commands: `python cli.py --help`.

## Make it yours

Career OS ships with **fictional example data**. Replace it with your own:

| What | Where |
|---|---|
| Target companies and tiers (A/B/C/Watchlist) | `src/career_os/seed.py`, `COMPANY_PORTFOLIO`, then `python cli.py seed` |
| Career-evidence stories (your projects, metrics) | `src/career_os/seed.py`, `_EVIDENCE_SEEDS`, or add rows through the UI |
| Role "lanes" A/B/C and skill keywords | `src/career_os/heuristics.py` |
| Depth "spikes" (your specialist strengths) | `src/career_os/services/problem_shape.py`, `SPIKES` |
| Weekly application target (default 10) | `src/career_os/services/metrics.py`, `WEEKLY_TARGET` |
| Standing "what not to do" rules | `src/career_os/services/actions.py`, `STANDING_RULES` |
| Your own notes about yourself | `profile.md` next to `cli.py` (gitignored; stored as a raw source on seed) |

Use a different database file (for a second search, or a demo) with the `CAREER_OS_DB` environment variable.

## Privacy

- Your data lives in `data/career.db` and `inbox/`. Both are **gitignored**. Back them up yourself.
- The web server binds to `127.0.0.1` only and has no login, because nothing else can reach it.
  Do not change the bind address without adding authentication.
- Nothing is sent anywhere. The optional AI classifier (see below) is off unless you set an API key.

## Facts versus guesses

Every value a heuristic or AI derives (role lane, fit tier, extracted requirement) is stored as a
`model_inference` claim with its basis, and is never silently promoted to a fact. Fit is qualitative on
purpose: priority 1/2/3 (Top/Medium/Low) and confidence High/Medium/Low. There are no numeric fit scores.
Raw text you paste is kept as-is in `inbox/` and the `raw_sources` table. Nothing is silently deleted.

## Optional: AI classifier

By default roles are classified by a keyword heuristic (`heuristics.py`, offline). If you install
`typesafe-sdk` and set `TYPESAFE_API_KEY`, `providers/jev.py` is tried first and falls back to the
heuristic on any failure. This is optional; the rest of the system works without it.

## Using it with an AI coding agent

`CLAUDE.md` and `AGENTS.md` describe the rules an agent should follow here (never fabricate, label
inferences, keep raw sources, put logic in `services/`, keep personal files private). Point Claude Code,
Codex or similar at this folder and ask it to update your pipeline from your notes or email.

## Project layout

```
cli.py                    command line entry point
server.py                 local web server (Data Browser, Dashboard, Action Center)
static/                   web UI (index.html, dashboard.js, dashboard.css)
schemas/schema.sql        every table
src/career_os/
  db.py                   connection and schema init (CAREER_OS_DB override)
  seed.py                 example companies and fictional example evidence
  demo.py                 fictional demo data (python cli.py seed-demo)
  heuristics.py classify.py providers/jev.py     role classification
  services/               all business logic, one module per entity
tests/                    unittest, stdlib only
docs/GUIDE.pdf            how to use it
```

## Tests

```bash
python -m unittest discover -s tests
```

## License

MIT. See [`LICENSE`](LICENSE).
