"""Search algorithms, hand-written against one interface.

Six strategies over a common :class:`SearchProblem`, so the same problem can be solved by
each and the results compared on equal terms. Every algorithm reports nodes expanded, nodes
generated, peak frontier size and elapsed time, because "which search is better" is not a
question anyone should answer from intuition.

`networkx` and `heapq`-based library search exist and are better engineered than this. They
are deliberately not used for the algorithms themselves: the point of this module is that the
search behaviour is open to inspection and instrumentation. `networkx` appears only in tests, as
an
independent oracle to check the hand-written graph search against.

**What the comparison actually shows** (see ``docs/06-search.md`` for the measured numbers):

* Uninformed strategies pay for ignoring cost. BFS finds the shortest path in *steps*, which
  is not the cheapest path when steps have different prices.
* Uniform cost is correct but expands much of the space.
* Greedy best-first is fast and not optimal - it commits to whatever looks best next.
* A* with an admissible heuristic matches uniform cost's answer while expanding fewer nodes,
  which is the entire argument for having a heuristic at all.
* Iterative deepening exists for the memory-bounded case: it re-expands aggressively in
  exchange for linear space, which matters when the frontier will not fit.

Determinism is enforced throughout by an insertion counter used as the final tiebreak, so two
runs over the same problem expand nodes in the same order. A benchmark whose numbers move
between runs is not a benchmark.
"""

from __future__ import annotations

import heapq
import time
from collections import deque
from collections.abc import Callable, Hashable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

State = TypeVar("State", bound=Hashable)
Action = TypeVar("Action")


Action_co = TypeVar("Action_co", covariant=True)


class SearchProblem(Protocol[State, Action_co]):
    """The interface every search in this project is written against."""

    def initial(self) -> State: ...

    def is_goal(self, state: State) -> bool: ...

    def successors(self, state: State) -> Iterable[tuple[State, Action_co, float]]:
        """Reachable states, the action that gets there, and the step cost."""
        ...

    def heuristic(self, state: State) -> float:
        """Estimated remaining cost. Must never overestimate, or A* loses optimality."""
        ...


@dataclass(frozen=True, slots=True)
class SearchResult(Generic[State, Action]):
    algorithm: str
    found: bool
    cost: float = 0.0
    actions: tuple[Action, ...] = ()
    final_state: State | None = None
    nodes_expanded: int = 0
    nodes_generated: int = 0
    max_frontier: int = 0
    elapsed_ms: float = 0.0
    depth_limit_reached: bool = False

    @property
    def length(self) -> int:
        return len(self.actions)

    def describe(self) -> str:
        if not self.found:
            return f"{self.algorithm}: no solution ({self.nodes_expanded} expanded)"
        return (
            f"{self.algorithm}: cost {self.cost:.1f} in {self.length} steps, "
            f"{self.nodes_expanded} expanded, {self.elapsed_ms:.1f} ms"
        )


@dataclass(slots=True)
class _Node(Generic[State, Action]):
    state: State
    parent: _Node[State, Action] | None = None
    action: Action | None = None
    cost: float = 0.0
    depth: int = 0

    def path(self) -> tuple[Action, ...]:
        actions: list[Action] = []
        node: _Node[State, Action] | None = self
        while node is not None and node.action is not None:
            actions.append(node.action)
            node = node.parent
        return tuple(reversed(actions))


@dataclass(slots=True)
class _Counter:
    """Monotonic tiebreak, so equal-priority nodes are expanded in insertion order."""

    value: int = 0

    def next(self) -> int:
        self.value += 1
        return self.value


@dataclass(slots=True)
class _Stats:
    expanded: int = 0
    generated: int = 0
    max_frontier: int = 0
    started: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0

    def observe_frontier(self, size: int) -> None:
        self.max_frontier = max(self.max_frontier, size)


def _result(
    algorithm: str,
    node: _Node[State, Action] | None,
    stats: _Stats,
    *,
    depth_limit_reached: bool = False) -> SearchResult[State, Action]:
    if node is None:
        return SearchResult(
            algorithm=algorithm,
            found=False,
            nodes_expanded=stats.expanded,
            nodes_generated=stats.generated,
            max_frontier=stats.max_frontier,
            elapsed_ms=stats.elapsed_ms(),
            depth_limit_reached=depth_limit_reached)
    return SearchResult(
        algorithm=algorithm,
        found=True,
        cost=node.cost,
        actions=node.path(),
        final_state=node.state,
        nodes_expanded=stats.expanded,
        nodes_generated=stats.generated,
        max_frontier=stats.max_frontier,
        elapsed_ms=stats.elapsed_ms())


# --------------------------------------------------------------------------------------
# Uninformed
# --------------------------------------------------------------------------------------


def breadth_first(problem: SearchProblem[State, Action]) -> SearchResult[State, Action]:
    """Fewest *steps*, which is not the same as cheapest when steps differ in price."""
    stats = _Stats()
    start = problem.initial()
    if problem.is_goal(start):
        return _result("breadth-first", _Node(start), stats)

    frontier: deque[_Node[State, Action]] = deque([_Node(start)])
    seen: set[State] = {start}

    while frontier:
        stats.observe_frontier(len(frontier))
        node = frontier.popleft()
        stats.expanded += 1
        for state, action, step in problem.successors(node.state):
            if state in seen:
                continue
            seen.add(state)
            stats.generated += 1
            child = _Node(state, node, action, node.cost + step, node.depth + 1)
            if problem.is_goal(state):
                return _result("breadth-first", child, stats)
            frontier.append(child)
    return _result("breadth-first", None, stats)


def depth_first(
    problem: SearchProblem[State, Action], *, max_depth: int = 32
) -> SearchResult[State, Action]:
    """Cheap on memory, indifferent to quality. Depth-limited to stay terminating."""
    stats = _Stats()
    start = problem.initial()
    if problem.is_goal(start):
        return _result("depth-first", _Node(start), stats)

    stack: list[_Node[State, Action]] = [_Node(start)]
    seen: set[State] = set()
    hit_limit = False

    while stack:
        stats.observe_frontier(len(stack))
        node = stack.pop()
        if node.state in seen:
            continue
        seen.add(node.state)
        stats.expanded += 1

        if node.depth >= max_depth:
            hit_limit = True
            continue

        for state, action, step in reversed(list(problem.successors(node.state))):
            if state in seen:
                continue
            stats.generated += 1
            child = _Node(state, node, action, node.cost + step, node.depth + 1)
            if problem.is_goal(state):
                return _result("depth-first", child, stats)
            stack.append(child)
    return _result("depth-first", None, stats, depth_limit_reached=hit_limit)


def iterative_deepening(
    problem: SearchProblem[State, Action], *, max_depth: int = 12
) -> SearchResult[State, Action]:
    """Depth-first completeness with linear memory, paid for by re-expansion.

    The re-expansion is the honest cost: node counts here are far higher than BFS on the same
    problem. It earns its place only when the frontier would not fit in memory, which is worth
    stating plainly rather than presenting it as a free improvement.
    """
    stats = _Stats()
    start = problem.initial()
    if problem.is_goal(start):
        return _result("iterative-deepening", _Node(start), stats)

    for limit in range(1, max_depth + 1):
        found = _depth_limited(problem, start, limit, stats)
        if found is not None:
            return _result("iterative-deepening", found, stats)
    return _result("iterative-deepening", None, stats, depth_limit_reached=True)


def _depth_limited(
    problem: SearchProblem[State, Action],
    start: State,
    limit: int,
    stats: _Stats) -> _Node[State, Action] | None:
    stack: list[_Node[State, Action]] = [_Node(start)]
    while stack:
        stats.observe_frontier(len(stack))
        node = stack.pop()
        stats.expanded += 1
        if node.depth >= limit:
            continue
        for state, action, step in reversed(list(problem.successors(node.state))):
            stats.generated += 1
            child = _Node(state, node, action, node.cost + step, node.depth + 1)
            if problem.is_goal(state):
                return child
            stack.append(child)
    return None


# --------------------------------------------------------------------------------------
# Informed
# --------------------------------------------------------------------------------------


def uniform_cost(problem: SearchProblem[State, Action]) -> SearchResult[State, Action]:
    """Cheapest path, guaranteed, by expanding in order of cost so far."""
    return _best_first(problem, "uniform-cost", use_heuristic=False, use_cost=True)


def greedy_best_first(problem: SearchProblem[State, Action]) -> SearchResult[State, Action]:
    """Follows the heuristic alone. Fast, and makes no promise about the answer."""
    return _best_first(problem, "greedy", use_heuristic=True, use_cost=False)


def astar(problem: SearchProblem[State, Action]) -> SearchResult[State, Action]:
    """Cost so far plus estimated cost remaining. Optimal when the heuristic is admissible."""
    return _best_first(problem, "a-star", use_heuristic=True, use_cost=True)


def _best_first(
    problem: SearchProblem[State, Action],
    name: str,
    *,
    use_heuristic: bool,
    use_cost: bool) -> SearchResult[State, Action]:
    stats = _Stats()
    counter = _Counter()
    start = problem.initial()

    def priority(node: _Node[State, Action]) -> float:
        value = node.cost if use_cost else 0.0
        if use_heuristic:
            value += problem.heuristic(node.state)
        return value

    start_node: _Node[State, Action] = _Node(start)
    frontier: list[tuple[float, int, _Node[State, Action]]] = [
        (priority(start_node), counter.next(), start_node)
    ]
    best_cost: dict[State, float] = {start: 0.0}

    while frontier:
        stats.observe_frontier(len(frontier))
        _, _, node = heapq.heappop(frontier)

        if node.cost > best_cost.get(node.state, float("inf")):
            continue  # a cheaper route to this state was already expanded

        stats.expanded += 1
        if problem.is_goal(node.state):
            return _result(name, node, stats)

        for state, action, step in problem.successors(node.state):
            new_cost = node.cost + step
            if new_cost >= best_cost.get(state, float("inf")):
                continue
            best_cost[state] = new_cost
            stats.generated += 1
            child = _Node(state, node, action, new_cost, node.depth + 1)
            heapq.heappush(frontier, (priority(child), counter.next(), child))

    return _result(name, None, stats)


# --------------------------------------------------------------------------------------
# Comparison harness
# --------------------------------------------------------------------------------------

ALGORITHMS = {
    "breadth-first": breadth_first,
    "depth-first": depth_first,
    "iterative-deepening": iterative_deepening,
    "uniform-cost": uniform_cost,
    "greedy": greedy_best_first,
    "a-star": astar,
}

OPTIMAL_ALGORITHMS = frozenset({"uniform-cost", "a-star"})
"""The two that guarantee the cheapest solution, given an admissible heuristic."""


def compare(
    problem: SearchProblem[State, Action],
    *,
    only: Iterable[str] | None = None,
    reset: Callable[[], None] | None = None) -> list[SearchResult[State, Action]]:
    """Run every algorithm on one problem and return the results in a stable order.

    ``reset`` is called before each run and exists for a specific reason: when the goal test
    is memoised, whichever algorithm runs first pays for every cache entry the rest then get
    free, and the wall-clock column becomes a measure of run order rather than of the
    algorithms. Passing the cache-clearing function makes the timings comparable. Node counts
    are unaffected either way, which is why they are the primary metric.
    """
    names = list(only) if only is not None else list(ALGORITHMS)
    results = []
    for name in names:
        if reset is not None:
            reset()
        results.append(ALGORITHMS[name](problem))
    return results


def format_comparison(results: list[SearchResult[State, Action]]) -> str:
    """A fixed-width table, for the docs and for the CLI."""
    header = f"{'algorithm':<20} {'found':<6} {'cost':>8} {'steps':>6} {'expanded':>9} {'generated':>10} {'frontier':>9} {'ms':>7}"
    lines = [header, "-" * len(header)]
    for r in results:
        lines.append(
            f"{r.algorithm:<20} {'yes' if r.found else 'no':<6} {r.cost:>8.1f} "
            f"{r.length:>6} {r.nodes_expanded:>9} {r.nodes_generated:>10} "
            f"{r.max_frontier:>9} {r.elapsed_ms:>7.1f}"
        )
    return "\n".join(lines)


def path_states(
    problem: SearchProblem[State, Action], result: SearchResult[State, Action]
) -> Iterator[State]:
    """Replay a solution, yielding each state along the way."""
    state = problem.initial()
    yield state
    for action in result.actions:
        for candidate, candidate_action, _cost in problem.successors(state):
            if candidate_action == action:
                state = candidate
                yield state
                break
