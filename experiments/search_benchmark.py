"""Benchmark the search strategies on problems where they actually differ.

Run with ``python experiments/search_benchmark.py``.

The case library's transaction graphs are single-route, and the contrastive state space is
shallow, so on real cases most strategies agree and the comparison says little. That is itself
a finding worth reporting, but it is not a benchmark. So this script builds problems chosen to
separate the algorithms:

1. **A branching value graph.** Many routes between the same pair of parties, with amounts
   spanning three orders of magnitude, so fewest-hops and cheapest-value genuinely diverge.
2. **A real contrastive problem** from the case library, with the memoisation cache cleared
   before each algorithm so the timings measure the algorithms rather than the run order.
3. **An unsolvable contrastive problem** - an out-of-scope case - because how a search behaves
   when there is no answer matters as much as how it behaves when there is.

Everything is seeded. Re-running reproduces the numbers.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from triagex.data.loader import CASE_DIR, load_case, measurements
from triagex.search.algorithms import OPTIMAL_ALGORITHMS, compare, format_comparison
from triagex.search.contrastive import ContrastiveProblem, reset_cache
from triagex.search.network import Flow, GraphPathProblem, TransactionGraph

SEED = 20260920


def branching_graph(*, layers: int = 5, width: int = 4, seed: int = SEED) -> TransactionGraph:
    """A layered payment network with many routes and widely varying amounts.

    Amounts span 1e3 to 1e6, so edge costs span three orders of magnitude. That is what makes
    the cheapest-value route differ from the fewest-hops route: a long chain of large transfers
    moves money more efficiently than a short chain of small ones.
    """
    rng = random.Random(seed)
    graph = TransactionGraph()
    graph.add(Flow("SOURCE", "L0-0", rng.uniform(5e5, 1e6), "origin"))

    for layer in range(layers):
        for index in range(width):
            node = f"L{layer}-{index}"
            if layer + 1 < layers:
                for target_index in range(width):
                    if rng.random() < 0.55:
                        graph.add(
                            Flow(
                                node,
                                f"L{layer + 1}-{target_index}",
                                rng.uniform(1e3, 1e6),
                                f"hop{layer}")
                        )
            else:
                graph.add(Flow(node, "SINK", rng.uniform(1e3, 1e6), "settlement"))

    # A few long-way-round edges with very large amounts: cheap per unit moved, many hops.
    for index in range(width):
        graph.add(Flow("L0-0", f"L1-{index}", rng.uniform(8e5, 1e6), "bulk"))

    return graph


def report(title: str, body: str) -> None:
    print()
    print("=" * 86)
    print(title)
    print("=" * 86)
    print(body)


def check_optimality(results: list[object]) -> str:
    """Confirm the optimal algorithms agree, and report anyone who did worse."""
    found = [r for r in results if getattr(r, "found", False)]
    if not found:
        return "no algorithm found a solution"

    optimal = [r for r in found if r.algorithm in OPTIMAL_ALGORITHMS]  # type: ignore[attr-defined]
    if not optimal:
        return "no cost-optimal algorithm ran"

    best = min(r.cost for r in optimal)  # type: ignore[attr-defined]
    disagreements = [
        f"{r.algorithm} returned {r.cost:.2f} (optimum {best:.2f}, "  # type: ignore[attr-defined]
        f"{(r.cost - best) / best:+.0%})"  # type: ignore[attr-defined]
        for r in found
        if r.cost > best + 1e-9  # type: ignore[attr-defined]
    ]
    if not disagreements:
        return f"every algorithm found the optimum ({best:.2f})"
    return "suboptimal results:\n  " + "\n  ".join(disagreements)


def main() -> None:
    # ---------------------------------------------------------------- 1. value graph
    graph = branching_graph()
    problem = GraphPathProblem(graph, "SOURCE", "SINK")
    results = compare(problem)

    hop_path = graph.shortest_hop_path("SOURCE", "SINK")
    value_path, value_cost = graph.cheapest_value_path("SOURCE", "SINK")

    report(
        f"1. Branching value graph: {len(graph)} nodes, {len(graph.flows)} flows",
        format_comparison(results)
        + f"\n\nlandmark node: {problem.landmark}"
        + f"\nfewest hops   : {len(hop_path) - 1} hops via {' -> '.join(hop_path)}"
        + f"\ncheapest value: {len(value_path) - 1} hops, cost {value_cost:.2f}"
        + f"\n\n{check_optimality(results)}")

    # ---------------------------------------------------------------- 2. contrastive
    case = load_case(CASE_DIR / "request_structuring_no_sof_01.toml")
    contrastive = ContrastiveProblem(
        case.alert_id, measurements(case), "refer_to_investigation", max_interventions=4
    )
    contrastive_results = compare(contrastive, reset=reset_cache)
    report(
        f"2. Contrastive search on {case.alert_id}: reach refer_to_investigation",
        format_comparison(contrastive_results)
        + f"\n\ninterventions available: {len(contrastive.catalogue)}"
        + f"\n{check_optimality(contrastive_results)}")

    # ---------------------------------------------------------------- 3. unsolvable
    crypto = load_case(CASE_DIR / "refuse_crypto_in_window_01.toml")
    hopeless = ContrastiveProblem(
        crypto.alert_id, measurements(crypto), "clear", max_interventions=4
    )
    hopeless_results = compare(hopeless, reset=reset_cache)
    report(
        f"3. Unsolvable contrastive search on {crypto.alert_id}: reach clear",
        format_comparison(hopeless_results)
        + "\n\nNo evidence resolves an out-of-scope case, so exhausting the space is the"
        "\ncorrect behaviour. Note the cost iterative deepening pays to establish it."
        + f"\n{check_optimality(hopeless_results)}")


if __name__ == "__main__":
    main()
