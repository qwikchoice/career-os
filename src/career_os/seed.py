"""Starter data: an example company portfolio plus EXAMPLE career-evidence rows.

Everything below is fictional sample data (made-up companies, projects and
numbers) so a new user can see how evidence rows look. Replace it with your own:
edit COMPANY_PORTFOLIO and _EVIDENCE_SEEDS, or add your own rows later with the
`update` command and the Data Browser. If a `profile.md` exists next to this
project's `cli.py`, it is stored as a raw source for provenance (it is gitignored).

Idempotent: safe to run more than once (companies/skills are get-or-create;
evidence rows are only inserted if not already present for the same
company+project combination).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from career_os.services import companies as companies_svc
from career_os.services import evidence as evidence_svc
from career_os.services import sources as sources_svc

CAREER_OS_ROOT = Path(__file__).resolve().parents[2]

# Example target-company tiers (A = top targets). Edit to your own list.
COMPANY_PORTFOLIO = {
    "A": [
        "OpenAI", "Google", "Amazon", "Microsoft", "Meta", "Apple",
        "Databricks", "Anthropic", "NVIDIA", "LinkedIn",
    ],
    "B": [
        "Salesforce", "ServiceNow", "Snowflake", "Adobe", "Cisco",
        "Uber", "Airbnb", "Intuit",
    ],
    "C": [
        "Scale AI", "Perplexity", "Cohere", "Palantir", "Oracle",
    ],
    "Watchlist": [
        "Stripe", "Block", "Pinterest", "Spotify", "DoorDash", "Atlassian",
    ],
}

# EXAMPLE EVIDENCE: fictional companies and numbers. Replace with your own work.
_EVIDENCE_SEEDS = [
    dict(
        company="Northwind Commerce", role="Senior Technical Program Manager", project="Marketplace Search Relevance",
        problem="Marketplace search relevance and engagement were lagging; filters and discovery were underbuilt.",
        architecture="Learned-ranking filters and personalized recommendations layered on the existing search ranking stack.",
        ownership="Owned the multi-year roadmap; defined the A/B testing strategy, feature sequencing and priorities across engineering and data science.",
        decisions="Drove ML feature launch sequencing and prioritization across engineering and data-science stakeholders.",
        metrics="+12% search click-through; +6 point NDCG improvement (example numbers)",
        thresholds="needs_evidence", segmentation="needs_evidence",
        business_impact="Lift in marketplace engagement tied to search relevance work.",
        technical_impact="NDCG improvement on search ranking quality.",
        technologies="Search ranking, A/B testing, recommendation systems",
        archetypes="A,B", skills=[
            "AI/ML Product Roadmaps", "Search Ranking", "Relevance", "NDCG",
            "A/B Testing", "Personalization", "Recommendation Systems",
        ],
    ),
    dict(
        company="Contoso Retail", role="Senior Technical Program Manager, Search", project="Multi-country Search Optimization",
        problem="Search data quality and relevance gaps across international markets limited revenue.",
        architecture="Annotation and audit workflows with several international vendor teams to validate and improve search model quality.",
        ownership="Owned peak-event readiness and the risk plan for critical search services; built the risk model and playbook.",
        decisions="Prioritized data-quality fixes by country; structured a cross-team readiness plan for peak traffic.",
        metrics="$20M incremental search revenue across 12 countries (example numbers)",
        thresholds="needs_evidence", segmentation="By country (12 markets)",
        business_impact="Incremental search revenue.",
        technical_impact="Improved search model quality and market coverage via an annotation and audit pipeline.",
        technologies="Search relevance, annotation/HITL, risk modeling",
        archetypes="A,C", skills=[
            "Search Ranking", "Data Quality", "Risk Mitigation",
            "Internationalization", "Annotation", "HITL",
        ],
    ),
    dict(
        company="Contoso Retail", role="Senior Technical Program Manager, Voice", project="Voice Assistant International Launch",
        problem="A voice shopping feature needed a privacy-compliant international launch bar across several markets.",
        architecture="Defined the localization roadmap, requirements and privacy controls as go-live criteria for international expansion.",
        ownership="Defined the internationalization roadmap; aligned cross-functional teams (engineering, product, legal, data science, privacy, QA) to the launch bar.",
        decisions="Set the go-live criteria and privacy-control bar that gated launch per market.",
        metrics="Launched in 5 countries (example numbers)",
        thresholds="needs_evidence", segmentation="By country (5 markets)",
        business_impact="International expansion of a voice-AI shopping feature.",
        technical_impact="Privacy-by-design launch framework reused as a go-live gate.",
        technologies="Voice AI, privacy/compliance, i18n",
        archetypes="A,B", skills=[
            "Voice AI", "Internationalization", "Cross-functional Leadership",
            "Stakeholder Management",
        ],
    ),
    dict(
        company="Fabrikam Cloud", role="Senior Technical Product Manager", project="Regional Capacity Launches",
        problem="Pricing and capacity strategy was needed for several new cloud regions.",
        architecture="Pricing proposals, demand forecasts and product specifications prepared for executive review.",
        ownership="Owned product strategy and pricing for new region launches; partnered with marketing and finance on go-to-market and pricing proposals.",
        decisions="Secured executive approval on capacity and pricing proposals.",
        metrics="6 region launches (example numbers)",
        thresholds="needs_evidence", segmentation="needs_evidence",
        business_impact="Enabled regional expansion with approved pricing.",
        technical_impact="needs_evidence",
        technologies="Cloud infrastructure, pricing strategy",
        archetypes="A", skills=[
            "Cloud Infrastructure", "Go-to-Market", "Pricing Strategy",
            "Executive Reporting",
        ],
    ),
    dict(
        company="Lumen Labs", role="Technical Program Manager", project="Enterprise RAG Platform",
        problem="A production RAG platform needed a defined evaluation bar before scaling use cases.",
        architecture="Retrieval strategy, chunking, embedding and reranking; prompt design and evaluation loops owned with engineering.",
        ownership="Owned vision, roadmap and the evaluation loop end to end: set accuracy, latency and adoption thresholds.",
        decisions="Drove ship decisions with engineering on when a response met the quality bar.",
        metrics="Accuracy, latency and adoption tracked per release (baseline figures: needs_evidence)",
        thresholds="needs_evidence", segmentation="needs_evidence",
        business_impact="needs_evidence",
        technical_impact="Guided the engineering team to a conference submission on agentic AI system design.",
        technologies="RAG, LLM, agentic AI, prompt engineering",
        archetypes="B,C,A", skills=[
            "RAG", "LLM", "Agentic AI", "Prompt Engineering", "ML Evaluation",
            "Golden Dataset",
        ],
    ),
    dict(
        company="Tailspin Apps", role="Technical Program Manager", project="Release Process and Personalization",
        problem="A distributed engineering team needed a release process and a personalization layer built from scratch.",
        architecture="A generative-AI surfacing layer over an enriched venue dataset; release process with branching, versioning and a deployment cadence.",
        ownership="Built the release management process from scratch; owned the roadmap for the personalization feature.",
        decisions="Set accuracy checks and manual-review thresholds deciding which records reached production.",
        metrics="10 releases per quarter with no critical outages; unified sign-in lifted signup conversion 15% (example numbers)",
        thresholds="needs_evidence", segmentation="needs_evidence",
        business_impact="Lift in new-user signup conversion via unified sign-in.",
        technical_impact="A large record set enriched and validated for production discovery.",
        technologies="GenAI, release management, data pipelines",
        archetypes="A,B", skills=[
            "Release Management", "Branching Strategy", "Program Scheduling",
            "Personalization", "Cross-functional Leadership", "A/B Testing",
        ],
    ),
    dict(
        company="Adatum Systems", role="Release Manager", project="Account Release Management",
        problem="Many concurrent workstreams needed a predictable release cadence.",
        architecture="Managed weekly and critical releases across the workstreams.",
        ownership="Managed release cadence and cross-workstream coordination.",
        decisions="needs_evidence",
        metrics="40 weekly + 30 critical releases across 12 workstreams (example numbers)",
        thresholds="needs_evidence", segmentation="By workstream (12)",
        business_impact="Improved operational efficiency.",
        technical_impact="needs_evidence",
        technologies="Release management",
        archetypes="A", skills=["Release Management", "Program Scheduling"],
    ),
]


def seed_companies(conn: sqlite3.Connection) -> int:
    count = 0
    for tier, names in COMPANY_PORTFOLIO.items():
        for name in names:
            companies_svc.get_or_create_company(conn, name, tier=tier)
            count += 1
    return count


def seed_evidence(conn: sqlite3.Connection) -> int:
    profile_path = CAREER_OS_ROOT / "profile.md"   # optional, your own, gitignored
    raw_source_id = None
    if profile_path.exists():
        src = sources_svc.create_raw_source(
            conn,
            source_type="misc",
            content_path=str(profile_path),
            origin="profile.md (seed import)",
        )
        raw_source_id = src["id"]

    inserted = 0
    for seed_item in _EVIDENCE_SEEDS:
        item = dict(seed_item)  # copy: pop() below must not mutate the module-level seed list
        existing = conn.execute(
            "SELECT id FROM evidence WHERE company = ? AND project = ?",
            (item["company"], item["project"]),
        ).fetchone()
        if existing:
            continue
        skill_names = item.pop("skills")
        evidence_svc.add_evidence(
            conn,
            **item,
            source_type="extracted_fact",
            confidence="Medium",
            raw_source_id=raw_source_id,
            skill_names=skill_names,
        )
        inserted += 1
    return inserted


def run_seed(conn: sqlite3.Connection) -> dict:
    from career_os.services import problem_shape as shape_svc

    result = {
        "companies_seeded": seed_companies(conn),
        "evidence_seeded": seed_evidence(conn),
    }
    result.update(shape_svc.seed_spike_links(conn))
    from career_os.services import job_sources as job_sources_svc
    result["job_sources_seeded"] = job_sources_svc.seed_job_sources(conn)
    return result
