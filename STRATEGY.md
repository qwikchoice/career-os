# Career OS Strategy Model: Generalist + Specialist Spike

Durable guidance. Code in `services/problem_shape.py`, `services/interview_prep.py` and `heuristics.py` implements it; this file is the reasoning. Inspired by David Epstein's *Range*.

## The four principles

> **Broad operating range is valuable when environments are changing and interconnected. Specialist depth is valuable where one leverage point materially determines outcomes. The default strategy is to operate broadly while maintaining visible depth in a few chosen spikes (the examples here are Search/Retrieval, AI Evaluation and Production AI Platforms; change them in `services/problem_shape.py`). Prefer roles where systems judgment matters and at least one of these depth spikes creates differentiated credibility.**

- **Interview:** SYSTEM -> LEVER -> MECHANISM -> DECISION -> OUTCOME
- **Learning:** Learn broadly enough to understand the system. Go deep where leverage is high.
- **Career:** The strongest career moves expand judgment surface while deepening at least one durable specialist spike.

AI tools (ChatGPT, Claude, LangChain, MCP, agent frameworks) are not a moat; they diffuse. The durable differentiator is judgment using AI: the actual constraint, which failure mode matters economically, which metric gates deployment, which tradeoff is reversible, where the model is likely wrong, where humans stay in the loop.

## Role problem shape

`problem_shape`: `generalist` | `generalist_specialist` (preferred) | `specialist` | `unknown`. Shown as Generalist / Generalist + Specialist / Specialist (`G` / `G+S` / `S` in tables).

Assessed from the JD, qualitatively, no formula:

| Field | Question | Values |
|---|---|---|
| `rate_of_change` | How fast do tech/market/customer assumptions move? | high/medium/low/unknown |
| `interconnectedness` | How many systems must be understood together? | same |
| `critical_depth_lever` | Where would deeper expertise materially change the result? | text |
| `depth_lever_importance` | How dominant is that lever? | same |
| `judgment_requirement` | How much is success framing ambiguity and cross-domain tradeoffs? | same |

`unknown` is correct whenever the JD gives too little signal. A title alone never produces a classification.

Shape reading: **Generalist** = high change, high interconnection, no dominant lever. **Generalist + Specialist** = interconnected, plus one lever where real depth is the price of credibility. **Specialist** = narrow, one technical lever dominates (CUDA, compilers, silicon, low-level training).

Risks to keep visible: a *pure generalist* role can reduce to meetings, coordination and dependency tracking; a *pure specialist* role puts you against people with years in one narrow domain.

## Depth spikes (working hypotheses)

| Code | Spike | Marker field that must be known before it can read "strong" |
|---|---|---|
| `search` | Search / Retrieval / Relevance | `metrics` |
| `eval` | AI Evaluation / Quality | `thresholds` |
| `platform` | Production AI / Platform | `failure_modes` |

Spike strength is **derived, never stored**: strong = 2+ evidence rows with known metrics and ownership AND the marker field known on at least one; partial = linked evidence exists; weak = none. Evidence-to-spike links and per-story `critical_lever` values are seeded as `model_inference` hypotheses (see `claims`). They become verified only when the user confirms them.

`depth_match` (strong/partial/weak/unknown) compares a role's lever to spike strength. It is **never inferred from resume keywords**, only from linked Career Evidence.

## Career compounding

- `judgment_surface_expansion`: does the role widen the product/engineering/model/data/customer/economics/operations surface you operate across?
- `specialist_spike_deepening`: does it deepen one durable spike?

Prefer roles that score on both. Do not optimize purely for title, brand, short-term compensation, number of technologies, or generic scope unless they materially improve long-term compounding. A common trajectory is Principal -> Director -> Senior Director, where value is: understand system -> identify leverage -> deploy specialists -> reconcile tradeoffs -> decide -> allocate -> own outcome.

## Interview repair

Common failure: broad system explanation + insufficient depth + unclear personal decision. Diagnosis: *Breadth demonstrated; specialist credibility insufficiently visible.* Repair: (1) name the critical lever, (2) go one layer deeper technically, (3) metric/threshold/segmentation, (4) your personal decision (not "we"), (5) outcome and lesson. `career diagnose` and `career story-frame` apply this.

## Learning decision check

Before recommending substantial learning, ask: (1) what hiring problem does it solve? (2) generalist literacy or specialist depth? (3) does it map to a current target role? (4) does it strengthen a durable spike? (5) will it matter within ~6 weeks? (6) is it higher priority than Pipeline, Conversion or Proof work? If not, backlog. Generalist literacy = enough to ask good questions and spot bad assumptions (GPU capacity, batching, inference, latency, serving economics). Specialist depth is for search/retrieval, evaluation and production AI systems.

## Proof project

Stays the single AI Quality Gate / EvalOps concept: Dataset -> Retrieval -> LLM/Agent -> Evaluation -> Observability -> Release. The lever is the release decision: how do we know a new version is better and safe enough? Show metrics, segmentation, thresholds, regression analysis, failure analysis, tradeoffs and a launch/no-launch call. No technology-demo projects. This framework does not add a second one.

## Positioning (configurable, not auto-applied)

> [Your title] operating across product, platform and engineering boundaries, with deep experience in [your spikes].

Avoid unstructured lists ("AI / ML / Product / TPM / Cloud / Search leader"). Resumes and LinkedIn are not rewritten automatically.

## Provenance

The JD is the source; every shape field is a `model_inference` recorded in `claims`. `career shape-set <role> <field> <value>` writes a `user_confirmed` claim, which later re-analysis never overwrites.

## Weekly review and analytics

`career review` shows a Generalist-Specialist section only when it can change a decision (counts by shape, PMO-drift warning). Funnel claims such as "G+S roles convert better than specialist roles" are not made until real pipeline data supports them.

## Not built (on purpose)

Numeric scoring, ML models, dashboards, a second database, ontology/knowledge-graph, new dependencies, automatic resume/LinkedIn rewrites, a second proof project.
