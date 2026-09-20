# Rule Base Refinement Log

Every change to the knowledge base after it first ran, with what forced it. A rule base that
arrives correct on the first attempt was not tested hard enough, so this file is evidence of
work rather than an admission of sloppiness.

Each entry names the mechanism that caught the problem, because that matters more than the
problem: a defect found by a test means the tests are working, and a defect found by reading
means the tests are not.

---

## v1 → v2, caught by the M3 behavioural tests

### The cash typology fired for a salaried individual

**Found by:** the end-to-end run of the worked example from `docs/03`, which produced
`cash_intensive_layering (cf 0.65)` for a *retail* customer.

**Defect:** `TYP-CASH-01` and `TYP-CASH-02` had no customer-segment premise. Typology rules read
Layer 1 only, so they could not see `customer_type` at all, meaning a salaried person banking
cash looked identical to a business layering its takings.

**Fix:** added the `customer_segment` indicator (`IND-SEG-01`) so the segment is visible at
Layer 1, and added it as a premise to all three cash rules.

**Now guarded by:** `test_cash_typology_does_not_fire_for_a_retail_customer`, plus the
regression case `adversarial_retail_heavy_cash_01`.

### A clean customer with stale due diligence matched no stage at all

**Found by:** `test_no_case_reaches_the_deficiency_fallthrough`, a test written specifically to
find coverage holes rather than to confirm behaviour.

**Defect:** the decision list had no stage for "nothing suspicious, but the file is incomplete".
Such cases fell through to `refuse_to_decide(deficiency)`: technically the designed failure
mode, but a gap in the knowledge rather than a property of the case.

**Fix:** added `DISP-EVID-02` (incomplete file, clean activity → `request_evidence`) and
`DISP-MON-02` (boundary scope, otherwise clean → `monitor`). Also relaxed `DISP-CLEAR-01` to
accept a `soft` conflict, since a soft conflict is a resolved conclusion with the dissent
recorded, not an open question.

**Now guarded by:** the fallthrough test, widened to ten case shapes.

---

## v2 → v3, caught by the M7 rule-base audit

The audit's first run reported 0 errors, 38 warnings and 3 notes over 100 rules. Triage
mattered more than the raw count: most of the warnings were the verifier's fault.

### 23 of 24 conflict warnings were false positives

**Found by:** reading the audit output rather than trusting it.

**Defect, in the verifier, not the rule base:** `_premises_compatible` compared only symbolic
`Has` value demands, so it could not see that `credit_count >= 5` and `credit_count < 5` are
mutually exclusive. Every banded indicator was reported as conflicting with its own siblings.

**Why it mattered more than the count suggests:** a verifier that produces 23 false positives
gets ignored, and an ignored verifier is worse than none, it provides the appearance of
assurance while hiding the one real finding among the noise.

**Fix:** taught the verifier interval arithmetic over `Cmp` and `Ratio` premises, and taught it
that `Missing(p)` and `Has(p, …)` cannot both hold. All 24 conflict warnings resolved, and the
remaining checks became legible.

### A domestic PEP was silently recorded as a foreign one

**Found by:** the `unreachable_value` check, which noticed nothing could ever produce
`pep_exposure(domestic)`.

**Defect:** `IND-PEP-01` matched `In("foreign", "domestic")` and concluded
`pep_exposure(foreign)`. MLR 2017 reg. 35 covers both, but the risk is not the same, and the
rule overstated the exposure of every domestic PEP while leaving a declared value dead.

**Fix:** split into `IND-PEP-01` (foreign) and `IND-PEP-04` (domestic).

**Worth noting:** no test would have caught this. Every case still produced a defensible
disposition; the bug was in the *meaning* of a fact, not in any outcome. This is precisely the
class of defect verification exists to find.

### Fourteen declared values nothing could produce

**Found by:** the `unreachable_value` check.

**Defect:** dead vocabulary. `counterparty_novelty` was declared with three values and used by
no rule at all. `deposit_frequency(low)`, `velocity(low)`, `documentation_gap(identity)` and
several `absent` values were declared but only ever tested by absence, which the three-valued
fact base handles directly. `disposition_blocked` declared all five dispositions when the veto
layer may by design only block the two permissive ones.

**Why it is not cosmetic:** a declared value tells a reader that something can mean it. Fourteen
that cannot is fourteen invitations to write a rule against a value that will never arrive.

**Fix:** removed `counterparty_novelty` entirely; narrowed the presence-flag predicates to
`("present")`; narrowed `disposition_blocked` to `("clear", "monitor")`; and *completed* two
graded indicators rather than deleting their values, adding `IND-PROX-03` (nowhere near the
threshold) and `IND-MEDIA-03` (media checked, nothing found), because `posture.py` claims every
graded indicator asserts a definite value and that claim should be true.

### Twenty rules had never fired

**Found by:** the `dead_rule` check, replaying the curated library plus 300 generated cases.

**Diagnosis:** a gap in the *corpus*, not the knowledge. Gambling flows, countermeasure
jurisdictions, lapsed diligence, adverse media, political exposure, cash-business abuse and
partly-unassessable cases all had rules and no cases.

**Fix:** nine new generator profiles, and two existing profiles widened to emit values they
never picked (`adverse_media(unverified)`, `pep_status(domestic)`). Dead rules fell from 20 to
zero across 824 cases.

**Current state:** 103 rules, 0 errors, 0 warnings, 3 notes.

---

## Known gaps, deliberately still open

**`DISP-REFUSE-03` has never fired.** The irreconcilable-conflict abstention is unreachable in
the current corpus, because the generator produces almost no genuinely ambiguous cases, its
profiles were written from the same thresholds the rules use, so agreement with its labels sits
at 99.8%, which measures self-consistency and nothing else. Until an `ambiguous` profile samples
the bands *between* profiles, the coverage-versus-risk curve at M8 would be close to
meaningless. This is the first thing M8 must fix, and it is recorded here rather than quietly
left out of the evaluation.

**Two refinement notes are expected.** `TYP-STRUCT-02` and `TYP-ROUND-02` add premises to their
parents at lower strength, which is how corroborating evidence accumulates certainty. The audit
reports them as notes rather than suppressing them, so a reader can confirm the pattern is
deliberate rather than take it on trust.
