# 07. Evaluation

Measured with `python experiments/evaluate.py`. Corpus: 500 generated cases, seed 20260920, of
which 17 (3.4%) have no defensible answer by construction.

**What these numbers are not.** The corpus is synthetic and its labels are true by construction.
Everything here measures internal consistency, the shape of the coverage trade-off, and what each
component contributes. None of it is evidence about real-world accuracy, which would need outcome
data from filed reports that no public dataset provides. The evaluation prints this caveat in its
own output so a figure cannot be quoted without it.

---

## 1. Why accuracy is not the headline

Clearing a case that should have been referred lets laundering through. Referring a clean
customer consumes an investigator and can freeze an innocent person's account. These are not the
same error, and no accuracy figure distinguishes them.

So the primary measure is **risk-weighted cost per case**, from the asymmetric matrix in
[reference.py](../src/triagex/kb/reference.py): missing a referral costs 25, over-escalating a
clean customer costs 6, declining a case that had an answer costs 2, and deciding a case the
system could not properly assess costs up to 12.

Selective accuracy is reported but never alone. A selective classifier can reach any accuracy it
likes by answering less, so accuracy and coverage are only meaningful as a pair.

---

## 2. Ablations

Each removes exactly one component, so the difference is attributable.

| configuration | cost/case | coverage | sel. acc | abstained | answered the unanswerable | missed referrals |
|---|---|---|---|---|---|---|
| **full system** | **0.476** | 88.8% | 97.9% | 56 | 17 | 2 |
| refuse stages removed | 0.788 | 91.4% | 95.0% | 43 | 17 | 2 |
| forced to answer | 1.648 | 100% | 86.5% | 0 | 17 | 2 |
| no veto layer | 0.476 | 88.8% | 97.9% | 56 | 17 | 2 |
| bayesian certainty | 0.476 | 88.8% | 97.9% | 56 | 17 | 2 |
| no meta layer | 1.660 | 2.4% | 100% | 488 | 0 | 0 |
| flat scorer | 3.498 | 100% | 46.6% | 0 | 17 | 21 |

### The flat scorer is 7.3× worse, and this project had been asserting that without evidence

The [flat baseline](../experiments/flat_baseline.py) is deliberately fair: same thresholds, same
signals, same cost matrix. What it lacks is the layering, no typologies, no meta reasoning, no
veto, no reject option. Every indicator contributes a weight to one number and the number picks a
band.

It costs **3.498 per case against 0.476**, and misses **21 referrals against 2**. Selective
accuracy is 46.6%. The documentation in this repository repeatedly claimed a flat scorer would do
worse; it now has a number attached, and the claim survives contact with measurement.

Note what the baseline structurally *cannot* do: `refuse_to_decide` is not in the range of its
classifier function. Collapsing an assessment to a scalar leaves no way to express "this cannot
be judged", because every input maps to a band and the bands cover the line. That is not an oversight
in the baseline; it is the clearest single argument for the layered design.

### Abstention cannot be ablated by deleting stages

Removing the three refuse stages left **43 abstentions**, because the freed cases fall through and
the deficiency fallthrough abstains too. *Silence is a refusal* is a design commitment, and it
turns out to be load-bearing: forcing the system to answer everything requires substituting the
fallthrough as well, not merely deleting stages.

With the fallthrough substituted, cost rises from 0.476 to **1.648**: abstention is worth a
factor of 3.5 on this corpus. That is the claim the whole design rests on, and it is measured
rather than assumed.

### The veto layer changes no outcome at all

Identical figures, to three decimal places. Every prohibition turns out to be redundant with a
guard the disposition stage already carries: `VETO-CLEAR-02` forbids closure when typology support
is strong, and `DISP-CLEAR-01` already requires support to be *none*. The same holds for all six.

This is reported rather than quietly dropped. The layer keeps two defensible purposes, it holds
if a disposition stage is ever loosened, and it makes prohibitions visible in explanations, which
is how "why not clear?" can answer *"a prohibition forbids it"*. But it does not change a single
decision here, and claiming it did would be an invented result.

### The Bayesian arithmetic changes nothing either

Also identical. Swapping MYCIN combination for odds multiplication and weakest-link conjunction
for a product moved individual certainties, 0.70 with 0.50 becomes 0.889 instead of 0.850, and
changed **no decision at all**.

The docstring in [certainty.py](../src/triagex/engine/certainty.py) argues that certainty factors
are worth keeping for transparency despite not being probabilistically sound. On this rule base
that transparency is free: the discrete band boundaries absorb the arithmetic difference. It is a
narrow result, a rule base with tighter bands or longer chains would likely diverge, but it is
the result.

### The meta layer is structural, not optional

Disabling it collapses coverage to 2.4%: `typology_support`, `conflict_state` and
`missing_premise` all come from the meta functions, and the disposition stages read them, so
without the meta pass nothing matches any stage. The meta layer is not an abstention feature
bolted onto a working system; it is load-bearing for every decision the system makes. Worth
knowing, and not what the architecture diagram suggests.

---

## 3. The risk-coverage curve, and a negative result

Sweeping the margin threshold: abstain when the deciding certainty sits within τ of the band
boundary that produced it, the same quantity the explanation facility reports when it says how
close a call was.

| τ | coverage | cost/case | sel. acc | answered the unanswerable |
|---|---|---|---|---|
| **0.00** | 88.8% | **0.476** | 97.9% | 17 |
| 0.05 | 70.8% | 0.836 | 97.3% | 17 |
| 0.10 | 64.8% | 0.956 | 97.1% | 17 |
| 0.15 | 52.2% | 0.834 | 96.6% | **0** |
| 0.20 | 41.6% | 1.046 | 95.7% | 0 |
| 0.25 | 41.6% | 1.046 | 95.7% | 0 |
| 0.30 | 41.6% | 1.046 | 95.7% | 0 |

**The margin-based reject option does not pay on this corpus.** τ = 0 is cheapest, and every
widening makes things worse. This is the opposite of what the design anticipated and it is
reported as the headline of this section rather than buried.

The reason is instructive. The system already answers 97.9% of its decided cases correctly, so a
confidence margin removes correct answers roughly as often as wrong ones, and each removal costs
the abstention charge. A scalar margin cannot tell a marginal-but-right decision from a
marginal-and-wrong one.

Two things worth separating out of that:

**Knowledge-based abstention pays; confidence-based abstention does not.** The abstentions that
earn their place are the categorical ones, out of scope, mandatory premise missing, where the
knowledge base can say precisely *what* it does not know. Those are what produce the 3.5× gap
against a forced answer. The margin overlay, which knows only that a number is near a boundary,
loses money. That distinction is the most useful thing this evaluation produced, and it maps
exactly onto the epistemic-versus-authority boundary the whole system is built around: knowing
*what* you do not know is worth something, and knowing only *that* you are unsure is not.

**τ = 0.15 does fix one specific failure.** It is the point at which the system stops answering
all 17 cases that have no defensible answer, and the cost dip from 0.956 to 0.834 is that effect.
But it still loses to τ = 0 overall, so the correct conclusion is that the margin overlay stays
off by default, not that it is tuned to 0.15.

---

## 4. Confusion matrix, full system

```
expected \ predicted        clear    monitor  request_e  refer_to_  refuse_to
clear                         150          .          .          .          .
monitor                         7         13          .          .          .
request_evidence                .          .        125          .          .
refer_to_investigation          2          .          .        130          .
refuse_to_decide                .          .          .          .         56
unanswerable                    .          .          8          9          .
```

Two error groups, both worth naming:

**Seven cases that should have been monitored were cleared.** The `adverse_media` profile produces
uncorroborated media hits, and unverified media deliberately feeds no typology, `TYP-MEDIA-01`
requires *verified* media. So the case reads as clean. This is arguably correct behaviour rather
than an error: acting on unchecked reporting about a named individual is its own harm, and the
generator's label may be the thing that is wrong. Recorded as an open question rather than
silently relabelled.

**Two cases that should have been referred were cleared.** Both are the dangerous error class, and
two out of 132 referrals is not a number to be relaxed about. They are cases where the
exculpatory rules cancelled a genuine signal, the mechanism that prevents the system convicting
everyone, doing too much work on a specific shape of case.

---

## 5. Open items

- **The 7 monitor-to-clear errors need adjudicating:** either the unverified-media policy is
  wrong or the generator's label is. Deciding that requires a view on whether uncorroborated
  adverse media should influence a disposition at all, which is a policy question rather than an
  engineering one.
- **The two missed referrals warrant a targeted look** at whether the exculpatory strengths are
  too strong on that case shape.
- **Threshold sensitivity is not yet measured.** Every numeric cut-off is `reconstructed`, and the
  knowledge-acquisition doc promises the evaluation tests sensitivity to them. A sweep over the
  main thresholds, not just the abstention margin, is still outstanding.
