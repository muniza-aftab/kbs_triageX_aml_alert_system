# 08. Design Decisions

Each entry records what was chosen, what was rejected, and what would change the answer. Where a
decision was later measured, the measurement is here too, including the two that turned out not
to matter.

---

## Rules rather than machine learning

**Chosen:** a symbolic rule base with explicit certainty factors.

**Rejected:** a trained classifier over the same features.

**Why.** Three reasons, in descending order of how much they actually weigh:

1. **There is no training data.** Calibrating a model needs outcome labels (which alerts turned
   out to be laundering), and those come from filed reports and prosecutions that no public
   dataset provides. A model trained on synthetic labels learns the generator, not the domain. A rule base
   trained on nothing is at least honest about where its knowledge came from.
2. **The output has to be defensible to a third party.** A Suspicious Activity Report may have to
   survive scrutiny, and the FCA's
   [Financial Crime Guide](https://handbook.fca.org.uk/handbook/fcg1) extended into AI assurance
   expectations in its April 2025 update. "The model scored it 0.83" is not a reason.
3. **Abstention is expressible.** A classifier's output space is its label set; adding "this
   cannot be judged" means bolting a confidence threshold onto the outside, which is exactly the mechanism the
   evaluation found does **not** work (see [07](07-evaluation.md) §3).

**What would change this.** Real outcome data would make a hybrid genuinely attractive: learned
detection feeding symbolic adjudication, which is roughly where the industry is heading. The
argument here is about this project's circumstances, not about rules being better than learning.

---

## No Prolog

**Chosen:** hand-written unification and backward chaining in Python.

**Rejected:** SWI-Prolog for the declarative layer.

**Why.** Prolog is the obvious fit and was declined on two grounds. It would make a reader
install a second toolchain before anything runs, and the capability it demonstrates is better
demonstrated by building it: a hand-written unifying backward chainer shows more than a call to a
Prolog interpreter does. The core keeps its zero-dependency property as a result.

**The honest cost.** [engine/backward.py](../src/triagex/engine/backward.py) is perhaps 150 lines
doing a fraction of what SWI-Prolog does, without indexing, tabling or cut. It has two restrictions
a real logic programming system would not: goal subjects must be ground, and only predicates some
rule concludes are derivable. Both are enforced rather than left as surprises.

---

## A custom inference engine rather than CLIPS or experta

**Chosen:** an agenda-based forward chainer written for this project.

**Rejected:** CLIPS via a binding, or `experta`.

**Why.** Instrumentation. The engine records every activation, including the ones that matched
and lost, with the reason they lost; the explanation facility is built entirely on that record. A
library engine would have needed the same information extracted through whatever hooks it happened
to expose. `experta` is also unmaintained on modern Python, which settles it.

**The honest cost.** Condition matching is a linear scan of working memory, so the engine is
O(facts × conditions) per cycle where a RETE network would be far better. It does not matter at
this scale (assessments take single-digit milliseconds) and it would matter immediately at
production volumes.

---

## Certainty factors rather than probabilities, and the measurement that followed

**Chosen:** MYCIN-style certainty factors with weakest-link conjunction.

**Rejected:** a Bayesian network.

**Why.** A human can read `strength=0.70` off a rule, understand where it came from, and argue with
it. Certainty factors are not probabilistically sound: the combination function is not derivable
from probability theory, and it assumes an independence the rule base does not have, since several
indicators derive from the same transactions. The claim was that the transparency is worth the
unsoundness.

**Measured.** [The ablation](07-evaluation.md) swapped in odds-multiplication combination and
product conjunction. Individual certainties moved: 0.70 with 0.50 becomes 0.889 rather than 0.850.
**No decision changed.** The discrete band boundaries absorb the difference, so on this rule base
the transparency costs nothing.

**What would change this.** Tighter bands or longer inference chains would likely diverge, and a
rule base where certainties feed a continuous output rather than a banded one certainly would. The
result is narrow and is reported as narrow.

---

## Six layers rather than five

**Chosen:** measurements, indicators, typologies, assessment, posture, disposition.

**Discovered, not designed.** The specification had five layers with `composite_risk` and
`typology_support` together. They cannot share one: `composite_risk` reads `typology_support`, and
allowing same-layer reads reintroduces the possibility of cycles. Splitting assessment from posture
keeps the dependency graph acyclic and made the premise policy stricter rather than looser.

Recorded because a specification quietly edited to match the code is worth less than one that says
where it was wrong.

---

## The meta layer is functions, not rules

**Chosen:** `typology_support`, `conflict_state` and `missing_premise` are computed by Python
functions.

**Rejected:** expressing them as production rules.

**Why.** Each quantifies over the whole fact base: *the strongest* typology, *any two*
incompatible conclusions, *every* mandatory premise. Production rules match individual facts and
cannot express aggregation or universal quantification without an explosion of hand-maintained
guard rules: one rule per typology per band, all of which have to be kept in step. This is a
well-known limitation of production systems, and naming it is more honest than pretending the
formalism covers everything. The thresholds those functions use remain data.

**Two consequences, both real.** The backward chainer cannot cross the meta layer, so
`composite_risk` is unprovable from raw measurements even when every number it needs is present,
which is why the contrastive search re-runs the pipeline instead of chaining through it. And the
[ablation](07-evaluation.md) shows the meta layer is load-bearing for *every* decision, not just
abstention: disabling it collapses coverage to 2.4%.

---

## The disposition layer is a decision list

**Chosen:** ordered stages, first match wins.

**Rejected:** unordered production rules with mutual-exclusion guards.

**Why.** Outcome precedence is inherently ordered: a confirmed designation match outranks an
abstention, which outranks an ordinary referral, which outranks closure. Encoding that into
unordered rules means every lower stage carrying guards against every higher one: roughly triple
the premises, no added knowledge, and a hazard where inserting a stage silently invalidates the
guards below it.

A decision list is itself a knowledge representation formalism. Each stage keeps the same metadata
as a rule, the conditions are the same objects evaluated by the same matcher, and the firing stage
is recorded with its premises. Only first-match-wins is added.

---

## The veto layer can only block permissive outcomes

**Chosen:** prohibitions may forbid `clear` and `monitor`, and nothing else. Enforced by a test.

**Why.** A mechanism that can override the reasoning engine is dangerous in proportion to what it
can override *towards*. Restricting it to removing permissive options means it can only ever push a
case towards more human attention. It cannot suppress an escalation, and it cannot force a case to
be cleared.

**Measured, and the result is awkward.** The veto layer changes **no outcome at all** on 500 cases:
every prohibition is redundant with a guard the disposition stage already carries. It survives on
two narrower grounds, it holds if a stage is ever loosened, and it makes prohibitions visible so
"why not clear?" can answer *"a prohibition forbids it"*. But it earns none of the behavioural
credit the architecture diagram implies, and [07](07-evaluation.md) says so.

---

## Fictional jurisdictions

**Chosen:** invented jurisdictions (Alvarra, Dalmuir, Gysant) with FATF-shaped statuses.

**Rejected:** the real FATF grey and black lists.

**Why.** Real listings change several times a year, so a hard-coded list is stale almost
immediately, and it embeds political content for no engineering benefit. The fictional set exercises
every rule identically. A production system would load the current lists from the FATF and HM
Treasury publications at runtime, and [reference.py](../src/triagex/kb/reference.py) says so.

---

## Pessimistic defaults

**Chosen:** `sanctions_signal` defaults to `not_checked`; `kyc_status` to `unknown`; an
unrecognised jurisdiction code resolves to `fatf_status(unknown)`.

**Why.** A case file that forgets to mention a check must never read as clean. Combined with the
mandatory-premise rule, the omission becomes an abstention rather than a silent pass. The case
`refuse_never_screened_01` has no `sanctions_signal` line at all, and a test asserts the absence so
the case cannot quietly stop testing what it was written to test.

---

## TOML case files, not YAML

**Chosen:** TOML, read with the standard library's `tomllib`.

**Why.** It keeps the core dependency-free. For a project whose purpose is to be cloned and run,
that is worth more than YAML's marginal readability. TOML dates and datetimes parse natively, so no
date handling is needed at the loader boundary.

---

## Rule rationales are held to ASCII

**Chosen:** rationale and stage text is ASCII, enforced by a test. Docstrings, case notes and this
documentation keep real typography.

**Why.** A `£` in a rule rationale raised `UnicodeEncodeError` on a stock Windows console. These
are the strings printed most often, and a crash thirty seconds after cloning is a miserable first
impression. The output stream is also reconfigured to UTF-8 with replacement, so both layers of
defence are present and neither alone is relied on.
