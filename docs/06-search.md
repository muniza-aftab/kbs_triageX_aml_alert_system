# 06. Search

Two search components, both doing work the product needs rather than demonstrating that search was
implemented. Six algorithms, hand-written against one interface so they can be compared on identical
problems.

Reproduce everything here with `python experiments/search_benchmark.py`.

---

## 1. The algorithms

| | strategy | guarantees |
|---|---|---|
| Uninformed | breadth-first | fewest *steps*, not cheapest when steps differ in price |
| | depth-first | none; cheap on memory |
| | iterative deepening | complete, linear memory, pays by re-expanding |
| Informed | uniform cost | cheapest path |
| | greedy best-first | none; follows the heuristic alone |
| | A\* | cheapest path, given an admissible heuristic |

Every algorithm reports nodes expanded, nodes generated, peak frontier and elapsed time, because
"which search is better" is not a question anyone should answer from intuition.

Determinism is enforced by an insertion counter as the final tiebreak, so two runs expand nodes in
the same order. A benchmark whose numbers move between runs is not a benchmark.

`networkx` is deliberately not used for the algorithms: the point is that the search behaviour is
inspectable and instrumented. It appears only in tests, as an independent oracle for Dijkstra,
shortest paths and betweenness. An implementation verified only by whoever wrote it is verified by
nobody.

---

## 2. Contrastive explanation search

**The question:** given this decision, what is the cheapest evidence that would change it?

**The state space:** a state is the set of interventions applied so far. An intervention is a piece of
evidence a bank could actually obtain, paired with the measurement it would establish. Step cost comes
from `EVIDENCE_COSTS`: analyst effort combined with how intrusive the request is for the customer:

| evidence | cost |
|---|---|
| sanctions screen | 1 |
| KYC refresh | 3 |
| counterparty relationship declaration | 4 |
| source-of-funds documentation | 5 |
| adverse media review | 6 |
| customer interview | 9 |
| beneficial-ownership trace | 12 |

So the search does not merely find *a* way to change the answer; it finds the least burdensome one.

**The output is the product.** When the system says "obtain source-of-funds documentation", this is
what chose that question over the six more intrusive ones available:

```
$ triagex evidence ALT-3001 --target refer_to_investigation

To reach refer_to_investigation, obtain (total effort 5):
  1. Obtain source-of-funds documentation (effort 5)

This is what would change the system's assessment. It is not a prediction that the
evidence will be favourable.
```

That last line is load-bearing. Without it an explanation facility becomes a machine for justifying a
predetermined conclusion.

**Why it re-runs the pipeline rather than backward-chaining.** The meta layer is computed by functions,
so backward chaining cannot cross it. Each goal test therefore re-assesses the modified case end to
end, which makes the goal test expensive, and in turn makes node counts matter rather than being
academic. Results are memoised on the frozen measurements, so different orderings of the same
interventions collapse automatically.

**Some limits cannot be bought out of.** Nothing in the catalogue resolves an out-of-scope case: no
amount of evidence gives this system a model of cryptoasset flows or trust ownership. The search
reports no solution, which is the intended behaviour. A search that always found an answer would be
lying about the system's limits.

### Measured: on real cases the algorithms mostly agree

`ALT-3001`, target `refer_to_investigation`:

| algorithm | cost | steps | expanded |
|---|---|---|---|
| breadth-first | 5.0 | 1 | 1 |
| depth-first | 5.0 | 1 | 1 |
| iterative deepening | 5.0 | 1 | 1 |
| uniform cost | 5.0 | 1 | 3 |
| greedy | 5.0 | 1 | 3 |
| A\* | 5.0 | 1 | 3 |

Everything ties. The contrastive state space is one or two steps deep with three to eight
interventions, so cost-aware search has nothing to earn here. **This is reported rather than hidden:**
the module docstring originally claimed the comparison would show the textbook divergences, and on
real cases it does not.

Note the mildly counter-intuitive expansion counts, BFS expands fewer nodes than A\* because BFS
tests the goal on *generation* while best-first must test on *expansion* to preserve cost optimality.
Cheaper, and only sound because unit-step optimality is all BFS promises.

On an unsolvable problem (`ALT-5001`, target `clear`) the space is exhausted: 4 nodes for everything
except iterative deepening's **58**, which is the re-expansion cost made visible.

### A measurement artefact that nearly produced a fake result

The goal test is memoised, so whichever algorithm ran first paid for every cache entry the rest got
free. The first run reported breadth-first at 1845 ms and uniform cost at 1.0 ms, a measure of run
order, not of algorithms.

The harness now takes a `reset` callable and clears the cache before each run. Node counts were
always safe, which is why they are the primary metric.

---

## 3. Counterparty network search

The transaction graph around an alert. Nodes are accounts and counterparties; edges are value flows.

**Edge cost is the inverse of value moved**, scaled per million: a path moving a large sum in one hop
is a *cheaper* route for the money than one dribbling it through many small transfers. Getting this
the wrong way round would make the shortest path the least plausible laundering route, the sort of
error that looks like working software.

### What it computes

- **Cycle detection** → `round_trip_signature`, feeding the round-tripping typology. Cycles are
  canonicalised by rotation, so one loop is reported once rather than once per starting node.
- **Dijkstra** → cheapest value-transfer path, for tracing where money went.
- **Degree** → collection hubs. Counting *distinct* payers, not transactions: twenty payments from one
  employer is a salary, twenty from twenty strangers is a collection point.
- **Betweenness** (Brandes) → the node every route passes through. A mule network's controller is not
  necessarily the node with most payers.

```
$ triagex graph ALT-4006

ALT-4006: 4 parties, 4 flows
  ACC-4006           1 distinct payers,       96,000 in
  ...
circular flows: 1
  ACC-4006 -> CP-BETA -> CP-GAMMA -> CP-ALPHA -> ACC-4006

nodes every route passes through:
  ACC-4006         3.0
```

This closed a documented placeholder. `closed_value_loop` was a hand-set boolean in case files until
the network search existed; it is now computed. That required adding `[[flows]]` to the case format, without counterparty-to-counterparty edges the graph is a star and **cannot** contain a cycle, so
round-tripping was undetectable in principle rather than merely unobserved.

### The landmark heuristic

A\* needs an admissible estimate and a transaction graph has no coordinates. So one node is chosen as
a landmark, exact distances from it are precomputed with Dijkstra, and the triangle inequality gives a
valid lower bound:

```
h(n) = | d(L, goal) − d(L, n) |
```

This is the ALT technique, admissible for any landmark. A test checks it directly against exact
reverse distances rather than inferring admissibility from A\* agreeing with uniform cost.

### Measured: here the algorithms genuinely diverge

A branching value graph, 22 nodes and 53 flows, amounts spanning three orders of magnitude:

| algorithm | cost | steps | expanded | verdict |
|---|---|---|---|---|
| breadth-first | 12.33 | 6 | 15 | **+49% over optimum** |
| depth-first | 12.33 | 6 | 6 | +49% |
| iterative deepening | 12.33 | 6 | **409** | +49%, 27× the expansions |
| uniform cost | **8.28** | 6 | 19 | optimal |
| greedy | 8.28 | 6 | 12 | optimal *here*, not guaranteed |
| **A\*** | **8.28** | 6 | **12** | optimal**37% fewer expansions than UCS** |

This is the textbook result, measured rather than asserted:

- The uninformed strategies find the fewest-hop route and pay **49% more** for the money moved.
- Uniform cost is correct and expands the most.
- A\* matches it while expanding a third fewer nodes, the entire argument for having a heuristic.
- Greedy happens to find the optimum on this instance. It makes no promise to, and the docs say so.
- Iterative deepening finds the same answer as depth-first for 68× the expansions, buying linear
  memory. Worth it only when the frontier will not fit.

The reason this graph shows what the contrastive space does not: continuously varying edge weights and
multiple routes between the same pair of nodes. That is the setting cost-aware search exists for.
