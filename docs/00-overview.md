# 00. Overview, without the jargon

For anyone who needs to understand what this system does and whether to trust it, without
reading code. If you want the technical detail, start at
[01. Domain primer](01-domain-primer.md) instead.

---

## The problem

A bank is legally required to watch its customers' transactions for signs of money laundering.
Software flags anything unusual, and each flag becomes an **alert**. Someone then has to decide
what that alert means.

The volume is the difficulty. Industry monitoring systems are widely reported to produce false
alarms in well over nine cases out of ten, so analysts spend most of their time closing alerts
that were never going to matter. That is exactly the environment where a confident wrong answer
does real damage in both directions: a wrongly closed alert lets laundering through, and a wrongly
escalated one can freeze an innocent person's account.

This system does that first assessment and recommends one of five actions.

---

## The five decisions

| Decision | What it means |
|---|---|
| **Close the alert** | Nothing needs further attention, and the customer file is complete. |
| **Close, with monitoring** | Something is faintly unusual, but not enough to take up an investigator's time. |
| **Request evidence** | A pattern is supported, but a specific document is missing. The system works out *which* one to ask for. |
| **Refer to an investigator** | The evidence is complete and supports a recognised pattern. Only a person with reporting authority can decide what happens next. |
| **Cannot decide** | The system cannot form a view, and says specifically why. |

---

## The idea the whole thing is built around

Most systems of this kind must produce an answer. This one distinguishes **two different reasons
for handing a case to a person**, because they need different responses:

- **Refer to an investigator** is a question of *authority*. The system knows exactly what it is
  looking at. It is confident. But only the Money Laundering Reporting Officer can lawfully
  authorise a report, so the system defers.
- **Cannot decide** is a question of *knowledge*. Something is outside what the system can assess,
  or a required check was never done, or the evidence points both ways. No view is possible.

### Why declining is a feature and not a cop-out

Under UK law the test for suspicion is **objective**. Section 330 of the Proceeds of Crime Act
2002 makes it an offence to fail to disclose money laundering where a person had *reasonable
grounds* to suspect it, whether or not they actually suspected anything.

So what matters is what a reasonable person should have concluded from the information available.
A system that quietly turns its own uncertainty into a clean "close the alert" has not removed
that uncertainty; it has hidden it, while the legal standard still applies to the firm. Saying
*"no view can be formed here, and this is why"* leaves a human able to meet that standard.

**And it was measured, not assumed.** Across 500 test cases, forcing the system to answer every
one made its decisions **3.5 times more costly** once errors are weighted by how much harm they
cause. A conventional scoring model built from the same signals did **seven times worse**, and
missed 21 cases that should have been referred against this system's 2.

---

## How it reaches a decision

It works up through stages rather than jumping straight from facts to a verdict. Each stage may
only read from the stages below it, and a rule that tries to skip ahead is rejected before the
system will even start.

1. **Measurements**: plain arithmetic. How many payments, how large, how fast the money left.
2. **Observations**: named things that are true. *"Payments cluster just under a review
   threshold."* No interpretation yet.
3. **Patterns**: recognised laundering methods the observations match, each with a strength.
4. **Assessment**: is the evidence complete? Is any of this outside what the system can judge?
   Does a legal obligation apply?
5. **Risk**: the overall posture.
6. **Decision**: one of the five actions, by a fixed order of precedence.

A worked example:

> **Facts.** Fourteen cash deposits of £2,400 over six days. Account opened three weeks ago. No
> evidence on file of where the money came from.
>
> **Observations.** Deposit frequency is extreme. Each deposit sits just under the £3,000 review
> threshold. The total is far larger than any single deposit. The account is too new to have a
> normal pattern.
>
> **Pattern.** Strongly consistent with splitting deposits to stay under a threshold.
>
> **Assessment.** Evidence incomplete: the source of the money is undocumented. Everything else
> is assessable.
>
> **Decision.** Request evidence. Specifically, source-of-funds documentation, because that is the
> least intrusive thing that would settle it.

### Why the stages matter

The easy way to build this is one large table: inputs in, verdict out. That is also the least
useful way, because nobody can tell *why* it said what it said, and partial conclusions cannot be
expressed at all. The staged approach means every conclusion can be traced back through named
rules to the facts that produced it.

---

## Three things it does that are worth knowing about

**It works out what to ask for.** When the system requests evidence it has not picked from a fixed
list. It searches every combination of evidence the bank could obtain, weighs each by effort and
by how intrusive it is for the customer, and returns the cheapest combination that would actually
change the decision. A quick internal sanctions screen is preferred over a customer interview
unless only the interview would settle it.

**It can explain why it did *not* do something.** The useful question is rarely "why did you say
that" but "why didn't you close it". That cannot be answered by showing the reasoning it *did*
use, because the answer is about something absent. Every assessment lists each decision it could
have reached and what specifically stopped it. For example: *"Evidence on file is Incomplete,
and would need to be Complete."*

**It checks its own rules.** A separate tool inspects the rule base for defects no individual test
case would reveal: two rules that contradict each other, a rule that can never fire, a conclusion
nothing can reach. It has found real problems, the most instructive being a rule that recorded a UK
public figure as a foreign one. Every case still produced a defensible decision, so no test caught
it; the error was in what a fact *meant*, not in any outcome.

---

## Where the knowledge comes from

The rules are derived from published material rather than invented: the Proceeds of Crime Act 2002,
the Money Laundering Regulations 2017, guidance from the Joint Money Laundering Steering Group and
the Financial Conduct Authority, and typology work from the Financial Action Task Force and the
Wolfsberg Group.

Every rule records its source and how directly it derives from it:

| | |
|---|---|
| **From legislation** | A confirmed sanctions match must always be escalated. |
| **From published guidance** | What "splitting deposits" looks like in practice. |
| **Reconstructed** | The shape comes from guidance; the numbers were chosen for this project. |

**Reconstructed is the largest group**, and saying so plainly matters. Published guidance describes
what suspicious behaviour looks like but deliberately leaves the actual thresholds to each firm's
risk appetite, so there was nothing to copy. Every number in this system was chosen to be
plausible. A clearly labelled reconstruction is defensible; an unlabelled one is the easiest thing
for someone who knows the field to pull apart.

---

## What it cannot do

**It has never seen a real case.** Every example is invented, and every "correct answer" was
set by whoever wrote the rules. The performance figures measure internal
consistency. They are not evidence it would work on real alerts. Real calibration needs outcome
data (which alerts became reports, and which reports became prosecutions), and no public
dataset provides it.

**Four kinds of laundering are deliberately excluded**: trade-based laundering, cryptoasset ramps,
correspondent banking, and trust structures. This is not a gap to be filled later. A system that
claims to cover everything cannot meaningfully say *"this is outside what can be assessed"*,
because
it recognises nothing as outside its competence.

**It cannot see intent.** It concludes that behaviour *matches a pattern*, never that anyone meant
to launder money. Nothing in transaction data shows intent.

**It considers one customer and one alert at a time.** Real monitoring looks across accounts,
across customers, and over months.

**Its thresholds are untested for sensitivity.** The numbers are plausible, but nobody has measured
how much the conclusions would move if they were set differently. That is the largest known gap.

---

## One result that went against the design

The system was built expecting it should also decline when a decision was simply *close*, near the
boundary between two conclusions. That was implemented, measured, and made things worse at every
setting tried.

The reason is instructive. The system already gets about 98% of the cases it answers right, so
declining the marginal ones discards correct answers about as often as wrong ones.

What does pay is declining for a **specific, nameable** reason: something outside its competence, a
check that was never run. In short:

> **Knowing *what* you do not know is worth a great deal. Knowing only *that* you are unsure is
> worth nothing.**

That distinction was not the reason for designing the system this way, and it is the most useful
thing the evaluation produced.

---

## Using it

There are three ways in:

- **The website**: assess an alert through a form, or browse 24 worked examples.
  See [the deployment notes](../README.md#deploying-the-website).
- **The command line**: `triagex run ALT-3001 --explain`.
- **The written record**: [the refinement log](refinement-log.md) lists every change made to the
  rules and what prompted it, including the mistakes. It is the most honest guide to how the system
  was actually built.
