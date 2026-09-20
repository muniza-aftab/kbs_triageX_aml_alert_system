# 01. Domain Primer

Anti-money-laundering (AML) alert triage, for a reader who has never worked in financial
crime. If you already know the domain, skip to
[02. Knowledge Acquisition](02-knowledge-acquisition.md).

---

## What the problem actually is

A UK bank is legally obliged to watch its own customers' transactions for signs of money
laundering. Software flags anything that looks unusual, and each flag becomes an **alert**.
A human analyst then has to decide what the alert means.

The decision is not "is this person a criminal". It is narrower and more procedural:

> Given the available information, does this warrant closing, watching, asking the customer a
> question, or handing to someone with the authority to report it?

The volume problem is what makes this interesting. Industry transaction-monitoring systems
are widely reported to produce false-positive rates well above 90%, the overwhelming
majority of alerts are innocent behaviour that happened to match a threshold. Analysts spend
most of their time closing alerts that were never going to matter, which is exactly the
environment where a system that is *confidently wrong* does real damage in both directions:
a wrongly cleared alert lets laundering through, and a wrongly escalated one can freeze an
innocent customer's account.

## The legal shape of the decision

Three features of UK law determine the architecture of any system in this space.

**1. The reporting duty is personal and criminal, not corporate and administrative.**
Under [section 330 of the Proceeds of Crime Act 2002](https://www.legislation.gov.uk/ukpga/2002/29/section/330),
a person working in the regulated sector commits a criminal offence by *failing* to disclose
money laundering they knew or suspected. So the pressure runs towards over-reporting: the
individual analyst's risk is asymmetric.

**2. The legal test is objective, not subjective.** Section 330(2)(b) introduces a
negligence limb, the offence is committed where someone had *reasonable grounds* for
knowing or suspecting, even if they did not personally suspect. This matters enormously for
system design, and is the single strongest argument for this project's central feature:

> If the standard is what a reasonable person *should* have suspected given the
> information, then a system that quietly resolves its own uncertainty into a clean
> `clear` is creating legal exposure. Surfacing "the evidence here is contradictory and no view
> can be formed" is not a weakness of the system. It is the legally honest output.

**3. Only a specific human can file the report.** Firms appoint a **Money Laundering
Reporting Officer (MLRO)**, whose role is set out in the
[JMLSG Guidance](https://www.jmlsg.org.uk/guidance/current-guidance/) (Part I, Chapter 3, revised again in February 2026 specifically to sharpen the MLRO's oversight and monitoring
responsibilities). The MLRO decides whether a **Suspicious Activity Report (SAR)** goes to
the National Crime Agency. No amount of software confidence can substitute for that
decision.

This is why the system distinguishes two kinds of deferral. Handing a case to the MLRO
because only they can lawfully act on it is an **authority boundary**. Declining to form a
view because the knowledge base cannot support one is an **epistemic boundary**. Collapsing
these into a single "escalate" outcome loses the distinction that the law itself draws.

## The lifecycle a case moves through

```
   transactions
        |
        v
  [ monitoring rules ]  ---->  ALERT  ---->  analyst triage  ---->  disposition
   thresholds, patterns                      (what this project models)
                                                     |
                                       +-------------+-------------+
                                       |             |             |
                                    close        request        refer to
                                  / monitor      evidence     MLRO / SAR
                                                                   |
                                                                   v
                                                           NCA (UKFIU)
```

This project models the **triage** step: alert in, disposition out, with the reasoning
exposed.

## Why the reasoning has to be visible

Three converging pressures, all of which favour a system that can explain itself in terms a
human can audit:

- **A SAR may have to survive scrutiny.** The reason-for-suspicion narrative is the part
  that matters, and the National Crime Agency asks reporters to be specific rather than
  generic, using structured glossary codes (prefixed `XX`) in the narrative text.
  A disposition that cannot articulate *why* produces a weak SAR.
- **The regulator now asks about AI assurance directly.** The FCA's
  [Financial Crime Guide](https://handbook.fca.org.uk/handbook/fcg1), updated in April 2025,
  extended its expectations into AI assurance alongside risk management and KYC
  remediation. "The model said so" is not an answer a firm can give.
- **Automated decisions about individuals are regulated.** GDPR Article 22 and Recital 71
  constrain purely automated decision-making with significant effects on a person. Note the
  careful claim here: AML transaction monitoring is **not** itself listed in Annex III of
  the EU AI Act, credit scoring and insurance pricing are. The argument for explainability
  in this domain rests on GDPR, FCA expectations and SAR defensibility, not on the AI Act.
  Overclaiming that would be an easy thing for a knowledgeable reader to catch.

## Transaction monitoring versus monitoring for suspicious activity

The Wolfsberg Group, a coalition of large international banks that publishes AML good
practice, drew a distinction in its 2024 *Statement on Effective Monitoring for Suspicious
Activity* that directly shapes this project's design.

| | Transaction Monitoring (TM) | Monitoring for Suspicious Activity (MSA) |
|---|---|---|
| Basis | Rules and thresholds | Behaviour, typologies, context |
| Looks at | Transactional anomalies | Transactions *plus* customer profile, risk indicators, known patterns |
| Failure mode | Alerts on anything unusual | Requires richer knowledge to work at all |

Wolfsberg's point is that threshold-based TM is necessary but insufficient, and that firms
should move towards the broader MSA posture. That is an argument about knowledge
representation, even though it is not phrased as one:

> A flat threshold rule (`amount > 10000 -> alert`) encodes no knowledge about *why* that
> amount is interesting. A typology (`structuring`) encodes a hypothesis about intent, which
> can be supported or undermined by other evidence.

This is precisely the distinction between Layer 1 and Layer 2 in this system's architecture.
The indicator layer notices that deposits cluster below a threshold; the typology layer
proposes that this constitutes structuring, with a certainty factor that other evidence can
raise or lower.

## The typologies modelled

Recognised laundering patterns, each drawn from published typology material (provenance in
[02](02-knowledge-acquisition.md)):

| Typology | Shape of the behaviour |
|---|---|
| Structuring / smurfing | Splitting a large sum into many deposits below a reporting or review threshold |
| Rapid pass-through | Funds arrive and leave almost immediately, leaving little balance |
| Round-tripping | Money returns to its origin through intermediaries, creating apparent trading |
| Mule networks | Many low-value accounts funnelling into a hub, often newly opened |
| Cash-intensive layering | A legitimate cash business used to mix illicit funds with real takings |
| Third-party funding | Deposits from unconnected parties with no plausible relationship |
| Dormant reactivation | A long-inactive account suddenly used for high-value flows |
| PEP / sanctions exposure | Involvement of a politically exposed person or a designated party |
| Gambling cycling | Funds cycled through betting activity to manufacture a clean source |

### Deliberately out of scope

| Excluded | Why |
|---|---|
| Trade-based laundering | Requires trade documentation, invoices and pricing benchmarks this system has no model of |
| Crypto on/off-ramps | Needs chain analytics; a different evidence base entirely |
| Correspondent banking | Nested relationships and downstream customers are not modelled |
| Trust and company service provider structures | Beneficial-ownership chain reasoning is out of scope |

These exclusions are load-bearing, not an admission. A system claiming universal coverage
cannot have a meaningful `refuse_to_decide` outcome, because there is nothing it recognises
as outside its own competence. Out-of-scope cases in the test library exist specifically to
prove the scope-condition meta-rules fire.

## What this system is not

- Not a detection engine. It triages alerts; it does not generate them from raw transaction
  feeds.
- Not trained on real data. All cases are synthetic or hand-constructed.
- Not a compliance product. Thresholds and jurisdiction lists are illustrative, no live
  sanctions list is embedded, and nothing here should be used to make a real decision about
  a real person.
- Not a machine-learning model. The reasoning is symbolic and inspectable by design;
  the rationale is in [08. Design Decisions](08-design-decisions.md).

---

## Sources

- [Proceeds of Crime Act 2002, s.330, Failure to disclose: regulated sector](https://www.legislation.gov.uk/ukpga/2002/29/section/330)
- [The Money Laundering, Terrorist Financing and Transfer of Funds (Information on the Payer) Regulations 2017 (SI 2017/692)](https://www.legislation.gov.uk/uksi/2017/692)
- [JMLSG, Current Guidance](https://www.jmlsg.org.uk/guidance/current-guidance/) (Part I, June 2023, updated August 2025; further revisions to Chapters 3 and 6 published February 2026)
- [FCA Financial Crime Guide (FCG)](https://handbook.fca.org.uk/handbook/fcg1), updated April 2025
- [Wolfsberg Group, Statement on Effective Monitoring for Suspicious Activity, Part I: Moving Beyond Automated Transaction Monitoring](https://wolfsberg-group.org/resources/168/) (July 2024)
- [FATF Recommendations](https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations.html)
