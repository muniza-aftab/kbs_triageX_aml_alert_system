# TriageX

### Intelligent AML Alert Triage & Risk Prioritization

**Transforming complex alerts into focused investigative action.**

A knowledge-based system that triages anti-money-laundering alerts and **knows when to refuse to
decide**.

An alert arrives: a customer, a window of transactions, counterparty details and KYC context.
The system returns one of five dispositions, with its full reasoning and, where relevant, the
cheapest evidence that would change its mind.

```
$ triagex run ALT-3001 --explain

ALT-3001: REQUEST_EVIDENCE

A typology is supported but a nameable piece of evidence is missing. Asking is cheaper
than escalating on an incomplete picture, and an escalation made after the answer arrives
carries a far stronger narrative.

Patterns matched:
  - structuring (confidence +0.86)

Assessment:
  typology_support       strong
  composite_risk         high
  evidence_sufficiency   partial
  conflict_state         none
  scope_state            in_scope

Reasoning:
  - threshold proximity is high (confidence +1.00)
    The largest credit sits between 80% and 100% of the GBP 3,000 review threshold.
    Amounts cluster just under a threshold when the threshold is known and being
    avoided.  [IND-PROX-01]
  ...
```

> **Illustrative system on synthetic data.** Thresholds, jurisdictions and screening results are
> invented; jurisdictions are deliberately fictional. Nothing here may be used to decide anything
> about a real person.

---

## The five outcomes

| | meaning |
|---|---|
| `clear` | Close the alert, no further action |
| `monitor` | Close, but place the customer under enhanced ongoing monitoring |
| `request_evidence` | Ask for specific evidence before deciding, and the system works out *which* evidence |
| `refer_to_investigation` | Escalate to a human investigator, possibly a Suspicious Activity Report |
| `refuse_to_decide` | The knowledge base cannot form a belief about this case, and says why |

## The idea

Most rule engines are obliged to produce an answer. This one models **two different reasons for
handing a case to a human**, and keeps them strictly apart:

| | meaning |
|---|---|
| `refer_to_investigation` | **An authority boundary.** The rules fired cleanly and the system knows exactly what the case is, but only the MLRO can lawfully authorise a report. Confident, and deferring. |
| `refuse_to_decide` | **An epistemic boundary.** The case falls outside the knowledge base's scope, or the rules conflict irreconcilably, or a mandatory premise was never established. No belief can be formed at all. |

That distinction is not decorative. UK law makes the test for suspicion *objective*, under
[POCA 2002 s.330](https://www.legislation.gov.uk/ukpga/2002/29/section/330) the offence is
committed where someone had **reasonable grounds** to suspect, whether or not they did. So a
system that quietly resolves its own uncertainty into a clean `clear` is manufacturing legal
exposure. Saying *"the evidence here is contradictory and no view can be formed"* is the honest
output, not a weakness.

**And it measurably pays.** Forcing the system to answer every case raises risk-weighted cost from
0.476 to 1.648 per case. A [flat scorer](experiments/flat_baseline.py) built from the same signals
and thresholds costs **3.498** and misses **21 referrals against 2**.

---

## The website

A plain HTML, CSS and JavaScript front end in [`frontend/`](frontend/): no framework, no build
step, and no third-party requests, with fonts served from the site itself. It is written for the
person who has to act on a decision rather than for an engineer. It talks to the API in
[`backend/`](backend/), which renders through a [plain-language layer](src/triagex/plain.py) that
translates `typology_support(strong)` into "Pattern strength: Strong" without ever dressing a
certainty factor up as a percentage.

| page | what it does |
|---|---|
| Home | What the system does, the five decisions, and why declining is a feature |
| Run assessment | A guided four-step form with validation, then a review step and a live assessment |
| Examples | All 24 cases, filterable by outcome and searchable, each with its own result page |
| History | Every assessment from this session, kept in the browser, reopenable and exportable |
| About | The staged reasoning, live rule and fact counts, sources, limitations and terms |

Every result, whether a new assessment, a worked example or a history entry, is shown in the same
dashboard: the recommended action, a plain-language explanation, the intermediate assessment, the
patterns detected, the reasoning trace grouped by stage, why each other decision was ruled out, and
the rules that fired. Any result, or a whole session, can be downloaded as a self-contained HTML
report, saved as a PDF, or exported as JSON. Light and dark themes follow the system setting and can
be switched by hand.

```bash
pip install -e ".[web]"
uvicorn backend.index:app --reload    # http://127.0.0.1:8000
```

### Deploying the website

The two halves are separate folders and deploy independently:

```
frontend/   static HTML, CSS, JS   ->  Vercel
backend/    the ASGI API           ->  Render
```

**Vercel, the front end.** Set the project's root to the repository and Vercel reads
[`vercel.json`](vercel.json): no build step, `frontend/` is served as-is, with long-lived caching for the
fonts only and `X-Frame-Options`, `nosniff` and a referrer policy on everything.
[`.vercelignore`](.vercelignore) keeps the Python out of the deployment entirely.

**Render, the API.** [`render.yaml`](render.yaml) is a blueprint. Render installs the package,
runs `uvicorn backend.index:app` and health-checks `/api/health`.

**Then connect them.** [`frontend/config.js`](frontend/config.js) chooses the API address itself:
same origin when the site is served locally, the Render service everywhere else. If the Render
service is not called `triagex-api`, change the one URL in that file. Optionally set
`ALLOWED_ORIGINS` on the Render service to your Vercel domain to close CORS down. The default is
permissive because the API holds no state and exposes no user data, but that is not a default to
keep in a system that does.

The Render free tier sleeps when idle, so the first request to a cold service takes a few seconds.
The front end says so rather than looking broken.

`requirements.txt` covers the API only. **The core package still has no runtime dependencies**: the engine, rule base, search and explanation facility all run on the standard library alone, and
a test enforces that nothing from the web layer creeps into it.

---

## Quickstart

Python 3.11+. **The core has no runtime dependencies.**

```bash
pip install -e .

triagex cases                      # the 24-case library
triagex run ALT-3001 --explain     # assess one case, with reasoning
triagex run ALT-3001 --why-not clear
triagex evidence ALT-3001          # what would change the decision
triagex graph ALT-4006             # counterparty network, circular flows
triagex dossier all                # self-contained HTML, one file per alert
triagex audit                      # verify the rule base
triagex consult                    # interactive assessment
```

Development:

```bash
pip install -e ".[dev]"
pytest                              # 401 tests
ruff check src tests experiments backend
mypy                                # --strict, clean

python experiments/audit_rules.py       # rule-base verification, exits 1 on error
python experiments/evaluate.py          # ablations and the risk-coverage curve
python experiments/search_benchmark.py  # six search strategies compared
```

---

## Architecture

Six layers. Each may read only from specified layers below it, enforced when a rule is
constructed, *not* merely "somewhere lower", because that still permits a disposition derived
straight from raw data, which is the flat lookup table the layering exists to prevent.

```
  L5  DISPOSITION      decision list, first match wins     reads L3, L4
        ^
  L4  POSTURE          composite risk; prohibitions        reads L1-L3
        ^
  L3  ASSESSMENT       evidence sufficiency, scope,        reads L1, L2
                       mandatory escalation
        ^
  L2  TYPOLOGIES       hypotheses with certainty factors   reads L1 only
        ^
  L1  INDICATORS       named observations                  reads L0 only
        ^
  L0  MEASUREMENTS     arithmetic, temporal, graph
```

A worked chain, five levels deep:

```
L0  14 cash deposits of GBP 2,400 over 6 days; account opened 21 days ago; no source-of-funds doc
L1  deposit_frequency(extreme), threshold_proximity(high), aggregation_gap(present),
    account_immaturity(true), documentation_gap(source_of_funds)
L2  typology(structuring, cf +0.86), typology(mule_account, cf +0.45)
L3  typology_support(strong), evidence_sufficiency(partial), scope_state(in_scope)
L4  composite_risk(high)
L5  request_evidence, ask for source-of-funds documentation (effort 5)
```

**103 rules**: 48 indicators, 27 typologies, 13 assessment, 15 posture and veto, plus a 10-stage
decision list. Every rule carries a source and a human-readable rationale, both enforced by tests.
56% are tagged `reconstructed`: the shape comes from published typologies and the numbers were
set for this project. The documentation says so rather than implying authority it lacks.

### What is built here rather than imported

- **The inference engine.** Agenda-based forward chaining with explicit conflict resolution
  (specificity → priority → recency → deterministic tiebreak), fully instrumented.
- **A unifying backward chainer**, for goal-directed and hypothetical queries.
- **Six search algorithms**: BFS, DFS, iterative deepening, uniform cost, greedy, A\* with a
  landmark heuristic, against one interface so they can be compared on identical problems.
- **Graph search** over the counterparty network, cross-validated against `networkx` in tests.
- **A rule-base verifier** for redundancy, subsumption, unfirable rules, circularity, dangling
  premises, unreachable values, conflict and dead rules.

`networkx` appears only in tests, as an independent oracle. An implementation verified only by
whoever wrote it is verified by nobody.

---

## Three things worth a closer look

**Unknown is not false, and it is enforced.** The fact base is three-valued, and predicates
registered as *mandatory* cannot be queried under negation-as-failure, the engine raises. A case
file that never mentions sanctions screening produces `not_checked`, not `none`, so the omission
becomes a missing premise and the system refuses. `Truth.UNKNOWN` also raises on boolean coercion,
so three-valued logic cannot silently decay into two-valued.

**The contrastive search output is a product feature.** "What would have to change" is a real
search over evidence-acquisition states, with step costs from analyst effort and how intrusive the
request is. Its answer *is* the `request_evidence` message, and it reports honestly when there is
no answer, because no amount of evidence gives this system a model of cryptoasset flows.

**The explanation facility answers "why not".** The hard question is not why an outcome was
reached but why another was not, and that cannot come from a proof tree because the answer is
about what is *absent*:

```
clear was not reached because:
  - composite_risk is high, not low
  - typology_support is strong, not none
  - evidence_sufficiency is partial, not sufficient
  - disposition_blocked is recorded as clear, and must not be
  - a prohibition forbids it: clear is blocked
```

---

## Results

Measured by `python experiments/evaluate.py` on 500 generated cases. Full write-up in
[docs/07-evaluation.md](docs/07-evaluation.md).

| configuration | cost/case | coverage | sel. acc | missed referrals |
|---|---|---|---|---|
| **full system** | **0.476** | 88.8% | 97.9% | 2 |
| forced to answer | 1.648 | 100% | 86.5% | 2 |
| no veto layer | 0.476 | 88.8% | 97.9% | 2 |
| bayesian certainty | 0.476 | 88.8% | 97.9% | 2 |
| no meta layer | 1.660 | 2.4% | 100% | 0 |
| flat scorer | 3.498 | 100% | 46.6% | 21 |

Accuracy is not the headline. Clearing a case that should have been referred lets laundering
through; referring a clean customer consumes an investigator and can freeze an innocent person's
account. The primary measure is risk-weighted cost against an asymmetric matrix.

**Three results that contradict what this project assumed:**

- **The veto layer changes no outcome.** Every prohibition is redundant with a guard the
  disposition stage already carries. It is kept for defence-in-depth and because it makes
  prohibitions visible in explanations, but it is reported as redundant rather than credited with
  work it does not do.
- **The Bayesian arithmetic changes no decision.** Swapping MYCIN combination for odds
  multiplication moved individual certainties and changed nothing downstream: the discrete band
  boundaries absorb it. On this rule base, the transparency of certainty factors is free.
- **Confidence-based abstention does not pay.** Sweeping a margin threshold makes things
  monotonically worse. What earns the 3.5× is *categorical* abstention, out of scope, premise
  missing, where the system can say precisely **what** it does not know. Knowing only **that**
  you are unsure turns out to be worth nothing.

---

## Documentation

| | |
|---|---|
| [00 Overview, without the jargon](docs/00-overview.md) | The whole system explained for a non-engineer |
| [01 Domain primer](docs/01-domain-primer.md) | AML triage for someone who has never seen it |
| [02 Knowledge acquisition](docs/02-knowledge-acquisition.md) | Sources, method, provenance policy |
| [03 Knowledge model](docs/03-knowledge-model.md) | The formal spec the code is built against |
| [04 Inference](docs/04-inference.md) | Chaining, conflict resolution, certainty arithmetic |
| [05 Abstention](docs/05-abstention.md) | The two boundaries, and how each is detected |
| [06 Search](docs/06-search.md) | Contrastive and network search, with measurements |
| [07 Evaluation](docs/07-evaluation.md) | Cost model, ablations, risk-coverage curve |
| [08 Design decisions](docs/08-design-decisions.md) | Why rules not ML, why no Prolog, why a custom engine |
| [09 Limitations](docs/09-limitations.md) | What this does not do, and would not do |
| [10 Deployment](docs/10-deployment.md) | How the two halves are hosted, and how they are joined |
| [Refinement log](docs/refinement-log.md) | Every change to the knowledge base, and what forced it |

The [refinement log](docs/refinement-log.md) is the one to read if you only read one. It records
what was wrong and what caught it, including a domestic PEP being silently recorded as a foreign
one, which no test would have found, and a bug in the evaluation's own cost model that made
abstention look worthless.

---

## Licence

[MIT](LICENSE).
# kbs_triageX_aml_alert_system
