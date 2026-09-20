# 02. Knowledge Acquisition

How the knowledge in this system was obtained, and where every piece of it came from.

---

## 1. The constraint

Classical knowledge engineering assumes access to a domain expert who can be interviewed,
observed and contradicted. No AML compliance officer was available for this project, so the
usual elicitation techniques, structured interview, think-aloud protocol, card sorting
against real case files, were not possible.

Rather than invent plausible-sounding rules, the knowledge was acquired by **structured
document analysis** of authoritative published sources. This is a recognised substitute when
expertise is codified in regulation and industry guidance, which in AML it unusually is: the
domain is one where experts are *obliged* to write down how they reason.

The trade-off is explicit and worth stating plainly:

| Document analysis provides | An expert would have provided |
|---|---|
| Rules traceable to a citable source | Tacit knowledge that never reaches guidance documents |
| Coverage of what regulators require | A sense of which alerts are *actually* wasting analysts' time |
| Reproducibility, anyone can check a rule against its source | Calibrated thresholds from real case outcomes |
| No access limits, no availability problem | Correction of misreadings in real time |

The most significant consequence is **threshold calibration**. Published guidance describes
the *shape* of suspicious behaviour but rarely gives numeric cut-offs, because firms are
expected to set them against their own risk appetite. Every numeric threshold in this system
is therefore an illustrative reconstruction, marked as such in
[`reference.py`](../src/triagex/kb/reference.py), and the evaluation deliberately tests
sensitivity to them rather than pretending they are authoritative.

## 2. Sources used

All verified as of September 2026.

| Source | What it supplied | Currency |
|---|---|---|
| [POCA 2002 s.330](https://www.legislation.gov.uk/ukpga/2002/29/section/330) | The disclosure duty, the objective "reasonable grounds" test, the regulated-sector scope (Sch. 9) | In force |
| [MLR 2017 (SI 2017/692)](https://www.legislation.gov.uk/uksi/2017/692) | Customer due diligence, enhanced due diligence triggers, record keeping, beneficial ownership | Made 22 Jun 2017, in force 26 Jun 2017, since amended |
| [JMLSG Guidance Part I](https://www.jmlsg.org.uk/guidance/current-guidance/) | MLRO role and responsibilities (Ch. 3), risk-based approach, data protection constraints on handling case data (Ch. 6) | June 2023, updated Aug 2025; Ch. 3 and 6 revisions published 4 Feb 2026, pending HM Treasury approval |
| [FCA Financial Crime Guide](https://handbook.fca.org.uk/handbook/fcg1) | Control expectations, self-assessment framing, AI assurance expectations | Updated April 2025 |
| [Wolfsberg Group MSA Statement, Part I](https://wolfsberg-group.org/resources/168/) | The distinction between threshold-based transaction monitoring and behaviour/typology-based monitoring for suspicious activity | July 2024 (Part II, *Transitioning to Innovation*, August 2025) |
| [FATF Recommendations](https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations.html) | Risk-based approach, higher-risk jurisdiction concept, EDD principles | Recommendations amended June 2026; R.1 and its Interpretive Note updated June 2025 |
| NCA / UKFIU SAR guidance | SAR narrative expectations, glossary codes (`XX` prefix, multiple codes permitted, placed in the reason-for-suspicion text) | Current |

### Academic sources for the architecture

The abstention mechanism is not an AML idea, it comes from the classification literature,
and the project is stronger for saying so rather than presenting it as novel.

| Source | Contribution |
|---|---|
| Chow, C.K. (1970) 'On optimum recognition error and reject tradeoff', *IEEE Transactions on Information Theory* | The original error/reject trade-off: abstention as a cost-optimal decision, not a failure |
| El-Yaniv, R. and Wiener, Y. (2010) 'On the foundations of noise-free selective classification', *JMLR* | The risk, coverage framing this project's headline evaluation curve uses |
| [Hendrickx et al., 'Machine Learning with a Reject Option: A Survey'](https://arxiv.org/pdf/2107.11277) | Taxonomy of rejection strategies; useful for positioning a rule-based reject option against learned ones |
| Preece, A. and Shinghal, R., rule-base verification | The anomaly classes the auditor in [`verify/anomalies.py`](../src/triagex/verify/anomalies.py) detects: redundancy, conflict, circularity, unreachability, deficiency |

## 3. Method

Four passes over the source material.

**Pass 1, Concept extraction.** Read for *nouns*: the entities the domain talks about, and
the attributes it cares about. These became the frame hierarchy, `Customer`, `Account`,
`Transaction`, `Counterparty`, `Jurisdiction`, `Alert`: and their slots. Guidance documents
are rich in this: MLR 2017 alone defines customer types, risk factors and the circumstances
requiring enhanced due diligence.

**Pass 2, Indicator extraction.** Read for *observations*: things guidance describes as
noteworthy about behaviour. These became Layer 1 indicator rules. Indicators are
deliberately judgement-free, they report what is observably true, not what it means.

**Pass 3, Typology reconstruction.** Read for *explanations*: named patterns that guidance
and typology reports treat as recognisable laundering methods. These became Layer 2 rules
mapping indicator combinations to hypotheses with certainty factors. This is where the
Wolfsberg TM/MSA distinction became the organising principle: the boundary between Pass 2
and Pass 3 is exactly Wolfsberg's boundary between transactional anomaly and suspicious
activity.

**Pass 4, Scope and duty extraction.** Read for *limits*: what the firm must do regardless
of its own assessment (mandatory escalation), what it may never do, and who holds which
authority. These became the Layer 4 veto and constraint rules. POCA s.330 and the JMLSG
MLRO provisions did most of the work here.

### Worked example: from source text to rule

The source statement, paraphrased from the structuring typology as described in published
typology material:

> Deposits are made in amounts deliberately kept below a reporting or internal review
> threshold, often over a short period and across multiple branches or channels, in order
> to avoid the scrutiny a single larger deposit would attract.

This decomposes into four separate observations plus one hypothesis, which is why it becomes
five rules across two layers rather than one big rule:

```
L1  IND-CASH-01   many deposits in a short window        -> deposit_frequency(elevated)
L1  IND-CASH-02   amounts clustered just under a         -> threshold_proximity(high)
                  threshold
L1  IND-CASH-03   multiple channels or locations used    -> channel_dispersion(present)
L1  IND-CASH-04   aggregate far exceeds any single       -> aggregation_gap(present)
                  deposit
L2  TYP-STRUCT-01 deposit_frequency(elevated) AND        -> typology(structuring, cf 0.7)
                  threshold_proximity(high)
                  [+ cf uplift from IND-CASH-03/04]
```

Splitting it this way is what gives the system its chaining depth, and it means an indicator
can support more than one typology. `threshold_proximity` also contributes to
`third_party_funding`, which a single monolithic structuring rule could never express.

The cost of the approach is visible here too: *"deliberately"* and *"in order to avoid
scrutiny"* are statements about intent, which no rule over transaction data can observe.
The system infers a pattern consistent with structuring and says so in exactly those terms.
Claiming to detect intent would be the kind of overreach that makes expert systems in this
domain untrustworthy.

## 4. Provenance policy

Every rule in the knowledge base carries a `source` field in its metadata naming the
document and, where applicable, the section or typology it derives from. This is enforced, a rule without provenance fails the test suite.

Three provenance categories, distinguished honestly because they carry different weight:

| Category | Meaning | Example |
|---|---|---|
| `statutory` | Derived from legislation or regulation | Mandatory escalation on a sanctions match |
| `guidance` | Derived from JMLSG / FCA / FATF / Wolfsberg material | EDD triggers, risk-based weighting |
| `reconstructed` | Shape from published typologies, numbers set for this project | All numeric thresholds, all certainty factors |

`reconstructed` is the largest category and the docs say so up front. Pretending otherwise
would be the single easiest thing for a knowledgeable reader to discredit, whereas a clearly
labelled reconstruction is a defensible engineering choice.

## 5. What this knowledge base cannot know

Recorded here because the meta-rules in Layer 3 are built directly from this list, each
limitation becomes a scope condition that can trigger `refuse_to_decide`.

| Limitation | Consequence in the system |
|---|---|
| No trade documentation model | Trade-based laundering cases are out of scope and must abstain |
| No chain analytics | Crypto on/off-ramp cases are out of scope and must abstain |
| No beneficial-ownership graph | Complex corporate structures cannot be assessed |
| No customer contact or explanation | A plausible innocent explanation cannot be tested, only requested |
| No historical outcome data | Certainty factors are elicited from guidance, not calibrated on outcomes |
| No live sanctions or PEP list | Matches are simulated against illustrative fixtures |
| Intent is unobservable | The system reports patterns consistent with a typology, never intent |

---

## 6. Rule provenance index

Populated as the knowledge base is built (M3). Every rule ID appears here with its source.

| Rule ID | Layer | Provenance category | Source |
|---|---|---|---|
| _to be completed at M3_ | | | |
