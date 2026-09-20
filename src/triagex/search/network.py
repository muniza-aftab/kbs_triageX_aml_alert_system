"""Counterparty network search.

The transaction graph around an alert, and the searches over it that feed the indicator layer:
circular flows for round-tripping, value paths for tracing where money went, and degree and
betweenness for spotting collection hubs.

**Why this is where the algorithm comparison earns its keep.** The contrastive search has a
small, shallow state space with a handful of discrete costs, so every strategy tends to agree.
A value graph has continuously varying edge weights and multiple routes between the same pair
of nodes, which is exactly the setting where fewest-hops and cheapest-path diverge - and where
an informed heuristic can be shown to pay for itself rather than asserted to.

**Edge cost is the inverse of value moved.** A path that moves a large sum in one hop is a
*cheaper* way to move money than one that dribbles it through many small transfers, so cost is
``1 / amount``. Getting this the wrong way round would make the shortest path the least
plausible laundering route, which is the sort of error that looks like working software.

**The landmark heuristic.** A* needs an admissible estimate, and a transaction graph has no
coordinates to derive one from. So one node is chosen as a landmark, exact distances from it
are precomputed with Dijkstra, and the triangle inequality gives a valid lower bound:
``h(n) = |d(L, goal) - d(L, n)|``. This is the ALT technique, and it is admissible for any
landmark, which the tests check by confirming A* and uniform cost always agree on cost.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

INFINITY = float("inf")

COST_SCALE = 1_000_000.0
"""Cost is expressed per million units of value moved."""


@dataclass(frozen=True, slots=True)
class Flow:
    """Value moving from one party to another."""

    source: str
    target: str
    amount: float
    reference: str = ""

    @property
    def cost(self) -> float:
        """Inverse value, scaled per million moved.

        Moving more in one hop is a cheaper route for the money, so cost falls as amount
        rises. The million scaling is cosmetic but not pointless: raw ``1/amount`` costs are
        around 1e-5 for realistic sums, which round to 0.0 in every report and make the
        comparison tables useless to read.
        """
        return COST_SCALE / self.amount if self.amount > 0 else INFINITY


class TransactionGraph:
    """A directed multigraph of value flows, with the searches an AML analyst needs."""

    def __init__(self, flows: Iterable[Flow] = ()) -> None:
        self._out: dict[str, list[Flow]] = {}
        self._in: dict[str, list[Flow]] = {}
        self._nodes: set[str] = set()
        for flow in flows:
            self.add(flow)

    # -- construction -------------------------------------------------------------------

    def add(self, flow: Flow) -> None:
        self._out.setdefault(flow.source, []).append(flow)
        self._in.setdefault(flow.target, []).append(flow)
        self._nodes.update({flow.source, flow.target})

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(sorted(self._nodes))

    @property
    def flows(self) -> tuple[Flow, ...]:
        return tuple(flow for flows in self._out.values() for flow in flows)

    def out_edges(self, node: str) -> tuple[Flow, ...]:
        return tuple(self._out.get(node, ()))

    def in_edges(self, node: str) -> tuple[Flow, ...]:
        return tuple(self._in.get(node, ()))

    def __len__(self) -> int:
        return len(self._nodes)

    # -- degree -------------------------------------------------------------------------

    def in_degree(self, node: str) -> int:
        """Distinct payers into a node. Distinct, not transaction count: twenty payments from
        one employer is a salary, twenty payments from twenty strangers is a collection point."""
        return len({flow.source for flow in self._in.get(node, ())})

    def out_degree(self, node: str) -> int:
        return len({flow.target for flow in self._out.get(node, ())})

    def inbound_value(self, node: str) -> float:
        return sum(flow.amount for flow in self._in.get(node, ()))

    def hubs(self, threshold: int) -> tuple[str, ...]:
        """Nodes with at least ``threshold`` distinct payers."""
        return tuple(n for n in self.nodes if self.in_degree(n) >= threshold)

    # -- cycles -------------------------------------------------------------------------

    def find_cycles(self, *, max_length: int = 6, limit: int = 32) -> list[tuple[str, ...]]:
        """Enumerate simple directed cycles, shortest first.

        Depth-first with an explicit path stack. Cycles are canonicalised by rotating to their
        smallest node so the same loop is not reported once per starting point, which a naive
        implementation does and which makes the output look far more alarming than it is.
        """
        found: set[tuple[str, ...]] = set()

        def walk(start: str, node: str, path: tuple[str, ...]) -> None:
            if len(found) >= limit or len(path) > max_length:
                return
            for flow in sorted(self._out.get(node, ()), key=lambda f: (f.target, -f.amount)):
                nxt = flow.target
                if nxt == start and len(path) >= 2:
                    found.add(_canonical_cycle(path))
                elif nxt not in path:
                    walk(start, nxt, (*path, nxt))

        for node in self.nodes:
            walk(node, node, (node,))

        return sorted(found, key=lambda cycle: (len(cycle), cycle))

    def has_closed_loop(self, *, max_length: int = 6) -> bool:
        """Whether value returns to its origin. Drives ``round_trip_signature``."""
        return bool(self.find_cycles(max_length=max_length, limit=1))

    # -- paths --------------------------------------------------------------------------

    def shortest_hop_path(self, source: str, target: str) -> tuple[str, ...]:
        """Fewest intermediaries, ignoring value. Breadth-first."""
        if source == target:
            return (source,)
        frontier: list[tuple[str, ...]] = [(source,)]
        seen = {source}
        while frontier:
            nxt: list[tuple[str, ...]] = []
            for path in frontier:
                for flow in self._out.get(path[-1], ()):
                    if flow.target == target:
                        return (*path, target)
                    if flow.target not in seen:
                        seen.add(flow.target)
                        nxt.append((*path, flow.target))
            frontier = nxt
        return ()

    def dijkstra(self, source: str) -> tuple[dict[str, float], dict[str, str]]:
        """Exact costs from one node, and the predecessor map to rebuild paths."""
        distance: dict[str, float] = {source: 0.0}
        previous: dict[str, str] = {}
        visited: set[str] = set()
        queue: list[tuple[float, str]] = [(0.0, source)]

        while queue:
            cost, node = heapq.heappop(queue)
            if node in visited:
                continue
            visited.add(node)
            for flow in self._out.get(node, ()):
                candidate = cost + flow.cost
                if candidate < distance.get(flow.target, INFINITY):
                    distance[flow.target] = candidate
                    previous[flow.target] = node
                    heapq.heappush(queue, (candidate, flow.target))
        return distance, previous

    def cheapest_value_path(self, source: str, target: str) -> tuple[tuple[str, ...], float]:
        """The route that moves value most efficiently, with its cost."""
        distance, previous = self.dijkstra(source)
        if target not in distance:
            return (), INFINITY
        path = [target]
        while path[-1] != source:
            path.append(previous[path[-1]])
        return tuple(reversed(path)), distance[target]

    # -- centrality ---------------------------------------------------------------------

    def betweenness(self) -> dict[str, float]:
        """Unweighted betweenness centrality, by counting shortest paths.

        Brandes' algorithm for unweighted graphs. Betweenness matters here because a mule
        network's controller is not necessarily the node with the most payers - it is the node
        every route passes through, which degree alone does not reveal.
        """
        scores = dict.fromkeys(self.nodes, 0.0)

        for source in self.nodes:
            stack: list[str] = []
            predecessors: dict[str, list[str]] = {n: [] for n in self.nodes}
            sigma = dict.fromkeys(self.nodes, 0.0)
            sigma[source] = 1.0
            distance = dict.fromkeys(self.nodes, -1)
            distance[source] = 0

            queue = [source]
            while queue:
                node = queue.pop(0)
                stack.append(node)
                for flow in self._out.get(node, ()):
                    nxt = flow.target
                    if distance[nxt] < 0:
                        distance[nxt] = distance[node] + 1
                        queue.append(nxt)
                    if distance[nxt] == distance[node] + 1:
                        sigma[nxt] += sigma[node]
                        predecessors[nxt].append(node)

            delta = dict.fromkeys(self.nodes, 0.0)
            while stack:
                node = stack.pop()
                for predecessor in predecessors[node]:
                    if sigma[node]:
                        delta[predecessor] += (sigma[predecessor] / sigma[node]) * (1 + delta[node])
                if node != source:
                    scores[node] += delta[node]
        return scores


def _canonical_cycle(path: tuple[str, ...]) -> tuple[str, ...]:
    """Rotate a cycle to start at its smallest node, so one loop is reported once."""
    pivot = path.index(min(path))
    return path[pivot:] + path[:pivot]


# --------------------------------------------------------------------------------------
# Search adapter
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class GraphPathProblem:
    """Value-path search as a :class:`SearchProblem`, so the generic algorithms can run on it.

    This is the adapter that makes the comparison possible: identical problem, six strategies,
    and the differences between them attributable to the strategies alone.
    """

    graph: TransactionGraph
    source: str
    target: str
    landmark: str | None = None
    _landmark_distance: dict[str, float] = field(default_factory=dict, init=False)
    _goal_distance: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        landmark = self.landmark or self._pick_landmark()
        self.landmark = landmark
        self._landmark_distance, _ = self.graph.dijkstra(landmark)
        self._goal_distance = self._landmark_distance.get(self.target, INFINITY)

    def _pick_landmark(self) -> str:
        """The highest-degree node. A well-connected landmark gives tighter bounds."""
        nodes = self.graph.nodes
        if not nodes:
            return self.source
        return max(nodes, key=lambda n: (self.graph.in_degree(n) + self.graph.out_degree(n), n))

    # -- SearchProblem ------------------------------------------------------------------

    def initial(self) -> str:
        return self.source

    def is_goal(self, state: str) -> bool:
        return state == self.target

    def successors(self, state: str) -> Iterator[tuple[str, str, float]]:
        for flow in self.graph.out_edges(state):
            label = f"{flow.source}->{flow.target}" + (f" [{flow.reference}]" if flow.reference else "")
            yield flow.target, label, flow.cost

    def heuristic(self, state: str) -> float:
        """Landmark lower bound via the triangle inequality. Admissible for any landmark."""
        if self._goal_distance == INFINITY:
            return 0.0
        here = self._landmark_distance.get(state)
        if here is None:
            return 0.0
        return abs(self._goal_distance - here)


# --------------------------------------------------------------------------------------
# Building a graph from a case
# --------------------------------------------------------------------------------------


def graph_for_case(case: object) -> TransactionGraph:
    """Build the transaction graph for a loaded case.

    Every credit becomes a flow from its counterparty into the account, every debit a flow out,
    and any explicit ``[[flows]]`` entries add counterparty-to-counterparty movement the bank
    can see from correspondent data. Without those extra flows the graph is a star and cannot
    contain a cycle, which is why the case format carries them.
    """
    from triagex.data.loader import Case

    assert isinstance(case, Case)
    graph = TransactionGraph()

    for txn in case.transactions:
        account = str(txn.require("account"))
        counterparty = str(txn.get("counterparty") or "EXTERNAL")
        amount = float(txn.require("amount"))
        if txn.get("direction") == "in":
            graph.add(Flow(counterparty, account, amount, str(txn.id)))
        else:
            graph.add(Flow(account, counterparty, amount, str(txn.id)))

    for flow in case.flows:
        graph.add(Flow(flow["source"], flow["target"], float(flow["amount"]), flow.get("reference", "")))

    return graph
