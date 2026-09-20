"""M6 acceptance tests: search algorithms, graph search, contrastive explanation.

Three kinds of claim are checked here.

**Correctness against an independent oracle.** The graph algorithms are hand-written, so they
are checked against `networkx` rather than against expectations written by the same hand. An
implementation verified only by whoever wrote it is verified by nobody.

**The properties that justify each algorithm's existence.** A* must never return a worse cost
than uniform cost, or its heuristic is inadmissible and the guarantee is void. BFS must find
fewest hops. Iterative deepening must find the same answer as depth-first while bounding
memory. These are asserted rather than assumed.

**That the contrastive search is honest about its limits.** No combination of evidence can
resolve an out-of-scope case, and the search must report that rather than manufacture an
answer.
"""

from __future__ import annotations

import networkx as nx
import pytest

from triagex.data.loader import CASE_DIR, factbase_for, load_case, measurements
from triagex.pipeline import assess
from triagex.search.algorithms import (
    ALGORITHMS,
    OPTIMAL_ALGORITHMS,
    astar,
    breadth_first,
    compare,
    depth_first,
    format_comparison,
    greedy_best_first,
    iterative_deepening,
    uniform_cost,
)
from triagex.search.contrastive import (
    CATALOGUE,
    ContrastiveProblem,
    analyse,
    cheapest_evidence,
    reset_cache,
)
from triagex.search.network import (
    COST_SCALE,
    Flow,
    GraphPathProblem,
    TransactionGraph,
    graph_for_case,
)

# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


def diamond() -> TransactionGraph:
    """Two routes from A to D: short and small, or long and large.

    Built so fewest-hops and cheapest-value disagree, because that disagreement is the whole
    reason cost-aware search exists.
    """
    return TransactionGraph(
        [
            Flow("A", "B", 1_000, "small hop"),
            Flow("B", "D", 1_000, "small hop"),
            Flow("A", "X", 900_000, "bulk"),
            Flow("X", "Y", 900_000, "bulk"),
            Flow("Y", "D", 900_000, "bulk"),
        ]
    )


def cyclic() -> TransactionGraph:
    return TransactionGraph(
        [
            Flow("ACC", "CP1", 50_000),
            Flow("CP1", "CP2", 49_000),
            Flow("CP2", "ACC", 48_000),
            Flow("CP3", "ACC", 2_000),
        ]
    )


def hub() -> TransactionGraph:
    flows = [Flow(f"P{i}", "MULE", 500 + i * 10) for i in range(9)]
    flows.append(Flow("MULE", "CONTROLLER", 5_000))
    flows.append(Flow("OTHER", "CONTROLLER", 400))
    return TransactionGraph(flows)


def as_networkx(graph: TransactionGraph) -> nx.DiGraph:
    """The same graph in networkx, for use as an oracle."""
    g = nx.DiGraph()
    for flow in graph.flows:
        # Keep the cheapest parallel edge, matching what Dijkstra would use anyway.
        if g.has_edge(flow.source, flow.target):
            g[flow.source][flow.target]["weight"] = min(
                g[flow.source][flow.target]["weight"], flow.cost
            )
        else:
            g.add_edge(flow.source, flow.target, weight=flow.cost)
    return g


# --------------------------------------------------------------------------------------
# Graph structure
# --------------------------------------------------------------------------------------


def test_cost_falls_as_value_rises() -> None:
    # Getting this backwards would make the least plausible route the shortest path.
    small = Flow("A", "B", 1_000)
    large = Flow("A", "B", 1_000_000)
    assert large.cost < small.cost
    assert small.cost == pytest.approx(COST_SCALE / 1_000)


def test_zero_amount_is_impassable() -> None:
    assert Flow("A", "B", 0).cost == float("inf")


def test_in_degree_counts_distinct_payers_not_transactions() -> None:
    graph = TransactionGraph(
        [Flow("P1", "ACC", 100), Flow("P1", "ACC", 100), Flow("P1", "ACC", 100)]
    )
    # Twenty payments from one employer is a salary; this must not read as three payers.
    assert graph.in_degree("ACC") == 1


def test_hub_detection() -> None:
    assert "MULE" in hub().hubs(threshold=5)
    assert "CONTROLLER" not in hub().hubs(threshold=5)


def test_cycles_are_reported_once_not_once_per_starting_point() -> None:
    cycles = cyclic().find_cycles()
    assert len(cycles) == 1, "a naive implementation reports this three times"
    assert set(cycles[0]) == {"ACC", "CP1", "CP2"}


def test_acyclic_graph_has_no_loop() -> None:
    assert diamond().has_closed_loop() is False
    assert cyclic().has_closed_loop() is True


def test_cycle_length_is_bounded() -> None:
    chain = TransactionGraph([Flow(f"N{i}", f"N{i + 1}", 1_000) for i in range(8)])
    chain.add(Flow("N8", "N0", 1_000))
    assert chain.find_cycles(max_length=4) == []
    assert chain.find_cycles(max_length=9)


# --------------------------------------------------------------------------------------
# Cross-validation against networkx
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("builder", [diamond, cyclic, hub], ids=["diamond", "cyclic", "hub"])
def test_dijkstra_matches_networkx(builder) -> None:  # type: ignore[no-untyped-def]
    graph = builder()
    oracle = as_networkx(graph)
    for source in graph.nodes:
        mine, _ = graph.dijkstra(source)
        theirs = nx.single_source_dijkstra_path_length(oracle, source, weight="weight")
        for node, cost in theirs.items():
            assert mine[node] == pytest.approx(cost), f"{source} -> {node}"
        assert set(mine) == set(theirs)


def test_cheapest_path_matches_networkx() -> None:
    graph = diamond()
    oracle = as_networkx(graph)
    mine, cost = graph.cheapest_value_path("A", "D")
    theirs = nx.dijkstra_path(oracle, "A", "D", weight="weight")
    assert list(mine) == theirs
    assert cost == pytest.approx(nx.dijkstra_path_length(oracle, "A", "D", weight="weight"))


def test_shortest_hop_path_matches_networkx() -> None:
    graph = diamond()
    mine = graph.shortest_hop_path("A", "D")
    theirs = nx.shortest_path(as_networkx(graph), "A", "D")
    assert len(mine) == len(theirs)


def test_betweenness_matches_networkx() -> None:
    graph = hub()
    mine = graph.betweenness()
    theirs = nx.betweenness_centrality(as_networkx(graph), normalized=False)
    for node, score in theirs.items():
        assert mine[node] == pytest.approx(score), node


def test_fewest_hops_and_cheapest_value_disagree() -> None:
    """The finding that justifies cost-aware search on this graph."""
    graph = diamond()
    hops = graph.shortest_hop_path("A", "D")
    value, _cost = graph.cheapest_value_path("A", "D")
    assert len(hops) == 3, "A -> B -> D is the shortest in hops"
    assert len(value) == 4, "A -> X -> Y -> D moves the value more efficiently"


# --------------------------------------------------------------------------------------
# Search algorithms
# --------------------------------------------------------------------------------------


def path_problem() -> GraphPathProblem:
    return GraphPathProblem(diamond(), "A", "D")


def test_breadth_first_finds_fewest_steps() -> None:
    result = breadth_first(path_problem())
    assert result.found
    assert result.length == 2, "BFS optimises steps, not cost"


def test_uniform_cost_finds_the_cheapest() -> None:
    result = uniform_cost(path_problem())
    assert result.found
    assert result.length == 3
    assert result.cost < breadth_first(path_problem()).cost


def test_astar_matches_uniform_cost_so_the_heuristic_is_admissible() -> None:
    # If A* ever beats uniform cost on cost, the heuristic overestimates and the optimality
    # guarantee is void. This is the single most important property in the module.
    for source, target in [("A", "D"), ("A", "Y"), ("X", "D")]:
        problem = GraphPathProblem(diamond(), source, target)
        assert astar(problem).cost == pytest.approx(uniform_cost(problem).cost)


def test_astar_expands_no_more_than_uniform_cost_on_a_larger_graph() -> None:
    graph = TransactionGraph()
    for layer in range(6):
        for index in range(4):
            for target in range(4):
                graph.add(Flow(f"L{layer}-{index}", f"L{layer + 1}-{target}", 1_000 * (index + target + 1)))
    problem = GraphPathProblem(graph, "L0-0", "L6-3")
    informed = astar(problem)
    blind = uniform_cost(problem)
    assert informed.cost == pytest.approx(blind.cost)
    assert informed.nodes_expanded <= blind.nodes_expanded


def test_greedy_is_not_guaranteed_optimal() -> None:
    # Not a defect - it is the trade being made, and the docs say so.
    result = greedy_best_first(path_problem())
    assert result.found
    assert result.cost >= uniform_cost(path_problem()).cost


def test_iterative_deepening_finds_a_solution_and_re_expands_to_do_it() -> None:
    shallow = depth_first(path_problem())
    deepened = iterative_deepening(path_problem())
    assert deepened.found
    assert deepened.nodes_expanded >= shallow.nodes_expanded, (
        "re-expansion is the price of bounded memory and should be visible"
    )


def test_depth_first_respects_its_limit() -> None:
    chain = TransactionGraph([Flow(f"N{i}", f"N{i + 1}", 1_000) for i in range(20)])
    result = depth_first(GraphPathProblem(chain, "N0", "N20"), max_depth=3)
    assert not result.found
    assert result.depth_limit_reached


def test_no_solution_is_reported_not_raised() -> None:
    graph = TransactionGraph([Flow("A", "B", 1_000), Flow("C", "D", 1_000)])
    for name, algorithm in ALGORITHMS.items():
        result = algorithm(GraphPathProblem(graph, "A", "D"))
        assert not result.found, name
        assert result.nodes_expanded >= 0


def test_start_equals_goal_is_a_zero_cost_solution() -> None:
    result = breadth_first(GraphPathProblem(diamond(), "A", "A"))
    assert result.found
    assert result.length == 0
    assert result.cost == 0.0


def test_search_is_deterministic() -> None:
    first = compare(path_problem())
    second = compare(path_problem())
    assert [(r.algorithm, r.cost, r.actions, r.nodes_expanded) for r in first] == [
        (r.algorithm, r.cost, r.actions, r.nodes_expanded) for r in second
    ]


def test_every_algorithm_reports_its_cost() -> None:
    results = compare(path_problem())
    assert len(results) == len(ALGORITHMS)
    for result in results:
        assert result.nodes_expanded > 0
        assert result.describe()
    assert "expanded" in format_comparison(results)


def test_optimal_algorithms_agree_with_each_other() -> None:
    results = {r.algorithm: r for r in compare(path_problem())}
    costs = {results[name].cost for name in OPTIMAL_ALGORITHMS}
    assert len(costs) == 1


# --------------------------------------------------------------------------------------
# Contrastive search
# --------------------------------------------------------------------------------------


def _case_measurements(name: str):  # type: ignore[no-untyped-def]
    case = load_case(CASE_DIR / f"{name}.toml")
    return case, measurements(case)


def test_cheapest_evidence_is_actually_the_cheapest() -> None:
    case, m = _case_measurements("request_structuring_no_sof_01")
    request = cheapest_evidence(case.alert_id, m, "refer_to_investigation")
    assert request.found
    assert request.names == ("source_of_funds_evidence",)
    # Any single-intervention alternative must cost at least as much.
    problem = ContrastiveProblem(case.alert_id, m, "refer_to_investigation")
    for item in problem.catalogue:
        if problem.outcome_for(frozenset({item.name})) == "refer_to_investigation":
            assert item.cost >= request.total_cost


def test_out_of_scope_cases_cannot_be_bought_out_of() -> None:
    case, m = _case_measurements("refuse_crypto_in_window_01")
    request = cheapest_evidence(case.alert_id, m, "clear", max_interventions=4)
    assert not request.found
    assert "cannot be bought out of" in request.to_text()


def test_trust_structure_is_equally_unfixable() -> None:
    case, m = _case_measurements("refuse_trust_structure_01")
    assert not cheapest_evidence(case.alert_id, m, "clear", max_interventions=3).found


def test_unscreened_case_is_fixed_by_the_cheapest_possible_action() -> None:
    case, m = _case_measurements("refuse_never_screened_01")
    request = cheapest_evidence(case.alert_id, m, "clear")
    assert request.found
    assert request.names == ("sanctions_screen",)
    assert request.total_cost == pytest.approx(1.0)


def test_interventions_that_change_nothing_are_excluded() -> None:
    case, m = _case_measurements("clear_salaried_01")
    problem = ContrastiveProblem(case.alert_id, m, "monitor")
    # Screening already returned none, so asking for it again is not a step.
    assert "sanctions_screen" not in {item.name for item in problem.catalogue}
    assert len(problem.catalogue) < len(CATALOGUE)


def test_request_text_refuses_to_imply_the_evidence_will_be_favourable() -> None:
    case, m = _case_measurements("request_structuring_no_sof_01")
    text = cheapest_evidence(case.alert_id, m, "refer_to_investigation").to_text()
    assert "not a prediction that the evidence will be favourable" in text


def test_contrastive_report_covers_every_other_outcome() -> None:
    case, m = _case_measurements("request_structuring_no_sof_01")
    result = assess(factbase_for(case), case.alert_id)
    report = analyse(case.alert_id, m, result.outcome, max_interventions=2)
    assert len(report.requests) == 4
    assert report.reachable()
    assert case.alert_id in report.to_text()


def test_cache_reset_makes_comparisons_fair() -> None:
    case, m = _case_measurements("request_structuring_no_sof_01")
    problem = ContrastiveProblem(case.alert_id, m, "refer_to_investigation")
    reset_cache()
    results = compare(problem, reset=reset_cache)
    assert all(r.found for r in results)
    costs = {r.cost for r in results}
    assert len(costs) == 1, "this problem is one step deep, so every strategy should agree"


def test_contrastive_optimality_across_the_library() -> None:
    """Whatever the case, the cost-optimal algorithms must agree."""
    for name in (
        "request_structuring_no_sof_01",
        "request_dormant_reactivation_01",
        "refuse_never_screened_01",
        "monitor_weak_signal_01"):
        case, m = _case_measurements(name)
        problem = ContrastiveProblem(case.alert_id, m, "clear", max_interventions=3)
        reset_cache()
        results = {r.algorithm: r for r in compare(problem, reset=reset_cache)}
        optimal = [results[a] for a in OPTIMAL_ALGORITHMS]
        if optimal[0].found:
            assert optimal[0].cost == pytest.approx(optimal[1].cost), name


# --------------------------------------------------------------------------------------
# Integration with the knowledge base
# --------------------------------------------------------------------------------------


def test_round_tripping_is_detected_by_graph_search_not_declared() -> None:
    case = load_case(CASE_DIR / "refer_round_tripping_01.toml")
    graph = graph_for_case(case)
    assert graph.has_closed_loop()
    # The measurement is computed, so the indicator rests on an actual cycle.
    assert measurements(case)["closed_value_loop"] is True

    result = assess(factbase_for(case), case.alert_id)
    assert result.facts.value_of("round_trip_signature", case.alert_id) == "present"
    assert result.facts.certainty_of("typology", case.alert_id, "round_tripping") > 0.5
    assert result.outcome == "refer_to_investigation"


def test_a_star_case_without_flows_has_no_cycle() -> None:
    case = load_case(CASE_DIR / "clear_salaried_01.toml")
    graph = graph_for_case(case)
    assert not graph.has_closed_loop()
    assert measurements(case)["closed_value_loop"] is False


def test_graph_for_case_includes_every_transaction() -> None:
    case = load_case(CASE_DIR / "request_mule_pattern_no_sof_01.toml")
    graph = graph_for_case(case)
    assert len(graph.flows) == len(case.transactions)
    assert graph.in_degree("ACC-3003") == 6


def test_landmark_heuristic_never_overestimates() -> None:
    """Admissibility, checked directly against exact distances rather than inferred."""
    graph = diamond()
    problem = GraphPathProblem(graph, "A", "D")
    exact, _ = graph.dijkstra("A")
    reverse_costs = {
        node: graph.cheapest_value_path(node, "D")[1] for node in graph.nodes
    }
    for node in graph.nodes:
        if node in exact and reverse_costs[node] != float("inf"):
            assert problem.heuristic(node) <= reverse_costs[node] + 1e-9, node
