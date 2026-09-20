# 05. Abstention

The feature the rest of the system exists to support: the ability to decline.

---

## 1. Two boundaries, not one

The output space has two ways of handing a case to a human, and collapsing them would lose the
distinction the law itself draws.

| | `refer_to_investigation` | `refuse_to_decide` |
|---|---|---|
| Kind of boundary | **Authority** | **Epistemic** |
| Belief formed? | Yes, the system knows what it is looking at | No |
| Why a human? | Only the MLRO can lawfully authorise a report | The knowledge base cannot support a view |
| Emotional register | Confident, and deferring | Unable |
| Reported as | A rationale and the supporting proof tree | The specific reason it could not decide |

A marker of the difference: a referral comes with a narrative an investigator can act on. An
abstention comes with a statement of what the system could not handle. They are different artefacts
for different readers.

---

## 2. Why the law makes this necessary rather than merely tidy

Under [POCA 2002 s.330](https://www.legislation.gov.uk/ukpga/2002/29/section/330) the failure-to-
disclose offence has a negligence limb: it is committed where a person had **reasonable grounds** for
knowing or suspecting money laundering, even if they did not personally suspect it.

The test is therefore *objective*. What matters is what a reasonable person should have concluded from
the information available, not what anyone actually concluded.

That has a direct consequence for system design. A system that resolves its own uncertainty into
a clean `clear` has not removed the uncertainty; it has hidden it, while the objective standard
still applies to the firm. Surfacing *"the evidence here is contradictory and no view can be
formed"* is the legally honest output, and the one that leaves a human able to meet the standard.

---

## 3. Four ways the system declines

Each names a different thing it could not do, because an abstention that does not say what went
wrong is useless to whoever receives it.

### Out of scope

The case contains something the knowledge base has no model of: a cryptoasset transfer, or a
trust structure. Detected at layer 1 (`unsupported_instrument`, `unsupported_structure`), lifted to
`scope_state(out_of_scope)` at layer 3.

Reported with the specific gap: *"cryptoasset transfer: requires chain analytics"*.

This is why the four excluded typologies are load-bearing rather than a shortcut. A system claiming
total coverage recognises nothing as outside its competence and cannot have a meaningful abstention.

### Missing mandatory premise

`sanctions_signal`, `kyc_status` and `customer_type` must be *known*. A value of `not_checked` or
`unknown` does not count.

This rests on two mechanisms working together. The frame defaults are pessimistic: a case file
that never mentions screening produces `not_checked`, not `none`. And predicates registered as mandatory
**cannot be queried under negation-as-failure**: the engine raises rather than let a missing check
read as clean.

The case `refuse_never_screened_01` has no `sanctions_signal` line at all, and a test asserts that
absence so the case cannot quietly stop testing what it was written for.

### Irreconcilable conflict

Substantial evidence points both ways and neither side dominates.

Detected by reading the **activations** rather than the surviving fact, which is the subtle part. The
certainty algebra cancels opposing evidence towards zero, so a cf of 0.02 from strong evidence on
both sides looks identical to a cf of 0.02 from no evidence at all. Those are very different states
and only one should produce an answer. Comparing the strongest supporting and strongest opposing
activation for each typology preserves the difference.

**This stage has never fired on any corpus.** Recorded as an open gap rather than presented as
working: the generated cases do not produce genuine two-sided evidence even after the `ambiguous`
profile was added.

### Deficiency

No stage of the decision list matched. The outcome is `refuse_to_decide`, and the verifier treats any
case reaching it as a **coverage defect in the knowledge base** rather than a property of the case.

*Silence is a refusal, not a pass.* Most engines fail open or fail silent; this one fails loud.

That turned out to have a consequence nobody anticipated: abstention **cannot be ablated by deleting
the refuse stages**, because the freed cases fall through and the fallthrough abstains too. Measuring
what abstention is worth required substituting the fallthrough as well.

---

## 4. Precedence: mandatory escalation outranks abstention

A confirmed designation match on an out-of-scope case still escalates.

Abstaining on a confirmed match would itself be a failure to act, so the veto layer is permitted to
push a case *through* an abstention, but only ever in the direction of more human attention. It can
escalate and it can block; it has no power to resolve uncertainty downwards, and a test enforces
that prohibitions may only forbid `clear` and `monitor`.

Full ordering in [03](03-knowledge-model.md) §6.

---

## 5. What it is worth, measured

| | cost/case | coverage |
|---|---|---|
| full system | **0.476** | 88.8% |
| refuse stages removed (still abstains via fallthrough) | 0.788 | 91.4% |
| forced to answer | 1.648 | 100% |
| flat scorer (structurally cannot abstain) | 3.498 | 100% |

Abstention is worth a factor of **3.5** against forced answering on a risk-weighted cost model.

Note what the flat baseline demonstrates structurally rather than numerically: `refuse_to_decide` is
not in the range of its classifier function at all. Collapsing an assessment to a scalar leaves no way
to express "this cannot be judged", because every input maps to a band and the bands cover the
line.

---

## 6. The negative result

The design also anticipated a **selective-prediction threshold**: abstain when the deciding certainty
sits within τ of the band boundary that produced it. This is the mechanism the reject-option
literature suggests ([Chow 1970](https://ieeexplore.ieee.org/document/1054406); El-Yaniv and Wiener
2010), and the same quantity the explanation facility reports when it says how close a call was.

It was implemented, swept, and **does not pay**:

| τ | coverage | cost/case |
|---|---|---|
| **0.00** | 88.8% | **0.476** |
| 0.05 | 70.8% | 0.836 |
| 0.10 | 64.8% | 0.956 |
| 0.15 | 52.2% | 0.834 |
| 0.20+ | 41.6% | 1.046 |

Cost rises as the margin widens. The system already answers 97.9% of its decided cases correctly, so
a scalar margin removes correct answers roughly as often as wrong ones, and each removal costs the
abstention charge. A margin knows only that a number is near a boundary; it cannot tell a
marginal-but-right decision from a marginal-and-wrong one.

τ = 0.15 does fix one specific failure: it is the point at which the system stops answering all
17 cases that have no defensible answer. It still loses overall, so the overlay stays **off by
default**.

### The distinction this produced

**Knowing *what* you do not know is worth something. Knowing only *that* you are unsure is not.**

Categorical abstention (out of scope, premise missing) earns the 3.5×, because the system can
name the gap and a human can act on the name. Confidence-based abstention loses money, because
bare uncertainty gives the recipient nothing to do.

That maps exactly onto the epistemic-versus-authority distinction the whole system is built around,
which was not the reason for building it that way, and is the most useful thing the evaluation
produced.
