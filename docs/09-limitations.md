# 09. Limitations

What this system does not do. Written plainly, because a project that lists no limitations is
either trivial or not being straight with you.

---

## It has never seen a real case

Every case is synthetic. Every label is true by construction. The 24 curated cases were written by
the same person who wrote the rules, and the generator's profiles were built from the same
thresholds the rules use, which is why the generated corpus agreed with its own labels 99.8% of the
time before the `ambiguous` profile was added. That figure measured the generator and the rule base
sharing assumptions, and nothing about the system's judgement.

**The consequence is specific.** No number in [07](07-evaluation.md) is evidence about real-world
accuracy. They measure internal consistency, the shape of the coverage trade-off, and what each
component contributes. Real calibration needs outcome data (which alerts became reports, and
which reports became prosecutions), and no public dataset provides it.

---

## Every threshold is invented, and their sensitivity is unmeasured

56% of rules are tagged `reconstructed`: the shape comes from published typology material, the
numbers were set for this project. Published guidance deliberately leaves cut-offs to each firm's
risk appetite, so there was nothing to copy.

[02](02-knowledge-acquisition.md) promises the evaluation tests sensitivity to them. It does not
yet. The abstention margin is swept; the actual thresholds, the GBP 3,000 review level, the 80%
proximity band, the 5-and-10 frequency bands, the 90-day immaturity window, are not. **A result
that holds only at one arbitrary threshold setting is weaker than it looks, and this is the largest
outstanding gap in the evaluation.**

---

## Four typologies are deliberately out of scope, and that is load-bearing

Trade-based laundering, cryptoasset ramps, correspondent banking and trust structures are excluded.
Not as a shortcut, a system claiming total coverage cannot have a meaningful abstention outcome,
because it recognises nothing as outside its own competence.

The honest cost is visible in the case library. `refuse_crypto_otherwise_clean_01` is an ordinary
salary plus a £250 crypto purchase; a coverage-maximising system would clear it, and this one
declines. Scope is not a risk judgement, so it abstains even when the rest of the case is obviously
fine. That case is kept in the library rather than hidden from it.

---

## Intent is not observable, and the system does not claim it is

Rules conclude `typology(structuring)`: "this behaviour matches the structuring pattern". Never
that anyone intended to structure. Intent cannot be seen in transaction data, and a system claiming
to detect it would be lying about what it can see.

This matters for how output should be read. `typology(structuring, cf +0.86)` is a statement about
pattern-matching, not about a person.

---

## The contrastive search answers a narrower question than it appears to

"What would have to change" finds the cheapest evidence that would move **the system's** decision.
It says nothing about what is true. An intervention labelled `source_of_funds_evidence -> present`
means *"if documentation were produced"*, not *"the documentation would exonerate them"*.

Confusing those two turns an explanation facility into a machine for justifying a predetermined
conclusion. The rendered output carries the distinction explicitly, and it is repeated here because
it is the easiest thing in the project to misread.

---

## One case, one customer, one alert

The fact base flattens every fact onto the alert. That removes the need for rules to join across
subjects, and it means the system cannot reason about:

- a customer with several accounts behaving differently
- two customers who are counterparties to each other
- the same counterparty appearing across many alerts
- anything at portfolio level

Real transaction monitoring does all of these. The graph search touches the edge of it, the
counterparty network is genuinely multi-party, but the *reasoning* is single-case.

---

## The abstention mechanism that works is not the one the literature suggests

The design anticipated a selective-prediction threshold: abstain when confidence is marginal. That
was implemented, swept, and **found not to pay**: cost rises monotonically as the margin widens,
because a scalar margin discards correct answers about as often as wrong ones.

What earns the 3.5× gap against forced answering is *categorical* abstention: out of scope, mandatory
premise missing. The system can say precisely **what** it does not know. Knowing only **that** it is
unsure is worth nothing here.

This is worth stating as a limitation rather than a finding, because it means the reject-option
literature this project draws on
([Chow 1970](https://ieeexplore.ieee.org/document/1054406); El-Yaniv and Wiener 2010) does not
transfer as directly as the design assumed.

---

## Engineering limits

**No RETE.** Condition matching is a linear scan of working memory, so the engine is
O(facts × conditions) per cycle. Fine at single-digit milliseconds per case; wrong at production
volume.

**The backward chainer cannot cross the meta layer.** `typology_support` and friends are computed by
functions, so nothing concludes them and `composite_risk` is unprovable from raw measurements even
when every number it needs is present. Asserted by a test so it cannot regress silently.

**No persistence, no concurrency, no API.** Assessments are in-memory and single-shot. There is no
audit store, which a real deployment would require before anything else.

**The MLRO override is modelled but not exercised.** [03](03-knowledge-model.md) describes human
overrides being recorded alongside the machine disposition as a calibration signal. The data model
supports it; no case uses it, and nothing consumes the signal.

---

## Two open questions in the results

**Seven cases that should have been monitored were cleared.** The generator produces uncorroborated
adverse media, and unverified media deliberately feeds no typology, acting on unchecked reporting
about a named individual is its own harm. So the case reads as clean. Either the policy is wrong or
the generator's label is, and deciding that is a policy question rather than an engineering one. It
is recorded as open rather than silently relabelled.

**Two cases that should have been referred were cleared.** Two out of 132 referrals, in the error
class the domain actually fears. Both are cases where exculpatory rules cancelled a genuine signal, the mechanism that stops the system convicting everyone, doing too much work on a specific shape of
case. Not yet investigated.

---

## What this is for

A portfolio project demonstrating knowledge representation, inference, search, verification and
honest evaluation. It is not a compliance product, it has no regulatory approval, and it would need
real data, real calibration, persistence, access control and an audit trail before it resembled one.

Read [docs/refinement-log.md](refinement-log.md) for what was wrong and what caught it. That file is
a better guide to the engineering than this one.
