# 03. Knowledge Model

The formal specification the engine and knowledge base are built against. If code and this
document disagree, this document is wrong and should be corrected, but it should not be
silently diverged from.

---

## 1. Design principles

Four commitments that the rest of the model follows from.

1. **Knowledge is data, not control flow.** Rules are declarative objects with metadata, not
   Python `if` statements. The engine knows nothing about money laundering.
2. **No rule maps raw input to a disposition.** Every conclusion passes through derived
   intermediate concepts. This is enforced at rule-construction time by an explicit
   per-layer premise policy (section 4a), not merely by requiring premises to sit somewhere
   lower.
3. **Unknown is not false.** The fact base is three-valued. Absence of evidence is
   represented explicitly, because the difference between "no sanctions match" and "no
   sanctions check performed" is the difference between a safe decision and an unsafe one.
4. **Every conclusion is reconstructible.** Any derived fact can name the rule that produced
   it and the facts it consumed, recursively, down to asserted input.

---

## 2. Frame hierarchy

Frames carry typed slots with defaults, validation and single inheritance. A subclass may
override a default or narrow an allowed-value set, never widen it.

```
Entity
├── Party
│   ├── Customer
│   │   ├── RetailCustomer
│   │   ├── BusinessCustomer
│   │   │   └── CashIntensiveBusiness
│   │   └── TrustCustomer            [scope marker: out of scope]
│   └── Counterparty
│       ├── KnownCounterparty
│       └── UnknownCounterparty
├── Account
│   ├── CurrentAccount
│   ├── SavingsAccount
│   └── PaymentAccount
├── Transaction
│   ├── CashDeposit
│   ├── CashWithdrawal
│   ├── InboundTransfer
│   ├── OutboundTransfer
│   ├── CardPayment
│   └── CryptoTransfer               [scope marker: out of scope]
├── Jurisdiction
└── Alert
```

### Why frames rather than flat records

Inheritance does real work here, and the `CashIntensiveBusiness` case shows it. A rule
written about `BusinessCustomer` automatically applies to cash-intensive businesses, while
the subclass overrides `expected_cash_ratio` from `0.15` to `0.60`. Without inheritance,
every cash-related rule would need a special case, and a takeaway depositing 80% of turnover
in cash would look identical to a consultancy doing the same thing.

The `[scope marker]` classes exist purely so the meta-layer can recognise a case it has no
business deciding. Instantiating a `CryptoTransfer` is sufficient to put a case out of scope.

### Principal slots

| Frame | Slot | Type / allowed values | Default |
|---|---|---|---|
| `Customer` | `customer_type` | retail \| business \| cash_intensive \| trust |, (required) |
| | `risk_rating` | low \| medium \| high | medium |
| | `pep_status` | none \| domestic \| foreign \| associate | none |
| | `sanctions_signal` | none \| possible \| confirmed \| **not_checked** | not_checked |
| | `kyc_status` | complete \| partial \| expired \| unknown | unknown |
| | `onboarding_date` | date |, (required) |
| | `expected_monthly_turnover` | money |, (required) |
| | `expected_cash_ratio` | ratio 0-1 | 0.15 (0.60 for cash-intensive) |
| | `source_of_funds_evidence` | present \| absent \| requested \| unknown | unknown |
| | `adverse_media` | none \| unverified \| verified \| unknown | unknown |
| `Account` | `account_type`, `opened_date`, `balance`, `average_balance_90d`, `dormant_since` | | |
| `Transaction` | `amount`, `currency`, `timestamp`, `direction` | in \| out |, |
| | `channel` | branch \| atm \| online \| mobile \| api |, |
| | `counterparty`, `narrative` | | |
| `Counterparty` | `jurisdiction`, `relationship_declared`, `prior_txn_count`, `is_flagged` | | |
| `Jurisdiction` | `fatf_status` | compliant \| grey_list \| black_list \| unknown | unknown |
| | `secrecy_score` | 0-10 |, |
| `Alert` | `customer`, `window_start`, `window_end`, `trigger_rule`, `transactions[]` | | |

Note the two defaults that are deliberately pessimistic: `sanctions_signal` defaults to
`not_checked` and `kyc_status` to `unknown`. Neither defaults to a benign value, because a
case file that forgets to mention them must not read as clean.

---

## 3. Fact representation

Working memory holds facts of the form:

```
Fact(predicate, subject, value, cf, derivation)
```

| Field | Meaning |
|---|---|
| `predicate` | e.g. `deposit_frequency`, `typology`, `composite_risk` |
| `subject` | the entity the fact is about (customer id, alert id, account id) |
| `value` | a member of the predicate's declared value set |
| `cf` | certainty factor in [-1, 1]; asserted observations are 1.0 |
| `derivation` | `Asserted(source_field)` or `Derived(rule_id, [premise facts])` |

### Three-valued semantics

| State | Represented as | Meaning |
|---|---|---|
| True | fact present with cf > 0 | believed to hold |
| False | fact present with cf < 0, or a `not_` value | believed not to hold |
| Unknown | no fact, or value `unknown` / `not_checked` | no belief either way |

**Negation as failure is permitted for indicator convenience but forbidden for mandatory
premises.** An indicator rule may test "no declared relationship exists" by absence. A
disposition rule may never treat an absent `sanctions_signal` as `none`. The engine enforces
this: predicates registered as `mandatory` raise if queried under negation-as-failure.

This is the single most important safety property in the model, and it is the mechanism by
which a missing check becomes `refuse_to_decide` rather than a quiet `clear`.

---

## 4. The five levels

### L0, Asserted facts

Read directly from the case file. No inference.

### L1, Indicators (observations, judgement-free)

Indicators report what is observably true. They carry no opinion about what it means, which
is what allows one indicator to feed several typologies.

| Predicate | Values |
|---|---|
| `deposit_frequency` | low \| normal \| elevated \| extreme |
| `threshold_proximity` | none \| moderate \| high |
| `channel_dispersion` | absent \| present |
| `aggregation_gap` | absent \| present |
| `velocity` | low \| normal \| high \| extreme |
| `balance_retention` | low \| normal |
| `turnover_deviation` | within \| above \| far_above |
| `cash_ratio_deviation` | within \| above |
| `counterparty_novelty` | established \| new \| unknown |
| `counterparty_concentration` | diffuse \| concentrated \| hub |
| `geographic_risk` | low \| elevated \| high \| unknown |
| `account_immaturity` | false \| true |
| `dormancy_break` | false \| true |
| `third_party_pattern` | absent \| present |
| `round_trip_signature` | absent \| present |
| `gambling_cycling_pattern` | absent \| present |
| `documentation_gap` | none \| source_of_funds \| identity \| purpose |
| `kyc_currency` | current \| stale \| expired |
| `pep_exposure` | none \| domestic \| foreign \| associate |
| `sanctions_signal` | none \| possible \| confirmed \| not_checked |
| `adverse_media_signal` | none \| unverified \| verified |
| `unsupported_instrument` | absent \| present |
| `unsupported_structure` | absent \| present |

The last two are scope observations, and they belong at this layer for the same reason as
everything else here: *"a transaction appears that this system has no model of"* is an
observation about the case, not a judgement about it. Putting them here is what allows
`scope_state` to be derived at Layer 3 without any rule ever reading raw data to decide a
question of competence.

### L2, Typologies (hypotheses, carry certainty)

`typology(alert_id, <name>, cf)` where name is one of:

`structuring`, `rapid_pass_through`, `round_tripping`, `mule_account`,
`cash_intensive_layering`, `third_party_funding`, `dormant_reactivation`, `pep_misuse`,
`sanctions_evasion`, `gambling_cycling`.

Typologies are hypotheses about *pattern*, never about intent. The system asserts that
behaviour is consistent with structuring; it never asserts that a customer intended to
structure, because intent is not observable from transaction data.

### L3, Assessment

| Predicate | Values |
|---|---|
| `typology_support` | none \| weak \| moderate \| strong |
| `composite_risk` | low \| moderate \| high \| severe |
| `evidence_sufficiency` | sufficient \| partial \| insufficient |
| `conflict_state` | none \| soft \| irreconcilable |
| `scope_state` | in_scope \| boundary \| out_of_scope |
| `missing_premise` | names a mandatory premise that could not be established (multi-valued) |
| `out_of_scope_reason` | names why the case is outside competence (multi-valued) |
| `disposition_blocked` | names an outcome a prohibition forbids for this case (multi-valued) |

`disposition_blocked` sits one layer below the disposition on purpose. A prohibition is a
statement about the case's posture, not itself a disposition, and keeping it below the
disposition layer means no disposition rule ever has to read another disposition fact, which keeps the disposition layer free of same-layer dependencies and therefore of cycles.

### L4, Posture

| Predicate | Values |
|---|---|
| `composite_risk` | low \| moderate \| high \| severe |
| `disposition_blocked` | names an outcome a prohibition forbids (multi-valued) |

`composite_risk` is the one assessment that depends on another: it reads
`typology_support`. Two predicates where one derives from the other cannot share a layer
without permitting same-layer reads and the cycles that come with them, which is why the
model runs to six layers rather than the five originally specified. This was discovered
while writing the rules, not designed in advance.

### L5, Disposition

`disposition(alert_id, <outcome>, rationale, required_evidence[])`

`required_evidence` is populated from the contrastive explanation search (M6) and is what
makes `request_evidence` actionable rather than vague.

### Chaining map

```
L0 asserted facts
   │
   ├─ arithmetic / temporal / graph predicates
   ▼
L1 indicators ────────────┐
   │                      │ (one indicator may feed several typologies)
   ▼                      ▼
L2 typology hypotheses (cf)
   │
   ▼
L3 typology_support ─┬─ composite_risk ─┬─ evidence_sufficiency
                     │                  │
                     └── conflict_state ─┴── scope_state
                                │
                                ▼
L4                         disposition
```

### 4a. Premise policy

"Premises must be at a lower layer than the conclusion" sounds sufficient and is not. It
still permits a Layer 4 rule to read a raw measurement and emit a disposition, which is
exactly the flat lookup table the layering exists to prevent. So the permitted reads are
declared explicitly per layer and enforced when a rule is constructed:

| A rule concluding at | may read premises from | because |
|---|---|---|
| L1 indicators | L0 only | an indicator names an observation about raw data |
| L2 typologies | L1 only | a hypothesis is built from named observations, never from a bare number |
| L3 assessment | L1 and L2 | evidence sufficiency can rest on an indicator alone (a documentation gap) with no typology involved, so this layer is allowed to skip |
| L4 posture | L1, L2 and L3 | `composite_risk` is downstream of `typology_support`, which is why the two cannot share a layer |
| L5 disposition | L3 and L4 only | nothing decides an outcome from raw data, from a bare indicator, or from another disposition |

This was originally specified as the weaker "strictly lower" rule and the gap was caught by
the test written to prove it worked, the test asserting that a Layer 4 rule reading
`credit_count` is rejected failed, because it wasn't. Recorded here because the weaker
version is the intuitive one to write, and it does not do the job.

---

## 5. Certainty factor algebra

MYCIN-style, chosen for transparency rather than probabilistic soundness.

| Operation | Formula |
|---|---|
| Conjunction of premises | `cf = min(cf_i)` |
| Disjunction of premises | `cf = max(cf_i)` |
| Rule conclusion | `cf = rule.strength × cf(premises)` |
| Two positive cf for same fact | `cf = cf₁ + cf₂(1 − cf₁)` |
| Two negative cf | `cf = cf₁ + cf₂(1 + cf₁)` |
| Mixed signs | `cf = (cf₁ + cf₂) / (1 − min(\|cf₁\|, \|cf₂\|))` |
| Noise floor | facts with `\|cf\| < 0.20` are not asserted |

### The honest caveat

Certainty factors are not probabilities. They assume premise independence that rarely holds,
the combination function is not derivable from probability theory, and Heckerman's analysis
showed the scheme is only coherent under restrictive conditions. They are used here because a
human can read `0.7` off a rule and understand where it came from, which matters more in an
auditable system than formal correctness.

This is exactly why the Bayesian comparison exists as an ablation rather than as a footnote:
the claim being tested is that the transparency is worth the unsoundness, and that claim
should be measured rather than asserted.

---

## 6. Outcome semantics

The formal preconditions. Evaluation is ordered, and the order is itself a design claim.

| Precedence | Stage | Fires when | Outcome |
|---|---|---|---|
| 1 | **Mandatory escalation** (veto) | `sanctions_signal(confirmed)` or any statutory trigger | `refer_to_investigation` |
| 2 | **Prohibition** (veto) | would-be `clear` while `composite_risk ∈ {high, severe}` | blocks the clear, falls through |
| 3 | **Epistemic boundary** (meta) | `scope_state(out_of_scope)` ∨ `conflict_state(irreconcilable)` ∨ any mandatory premise unknown | `refuse_to_decide` |
| 4 | **Authority boundary** | `typology_support ∈ {moderate, strong}` ∧ `evidence_sufficiency(sufficient)` ∧ `conflict_state ∈ {none, soft}` | `refer_to_investigation` |
| 5 | **Evidence gathering** | `typology_support ∈ {moderate, strong}` ∧ `evidence_sufficiency(partial)` | `request_evidence` |
| 6 | **Watchful close** | `composite_risk(moderate)` ∧ `typology_support(weak)` | `monitor` |
| 7 | **Close** | `composite_risk(low)` ∧ `typology_support(none)` ∧ `evidence_sufficiency(sufficient)` | `clear` |
| 8 | **Deficiency fallthrough** | nothing above fired | `refuse_to_decide` |

Three consequences of this ordering worth stating explicitly, because each is a deliberate
decision rather than an artefact:

**Mandatory escalation outranks abstention.** A confirmed sanctions match on an out-of-scope
case still escalates. Abstaining on a confirmed match would itself be unlawful inaction, so
the veto layer is permitted to push a case *through* an abstention, but only ever in the
direction of more human attention.

**The veto layer can never force a `clear`.** It can escalate, and it can block, but it has
no power to resolve uncertainty downwards. This asymmetry is the whole point of having it.

**Silence is a refusal, not a pass.** If no disposition rule fires, the outcome is
`refuse_to_decide` with reason `deficiency`, and the anomaly auditor treats a case reaching
stage 8 as a coverage gap in the knowledge base. Most rule engines fail open or fail silent;
this one fails loud.

### The two deferrals, formally

| | `refer_to_investigation` | `refuse_to_decide` |
|---|---|---|
| Belief formed? | Yes, the system knows what it is looking at | No |
| Why a human? | Only the MLRO holds the authority to report | The knowledge base cannot support a view |
| Preconditions | typology support with sufficient evidence, no irreconcilable conflict, in scope | out of scope, irreconcilable conflict, missing mandatory premise, or no rule fired |
| Reported as | a rationale and the supporting proof tree | the specific reason it could not decide |

A `refuse_to_decide` always names which of the four reasons applies. An unexplained "no decision"
would be useless to the analyst receiving it.

---

## 7. Meta-layer mechanics

### Scope conditions

A case is `out_of_scope` if it instantiates a scope-marker frame (`CryptoTransfer`,
`TrustCustomer`), involves an excluded typology's prerequisites (trade documentation,
correspondent relationships), or references a `Jurisdiction` with `fatf_status(unknown)`
where jurisdiction is load-bearing for the decision. `boundary` marks cases that are
in scope but sit near an exclusion, and are allowed to proceed with a recorded caveat.

### Conflict detection

Conflict is defined over incompatible values of the same L3 predicate:

| Condition | State |
|---|---|
| Two rules assert incompatible values, `\|cf₁ − cf₂\| < 0.15` | `irreconcilable` |
| Two rules assert incompatible values, `\|cf₁ − cf₂\| ≥ 0.15` | `soft`: resolve to the higher cf, record the dissent |
| No incompatibility | `none` |

Soft conflicts are resolved but never discarded: the losing conclusion appears in the
explanation as a recorded dissent, so an analyst can see the system nearly decided
otherwise. Irreconcilable conflict is the most interesting abstention trigger, because it is
the case where a flat scorer would confidently average two incompatible readings into a
meaningless middle.

### Mandatory premises

Registered as mandatory; unknown values here force abstention:

`sanctions_signal` (must not be `not_checked`), `kyc_status` (must not be `unknown`),
`customer_type`, a non-empty transaction set, and `expected_monthly_turnover` for any rule
depending on `turnover_deviation`.

---

## 8. Veto layer

| Kind | Behaviour |
|---|---|
| Mandatory escalation | Forces `refer_to_investigation` regardless of computed posture |
| Prohibition | Forbids specific dispositions in specific states; blocks and falls through |
| Human override | An MLRO decision supplied with the case; overturns any machine disposition |

Overrides are recorded rather than silently applied: the case result retains the machine
disposition, the override, and the reason. That record is a calibration signal, a pattern of
overrides in one direction is evidence the rule base is miscalibrated, and it feeds the
refinement log rather than disappearing.

---

## 9. Rule metadata schema

```python
Rule(
    id="TYP-STRUCT-01",
    layer=2,
    priority=50,
    strength=0.70,
    when=[
        Has("deposit_frequency", "$alert", In("elevated", "extreme")),
        Has("threshold_proximity", "$alert", "high"),
    ],
    then=Conclude("typology", "$alert", "structuring"),
    source="FATF structuring typology; JMLSG Part I risk factors",
    provenance="reconstructed",
    rationale="Deposits clustered below a review threshold, repeated within a short "
              "window, are consistent with deliberate splitting of a larger sum.")
```

| Field | Purpose |
|---|---|
| `id` | Stable identifier used in traces, tests and the provenance index |
| `layer` | Enforced: premises must come from a lower layer than the conclusion |
| `priority` | Conflict resolution tiebreak after specificity |
| `strength` | The cf attached to the conclusion |
| `source` | Free text naming the document; required |
| `provenance` | `statutory` \| `guidance` \| `reconstructed`; required |
| `rationale` | Human-readable; rendered directly in explanations |

`rationale` is not a comment. It is the sentence the explanation facility shows a human, so
it is written for an analyst rather than for a developer.

### Conflict resolution strategy

Applied in order: **specificity** (more premises wins) → **priority** (explicit) →
**recency** (most recently asserted premise) → **rule id** (deterministic tiebreak, so runs
are reproducible).

---

## 10. Case file format

TOML rather than YAML, read with the standard library's `tomllib`. This keeps the core
dependency-free, which matters more for a project meant to be cloned and run than the
marginal readability YAML would buy.

```toml
alert_id = "ALT-0007"
trigger_rule = "TM-CASH-AGG"
window = { start = 2026-03-01, end = 2026-03-07 }

[customer]
customer_id = "CUS-1183"
customer_type = "retail"
onboarding_date = 2026-02-08
expected_monthly_turnover = 2200
kyc_status = "complete"
sanctions_signal = "none"
source_of_funds_evidence = "absent"

[[accounts]]
account_id = "ACC-9001"
account_type = "current"
opened_date = 2026-02-08
balance = 410

[[transactions]]
txn_id = "T1"
amount = 2400
direction = "in"
channel = "branch"
timestamp = 2026-03-01T10:14:00

# ... 13 further deposits

[expected]
disposition = "request_evidence"
must_fire = ["IND-CASH-01", "IND-CASH-02", "TYP-STRUCT-01"]
notes = "Structuring on an immature account; evidence incomplete, so ask before escalating."
```

The `expected` block makes every case simultaneously documentation and a test. TOML dates
and datetimes parse natively, so no date handling is needed at the loader boundary.

---

## 11. Worked example

Case `ALT-0007` above: 14 cash deposits of £2,400 over six days, account opened 21 days
earlier, expected monthly turnover £2,200, no source-of-funds evidence.

```
L0  asserted      14 × CashDeposit(2400, branch); onboarding 2026-02-08;
                  expected_monthly_turnover 2200; source_of_funds_evidence absent;
                  sanctions_signal none; kyc_status complete

L1  IND-CASH-01   14 deposits / 6 days          -> deposit_frequency(extreme)      cf 1.00
    IND-CASH-02   2400 vs 3000 review threshold -> threshold_proximity(high)       cf 1.00
    IND-CASH-04   33600 aggregate vs 2400 max   -> aggregation_gap(present)        cf 1.00
    IND-ACCT-01   21 days since onboarding      -> account_immaturity(true)        cf 1.00
    IND-TURN-01   33600 vs 2200 expected        -> turnover_deviation(far_above)   cf 1.00
    IND-DOC-01    source_of_funds absent        -> documentation_gap(source_of_funds)

L2  TYP-STRUCT-01 deposit_frequency ∧ threshold_proximity
                                                -> typology(structuring)           cf 0.70
    TYP-STRUCT-02 + aggregation_gap uplift      -> typology(structuring)           cf 0.85
    TYP-MULE-01   account_immaturity ∧ turnover_deviation
                                                -> typology(mule_account)          cf 0.45

L3  POS-SUP-01    max typology cf 0.85          -> typology_support(strong)
    POS-RISK-02   strong support ∧ far_above    -> composite_risk(high)
    POS-EVID-02   documentation_gap present     -> evidence_sufficiency(partial)
    POS-CONF-01   no incompatible L3 assertions -> conflict_state(none)
    POS-SCOPE-01  no scope markers              -> scope_state(in_scope)

L4  stage 1       no statutory trigger, not fired
    stage 3       in scope, no conflict, mandatory premises known, not fired
    stage 4       evidence_sufficiency is partial, not sufficient, not fired
    stage 5       strong support ∧ partial evidence
                                    -> request_evidence
                                       required: source_of_funds (cheapest flip to clear)
```

Note the outcome: not `refer_to_investigation`, because the evidence is incomplete and the
cheapest way to resolve the case is to ask. The contrastive search supplies *what* to ask
for. If source-of-funds evidence then arrives and is inconsistent with the deposits,
`evidence_sufficiency` becomes `sufficient`, stage 4 fires, and the case escalates with a
far stronger narrative than it would have had at first pass.

### Second example, abstention

Same case, but `sanctions_signal` is `not_checked` and one deposit is a `CryptoTransfer`.

```
L1  IND-SCOPE-02   CryptoTransfer instantiated  -> unsupported_instrument(present)
L3  META-SCOPE-02  unsupported_instrument       -> scope_state(out_of_scope)
L4  stage 3        out of scope ∧ mandatory premise unknown
                             -> refuse_to_decide
                                reasons: [out_of_scope(crypto), missing_premise(sanctions_signal)]
```

No disposition is guessed, both reasons are reported, and the analyst knows exactly what
would need to change for the system to be able to help.


---

## 12. What building the rule base changed

Three revisions forced by implementation, recorded here because a specification that is
quietly edited to match the code is worth less than one that says where it was wrong.

**The layer model grew from five levels to six.** `composite_risk` reads
`typology_support`, so the two cannot sit on one layer without permitting same-layer reads.
Splitting assessment (L3) from posture (L4) keeps the dependency graph acyclic and made the
premise policy stricter rather than looser.

**Three meta-level assessments are functions, not production rules.** `typology_support`,
`conflict_state` and `missing_premise` each quantify over the whole fact base, *the
strongest* typology, *any two* incompatible conclusions, *every* mandatory premise.
Production rules match individual facts and cannot express aggregation or universal
quantification without an explosion of hand-maintained guard rules. This is a well-known
limitation of production systems, and naming it is more honest than pretending the rule
formalism covers everything. The thresholds those functions use remain data.

**The disposition layer is a decision list rather than a rule set.** Outcome precedence is
inherently ordered. Encoding that order into unordered production rules requires every lower
stage to carry explicit guards against every higher one, roughly tripling the premise count
while adding no knowledge, and creating a hazard where inserting a stage silently invalidates
the guards below it. A decision list is itself a knowledge representation formalism: each
stage keeps the same metadata as a rule, the conditions are the same objects evaluated by the
same matcher, and the firing stage is recorded with its premises. Only first-match-wins is
added.
