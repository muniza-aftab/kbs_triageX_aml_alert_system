# 04. Inference

How conclusions are reached. The engine in [src/triagex/engine/](../src/triagex/engine/) knows
nothing about money laundering; everything domain-specific lives in the rule base.

---

## 1. The assessment pipeline

One assessment is deliberately not one pass. It alternates between inference and meta-level
assessment, because the meta layer has to look at what the domain rules concluded before the
disposition layer can act:

```
  measurements
       |
   [ chain ]      indicators, typologies, assessment          layers 1-3
       |
   [ meta  ]      strongest typology -> support band
                  mandatory premises established?
                  does the evidence contradict itself?
       |
   [ chain ]      composite risk, prohibitions                layer 4
       |
  [ decide ]      the decision list                           layer 5
```

**Refraction state is shared across both chaining runs**, and this is not an optimisation.
Repeated conclusions *combine* certainty, so a rule re-firing on evidence it has already used
would inflate its own conclusion. Evidence counted twice is not stronger evidence.

---

## 2. Forward chaining

Data-driven, agenda-based. Each cycle finds every rule that could fire given what is currently
believed, picks one, asserts its conclusion, and repeats until nothing new follows.

Forward chaining suits the bulk of the work because the input is a fixed case file and the useful
task is deriving everything that follows from it.

### Termination

Guaranteed by **refraction on premise content**: a rule fires at most once per distinct combination
of premises.

The detail that matters is *content* rather than assertion sequence. Certainty factors get revised
as evidence accumulates, which changes a fact's sequence number, so keying refraction on sequence
would let the same rule re-fire on the same evidence indefinitely. The cycle limit is a diagnostic
backstop, not the mechanism; if it ever trips, the rule base has a problem the verifier should have
caught.

### Conflict resolution

When several rules are eligible, the policy is applied in strict order. This is a
knowledge-engineering decision, not an implementation detail, it decides which of two competing
readings of a case wins.

| | rule | rationale |
|---|---|---|
| 1 | **Specificity**: more premises wins | A rule accounting for more of the evidence should beat one accounting for less. In a layered base this is where refinement rules live: they carry the extra premise. |
| 2 | **Priority**: explicit integer | For genuine ties where the domain has an opinion. Veto rules sit above ordinary ones. |
| 3 | **Recency**: most recently asserted premise | Keeps inference moving forwards through the layers rather than revisiting settled ground. |
| 4 | **Rule id**: deterministic | Two runs over identical input fire rules in identical order. An auditable system whose trace differs between runs is not auditable. |

Losing activations are **recorded, not discarded**. A system that only remembers what it did cannot
explain what it nearly did, and "why not?" is the question that matters most in practice.

---

## 3. Backward chaining

Goal-directed, with unification. Answers one question, *can this be established, and how?*, without deriving the rest.

Both directions are needed for different jobs. Forward chaining produces the assessment. Backward
chaining answers questions *about* an assessment, including hypothetical ones: "could this have been
cleared?", "what would have to hold for the evidence to count as sufficient?". Those are asked
against a fact base that does **not** contain the conclusion, so a forward pass has nothing to find.

### Two enforced restrictions

**Goal subjects must be ground.** Every real question is about one specific alert; supporting
unbound subjects would mean joining across cases for no benefit.

**Only predicates some rule concludes are derivable.** Everything else is a base measurement that
can be checked but never proved. `credit_count` is observed; `typology` is derived.

### The meta layer is a hard boundary

`typology_support`, `conflict_state` and `missing_premise` are computed by functions rather than
rules, so nothing concludes them and backward chaining cannot derive them. Goals *above* the meta
layer, `composite_risk`, `disposition_blocked`: are provable only when those meta facts are
already believed, which they are after a normal assessment but not from raw measurements alone.

This is asserted by a test so it cannot regress silently, and it settled a design question: the
contrastive search re-runs the whole pipeline over a modified case rather than chaining through it,
because the honest way to cross a procedural step is to execute it.

---

## 4. Certainty arithmetic

MYCIN-style certainty factors in [-1, 1].

| operation | formula |
|---|---|
| Conjunction of premises | `min(cf_i)`: the weakest link |
| Disjunction | `max(cf_i)` |
| Rule conclusion | `strength × cf(premises)` |
| Two positive beliefs | `cf₁ + cf₂(1 − cf₁)` |
| Two negative beliefs | `cf₁ + cf₂(1 + cf₁)` |
| Mixed signs | `(cf₁ + cf₂) / (1 − min(|cf₁|, |cf₂|))` |
| Noise floor | facts weaker than 0.20 are not asserted |

### Negative strength, and why it matters

Rule strengths may be negative. A system that can only accumulate suspicion will convict every
customer eventually, given enough rules, so four typology rules argue *against* their hypothesis:
an established account with few payers does not fit the mule pattern; a healthy closing balance is
inconsistent with a conduit.

The mixed-sign branch is what lets exculpatory evidence actually reduce a typology's certainty
rather than merely failing to raise it.

### The honest caveat, and the measurement

Certainty factors are **not probabilities**. The combination function is not derivable from
probability theory, and it assumes premise independence that this rule base does not have, several
indicators derive from the same transactions. Heckerman's analysis showed the scheme is coherent
only under restrictive conditions.

The justification was transparency: a human can read `0.70` off a rule and argue with it. That is a
claim, so it was tested. [The ablation](07-evaluation.md) swapped in odds-multiplication combination
and product conjunction; individual certainties moved (0.70 with 0.50 gives 0.889 rather than 0.850)
and **no decision changed**. The discrete band boundaries absorb the difference, so on this rule base
the transparency is free.

That result is narrow. Tighter bands or longer chains would likely diverge.

### Where continuous meets discrete

`support_band()` is the only place a certainty becomes a symbol:

| certainty | band |
|---|---|
| ≥ 0.75 | strong |
| ≥ 0.55 | moderate |
| ≥ 0.30 | weak |
| below | none |

Keeping the conversion in one function means the disposition rules stay symbolic, and the bands can
be swept from a single place.

---

## 5. Traces and proof trees

Every derived fact records the rule that produced it and the facts that rule consumed, recursively,
down to asserted input. Rendering that gives a proof tree:

```
typology_support(ALT-3001) = strong  [cf +1.00]
  <- derived by META-SUPPORT-01
    typology(ALT-3001) = structuring  [cf +0.86]
      <- combined from 2 independent derivations
        <- derived by TYP-STRUCT-02
          deposit_frequency(ALT-3001) = extreme  [cf +1.00]
            <- derived by IND-FREQ-02
              credit_count(ALT-3001) = 14  [cf +1.00]
                <- asserted from case.credit_count
```

Duplicate premises are dropped at the activation level. A band test comparing one measurement
against both an upper and a lower bound legitimately matches the same fact twice, and without
deduplication every explanation reads as though the system counted the same evidence twice.

The trace is not debug output; it is the substrate the whole explanation facility is built on.
