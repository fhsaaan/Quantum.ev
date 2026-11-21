"""Turn a small group of EVs into a QUBO, then into an Ising Hamiltonian.

Each binary variable x_i means "this EV takes option i".
    E(x) = sum c_i x_i                         (rupee cost, rescaled)
         + A sum_ev (sum_{i in ev} x_i - 1)^2  (exactly one option per EV)
         + A sum_{i,j conflict} x_i x_j        (one EV per charger per slot)
Every charger is its own resource, so a station with capacity 2 needs no slack
qubits: capacity is enforced by pairwise conflicts alone.
"""
from dataclasses import dataclass
from itertools import combinations, product
import numpy as np
from qiskit.quantum_info import SparsePauliOp


@dataclass
class SubProblem:
    groups: list          # options per EV: list[list[Option]]
    costs: np.ndarray     # rescaled cost per qubit
    conflicts: list       # (i, j) qubit pairs that clash
    penalty: float
    registers: list       # qubit indices per EV
    rs: np.ndarray        # real rupee cost per qubit

    @property
    def n_qubits(self):
        return len(self.costs)

    def options_of(self, x):
        flat = [o for g in self.groups for o in g]
        return [flat[i] for i in np.flatnonzero(x)]

    def is_feasible(self, x):
        return (all(x[r].sum() == 1 for r in self.registers)
                and not any(x[i] and x[j] for i, j in self.conflicts))

    def rupees(self, x):
        return float(self.rs @ x)


def select_options(inst, schedule, evs, k):
    """Classical preprocessing: the k cheapest options per EV that do not clash
    with the EVs held fixed. The current choice always stays in, so a sub-solve
    can never make the schedule worse."""
    fixed = [o for e, o in schedule.items() if e not in evs]
    groups = []
    for rank, e in enumerate(evs):
        free = [o for o in inst.options[e]
                if o.charger >= 0 and not any(o.conflicts(f) for f in fixed)]
        # Chargers at a site are interchangeable, so keep one per (site, start)
        # and rotate by EV so that two EVs in the group lean on different chargers.
        by_site = {}
        for o in free:
            by_site.setdefault((inst.chargers[o.charger].station, o.start), []).append(o)
        unique = [v[rank % len(v)] for v in by_site.values()]
        unique.sort(key=lambda o: o.cost)
        cur = schedule[e]
        group = [cur] + [o for o in unique if o != cur][:k - 1]
        groups.append(sorted(group, key=lambda o: o.cost))
    return groups


def build(groups):
    flat = [o for g in groups for o in g]
    rs = np.array([o.cost for o in flat])
    registers, at = [], 0
    for g in groups:
        registers.append(np.arange(at, at + len(g)))
        at += len(g)
    costs = rs.astype(float).copy()
    spread = 0.0
    for r in registers:
        costs[r] -= costs[r].min()
        spread += costs[r].max()
    scale = max(spread, 1e-9)
    costs /= scale           # the summed per-EV spread is now 1
    conflicts = [(i, j) for (i, a), (j, b) in combinations(enumerate(flat), 2)
                 if a.ev != b.ev and a.conflicts(b)]
    return SubProblem(groups, costs, conflicts, 1.01, registers, rs)


def linear_quadratic(sub, one_hot):
    """QUBO coefficients. one_hot=False leaves the constraint to the XY mixer."""
    a = sub.costs.copy()
    b = {pair: sub.penalty for pair in sub.conflicts}
    if one_hot:
        for r in sub.registers:
            a[r] -= sub.penalty  # (sum x - 1)^2 = 1 - sum x + 2 sum_{i<j} x_i x_j
            for i, j in combinations(r, 2):
                b[(int(i), int(j))] = 2 * sub.penalty
    return a, b


def ising(sub, one_hot):
    """x = (1 - Z)/2 gives H = sum h_i Z_i + sum J_ij Z_i Z_j + const.
    Coefficients are normalised so one QAOA angle range suits every sub-problem."""
    a, b = linear_quadratic(sub, one_hot)
    h = -a / 2
    J = {}
    for (i, j), v in b.items():
        h[i] -= v / 4
        h[j] -= v / 4
        J[(i, j)] = v / 4
    norm = max(np.abs(h).max(), max(map(abs, J.values()), default=0), 1e-9)
    return h / norm, {p: v / norm for p, v in J.items()}


def to_pauli(h, J):
    """Same Hamiltonian as a Qiskit operator (used by the tests and the docs)."""
    terms = [("Z", [i], float(v)) for i, v in enumerate(h)]
    terms += [("ZZ", list(p), float(v)) for p, v in J.items()]
    return SparsePauliOp.from_sparse_list(terms, num_qubits=len(h))


def energies(sub, bits, one_hot=True):
    """QUBO energy for a matrix of bit rows."""
    a, b = linear_quadratic(sub, one_hot)
    e = bits @ a
    for (i, j), v in b.items():
        e = e + v * bits[:, i] * bits[:, j]
    return e


def brute_force(sub):
    """Exact optimum of the sub-problem by listing every one-hot assignment."""
    best, best_x = np.inf, None
    n = 0
    for pick in product(*[r.tolist() for r in sub.registers]):
        x = np.zeros(sub.n_qubits, dtype=int)
        x[list(pick)] = 1
        if sub.is_feasible(x):
            n += 1
            if sub.rupees(x) < best:
                best, best_x = sub.rupees(x), x
    return best, best_x, n
