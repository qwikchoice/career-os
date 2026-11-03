-- Career OS V0.1 schema
-- SQLite. Idempotent: every statement uses IF NOT EXISTS.
-- Provenance rule: any AI-derived value also gets a row in `claims`
-- recording source_type so it is never silently treated as verified fact.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Raw source retention (section 15/16): preserve original input forever.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type     TEXT NOT NULL,          -- 'job_posting' | 'recruiter_message' | 'note' | 'resume_file' | 'interview_notes' | 'url' | 'misc'
    content         TEXT,                   -- raw text, if pasted directly
    content_path    TEXT,                   -- path to a file on disk, if ingested from / stored as a file
    origin          TEXT,                   -- free text: where it came from (LinkedIn, email, verbal, etc.)
    content_hash    TEXT UNIQUE,            -- sha256 of normalized content, for dedup
    captured_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Companies
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    website         TEXT,
    tier            TEXT CHECK (tier IN ('A','B','C','Watchlist') OR tier IS NULL),
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    title               TEXT NOT NULL,
    location            TEXT,
    employment_type     TEXT,
    compensation_text   TEXT,
    job_url             TEXT,
    source               TEXT,              -- where the role was found
    source_posted_date  TEXT,
    captured_at         TEXT NOT NULL DEFAULT (datetime('now')),
    status              TEXT NOT NULL DEFAULT 'new',   -- new|researching|applied|... (application lifecycle lives in `applications`; this is coarse role status)
    archetype           TEXT,               -- 'A' | 'B' | 'C' | NULL
    role_tier           INTEGER CHECK (role_tier IN (1,2,3) OR role_tier IS NULL),
    fit_confidence      TEXT CHECK (fit_confidence IN ('High','Medium','Low') OR fit_confidence IS NULL),
    fit_reason          TEXT,
    primary_gap         TEXT,
    canonical_key       TEXT,               -- company+title normalized, for duplicate detection
    raw_source_id       INTEGER REFERENCES raw_sources(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    -- v2: problem-shape framework (see STRATEGY.md). All are model_inference
    -- unless a user_confirmed claim says otherwise; 'unknown' is a valid value.
    problem_shape            TEXT,   -- generalist | generalist_specialist | specialist | unknown
    rate_of_change           TEXT,   -- high | medium | low | unknown
    interconnectedness       TEXT,   -- high | medium | low | unknown
    critical_depth_lever     TEXT,   -- human-readable
    depth_lever_importance   TEXT,   -- high | medium | low | unknown
    judgment_requirement     TEXT,   -- high | medium | low | unknown
    depth_match              TEXT,   -- strong | partial | weak | unknown
    depth_match_reason       TEXT,
    missing_depth_evidence   TEXT,
    judgment_surface_expansion TEXT, -- high | medium | low | unknown
    specialist_spike_deepening TEXT, -- high | medium | low | unknown
    job_code                TEXT    -- v4: employer job/req ID (e.g. 29489); lets one company have several roles with the same title
);

CREATE INDEX IF NOT EXISTS idx_roles_company ON roles(company_id);
CREATE INDEX IF NOT EXISTS idx_roles_canonical_key ON roles(canonical_key);

-- ---------------------------------------------------------------------------
-- Applications (lifecycle tracked independently from the role)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS applications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id              INTEGER NOT NULL REFERENCES roles(id),
    status               TEXT NOT NULL DEFAULT 'planned',
    -- planned|referral_requested|referred|applied|recruiter_screen|hiring_manager|
    -- interview_loop|final_round|offer|rejected|withdrawn|closed
    date_applied         TEXT,
    channel               TEXT,
    referral_contact_id  INTEGER REFERENCES contacts(id),
    next_action           TEXT,
    next_action_date      TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_applications_role ON applications(role_id);

-- ---------------------------------------------------------------------------
-- Contacts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contacts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    company_id        INTEGER REFERENCES companies(id),
    title             TEXT,
    relationship_type TEXT,     -- recruiter|hiring_manager|referral|former_colleague|interviewer|other
    linkedin_url      TEXT,
    email             TEXT,
    strength          TEXT,     -- qualitative, user-supplied only; never inferred
    notes             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);

-- ---------------------------------------------------------------------------
-- Interactions (touchpoints with a contact)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id      INTEGER REFERENCES contacts(id),
    role_id         INTEGER REFERENCES roles(id),
    date            TEXT NOT NULL DEFAULT (datetime('now')),
    channel         TEXT,      -- linkedin|email|phone|in_person|other
    direction       TEXT,      -- inbound|outbound
    summary         TEXT NOT NULL,
    follow_up       TEXT,
    raw_source_id   INTEGER REFERENCES raw_sources(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_interactions_contact ON interactions(contact_id);
CREATE INDEX IF NOT EXISTS idx_interactions_role ON interactions(role_id);

-- ---------------------------------------------------------------------------
-- Interviews + Interview Signals
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interviews (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id                 INTEGER NOT NULL REFERENCES roles(id),
    stage                   TEXT,
    interviewer_contact_id  INTEGER REFERENCES contacts(id),
    date                    TEXT,
    notes                   TEXT,
    outcome                 TEXT,
    raw_source_id           INTEGER REFERENCES raw_sources(id),
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_interviews_role ON interviews(role_id);

CREATE TABLE IF NOT EXISTS interview_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id    INTEGER NOT NULL REFERENCES interviews(id),
    dimension       TEXT NOT NULL,   -- technical_ownership|metrics|system_design|coding|product_judgment|leadership|communication
    signal          TEXT NOT NULL CHECK (signal IN ('Strong','Mixed','Weak','Unknown')),
    root_cause      TEXT,
    repair          TEXT,
    retest          TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_signals_interview ON interview_signals(interview_id);

-- ---------------------------------------------------------------------------
-- Evidence (the career evidence database — section 12)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    company             TEXT,
    role                TEXT,
    project             TEXT,
    problem             TEXT,
    technical_context   TEXT,
    architecture        TEXT,
    scale               TEXT,
    ownership           TEXT,
    stakeholders        TEXT,
    decisions           TEXT,
    alternatives        TEXT,
    tradeoffs           TEXT,
    metrics             TEXT,     -- JSON-ish free text: metric/baseline/value. 'unknown' if not available. Never fabricated.
    thresholds          TEXT,     -- 'unknown' / 'needs_evidence' if not available
    segmentation        TEXT,
    business_impact     TEXT,
    technical_impact    TEXT,
    leadership_impact   TEXT,
    failure_modes       TEXT,
    lessons             TEXT,
    technologies        TEXT,
    archetypes          TEXT,     -- comma-separated subset of A,B,C
    critical_lever      TEXT,     -- v2: what part of the system determined success; hypothesis until user_confirmed
    source_type         TEXT NOT NULL DEFAULT 'extracted_fact'
                        CHECK (source_type IN ('raw_source','extracted_fact','model_inference','user_confirmed')),
    confidence          TEXT CHECK (confidence IN ('High','Medium','Low') OR confidence IS NULL),
    raw_source_id       INTEGER REFERENCES raw_sources(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Stories (narrative wrapper over one or more evidence rows — section 13)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    situation       TEXT,
    ownership       TEXT,
    architecture    TEXT,
    tradeoff        TEXT,
    metric          TEXT,
    threshold       TEXT,
    segmentation    TEXT,
    decision        TEXT,
    outcome         TEXT,
    lesson          TEXT,
    short_version   TEXT,   -- ~90-second interview version
    deep_version    TEXT,   -- deep technical version
    critical_lever  TEXT,   -- v2: other SYSTEM->LEVER->MECHANISM->DECISION->OUTCOME slots derive from situation/architecture/decision/outcome
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS story_evidence (
    story_id    INTEGER NOT NULL REFERENCES stories(id),
    evidence_id INTEGER NOT NULL REFERENCES evidence(id),
    PRIMARY KEY (story_id, evidence_id)
);

-- ---------------------------------------------------------------------------
-- Skills + role/evidence linkage (section 14)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    category    TEXT CHECK (category IN ('must-have','frequently requested','differentiating','emerging','low-value buzzword') OR category IS NULL),
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS role_skills (
    role_id             INTEGER NOT NULL REFERENCES roles(id),
    skill_id            INTEGER NOT NULL REFERENCES skills(id),
    requirement_level   TEXT,   -- 'required' | 'preferred' | 'mentioned'
    PRIMARY KEY (role_id, skill_id)
);

CREATE TABLE IF NOT EXISTS evidence_skills (
    evidence_id INTEGER NOT NULL REFERENCES evidence(id),
    skill_id    INTEGER NOT NULL REFERENCES skills(id),
    PRIMARY KEY (evidence_id, skill_id)
);

-- ---------------------------------------------------------------------------
-- Depth spikes (v2): durable specialist strengths. Strength is DERIVED from
-- linked evidence rows (services/problem_shape.spike_strength), never stored.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS depth_spikes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,   -- 'search' | 'eval' | 'platform'
    name        TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS evidence_spikes (
    evidence_id INTEGER NOT NULL REFERENCES evidence(id),
    spike_id    INTEGER NOT NULL REFERENCES depth_spikes(id),
    PRIMARY KEY (evidence_id, spike_id)
);

-- ---------------------------------------------------------------------------
-- Claims: generic provenance ledger (section 15) for any AI-derived
-- statement that isn't already a typed, explicitly-labeled column.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claims (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_text          TEXT NOT NULL,
    subject_type        TEXT NOT NULL,     -- 'role' | 'evidence' | 'contact' | 'company' | ...
    subject_id          INTEGER NOT NULL,
    source_type         TEXT NOT NULL CHECK (source_type IN ('raw_source','extracted_fact','model_inference','user_confirmed')),
    source_path         TEXT,
    raw_source_id       INTEGER REFERENCES raw_sources(id),
    verification_status TEXT,              -- 'source_supported' | 'unverified' | 'user_confirmed' | 'needs_evidence'
    confidence          TEXT CHECK (confidence IN ('High','Medium','Low') OR confidence IS NULL),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_claims_subject ON claims(subject_type, subject_id);

-- ---------------------------------------------------------------------------
-- Duplicate flags (section 17: flag, never silently delete)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS duplicates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,
    entity_id_a     INTEGER NOT NULL,
    entity_id_b     INTEGER NOT NULL,
    reason          TEXT,
    status          TEXT NOT NULL DEFAULT 'flagged',  -- flagged|related|merged|dismissed
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Notes inbox: free text that may or may not link cleanly to an entity.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notes_inbox (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text            TEXT NOT NULL,
    captured_at         TEXT NOT NULL DEFAULT (datetime('now')),
    linked_entity_type  TEXT,
    linked_entity_id    INTEGER,
    linked_confidence   TEXT CHECK (linked_confidence IN ('High','Medium','Low') OR linked_confidence IS NULL),
    raw_source_id       INTEGER REFERENCES raw_sources(id),
    processed           INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- v3: Referrals. A lightweight link Contact -> Company -> Role -> Application.
-- company/role are both optional ("X can refer me at Google" has no role yet);
-- role_hint preserves a role description that matches no tracked role (yet).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS referrals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id      INTEGER NOT NULL REFERENCES contacts(id),
    company_id      INTEGER REFERENCES companies(id),
    role_id         INTEGER REFERENCES roles(id),
    role_hint       TEXT,
    status          TEXT NOT NULL DEFAULT 'offered'
                    CHECK (status IN ('offered','to_request','requested','submitted','declined','expired','completed','unknown')),
    date_offered    TEXT,
    date_requested  TEXT,
    date_submitted  TEXT,
    follow_up_date  TEXT,
    source          TEXT,          -- where the offer came from (LinkedIn, email, ...)
    notes           TEXT,
    raw_source_id   INTEGER REFERENCES raw_sources(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_referrals_contact ON referrals(contact_id);
CREATE INDEX IF NOT EXISTS idx_referrals_company ON referrals(company_id);
CREATE INDEX IF NOT EXISTS idx_referrals_role ON referrals(role_id);

-- ---------------------------------------------------------------------------
-- v3: Job sources. roles.source holds the DISCOVERY source name (matched here
-- case-insensitively); applications.channel is the separate APPLICATION CHANNEL.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    source_type     TEXT NOT NULL DEFAULT 'other',  -- company_careers|linkedin|aggregator|remote_board|startup_board|government|recruiter|referral|community|other
    url             TEXT,
    notes           TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    priority        TEXT CHECK (priority IN ('High','Medium','Low') OR priority IS NULL),
    priority_basis  TEXT,           -- seed_hypothesis | user_stated
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- v3: Learning resources. One generic table for every resource type.
-- category is validated in code (services/learning.CATEGORIES) so adding a
-- category never needs a schema change.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learning_resources (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    url_or_path       TEXT,
    provider          TEXT,
    category          TEXT,
    topics            TEXT,         -- comma-separated canonical topics
    format            TEXT,
    estimated_minutes INTEGER,      -- NULL = unknown (never guessed)
    depth             TEXT,         -- intro | working | deep | NULL
    notes             TEXT,
    source            TEXT,         -- how it was added
    usefulness        TEXT NOT NULL DEFAULT 'unknown'
                      CHECK (usefulness IN ('useful','neutral','not_useful','unknown')),
    raw_source_id     INTEGER REFERENCES raw_sources(id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Application questions and answers (one row per question asked on an application,
-- plus the cover letter). Stored so an answer can be reused or compared across roles.
-- source_file points at the saved draft; answer holds the text actually used.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS application_answers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id       INTEGER NOT NULL REFERENCES roles(id),
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL,
    source_file   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_answers_role ON application_answers(role_id);

-- ---------------------------------------------------------------------------
-- Schema version marker (simple migration tracking for V0.1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', '1');
