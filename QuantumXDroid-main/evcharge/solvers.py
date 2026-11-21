"""Baselines and the hybrid loop: FCFS, exact MILP, and QAOA-powered LNS."""
import time
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from .instance import N_SLOTS
from .qaoa import QAOASolver, best_feasible
from .qubo import brute_force, build, select_options


def fcfs(inst):
    """What happens today: in ready-time order, each driver goes to the nearest
    station that can fit them and takes its earliest free slot."""
    busy = {}
    schedule = {}
    for ev in sorted(inst.fleet, key=lambda e: (e.ready, e.id)):
        opts = [o for o in inst.options[ev.id] if o.charger >= 0]
        ok = [o for o in opts if all((o.charger, s) not in busy for s in o.slots)]
        if ok:
            pick = min(ok, key=lambda o: (round(o.km, 3), o.start))
        else:
            pick = next(o for o in inst.options[ev.id] if o.charger < 0)
        schedule[ev.id] = pick
        for s in pick.slots:
            busy[(pick.charger, s)] = ev.id
    return schedule


def exact_milp(inst, time_limit=120):
    """Proven optimum (HiGHS). This is the yardstick, not part of the product."""
    flat = [o for opts in inst.options for o in opts]
    n = len(flat)
    rows = len(inst.fleet)
    idx = {(c.id, s): rows + c.id * N_SLOTS + s
           for c in inst.chargers for s in range(N_SLOTS)}
    A = lil_matrix((rows + len(idx), n))
    for j, o in enumerate(flat):
        A[o.ev, j] = 1
        if o.charger >= 0:
            for s in o.slots:
                A[idx[(o.charger, s)], j] = 1
    lo = np.r_[np.ones(rows), -np.inf * np.ones(len(idx))]
    hi = np.ones(rows + len(idx))
    res = milp(np.array([o.cost for o in flat]), integrality=np.ones(n),
               bounds=Bounds(0, 1), constraints=LinearConstraint(A.tocsr(), lo, hi),
               options={"time_limit": time_limit})
    if res.x is None:
        raise RuntimeError(res.message)
    return {flat[j].ev: flat[j] for j in np.flatnonzero(res.x > 0.5)}, res.status == 0


def pick_group(inst, schedule, size, rng):
    """Group EVs that actually compete: a seed with high regret, plus those whose
    current slots block the seed's cheapest options."""
    n = len(inst.fleet)
    regret = np.array([schedule[e].cost - min(o.cost for o in inst.options[e]) for e in range(n)])
    seed = int(rng.choice(n, p=(regret + 1) / (regret + 1).sum()))
    top = sorted(inst.options[seed], key=lambda o: o.cost)[:12]
    score = np.array([sum(o.conflicts(schedule[e]) for o in top) for e in range(n)], float)
    score += rng.random(n) * 0.5
    score[seed] = -1
    return [seed] + [int(e) for e in np.argsort(-score)[:size - 1]]


def lns(inst, start, sub_solver, group=3, k=4, iters=40, patience=15, seed=0):
    """Large Neighbourhood Search: free a few EVs, re-optimise them, keep any gain."""
    rng = np.random.default_rng(seed)
    schedule = dict(start)
    history = [sum(o.cost for o in schedule.values())]
    stale, qubits = 0, 0
    t0 = time.time()
    for _ in range(iters):
        evs = pick_group(inst, schedule, min(group, len(inst.fleet)), rng)
        sub = build(select_options(inst, schedule, evs, k))
        qubits = max(qubits, sub.n_qubits)
        x = sub_solver(sub)
        old = sum(schedule[e].cost for e in evs)
        if x is not None and sub.rupees(x) < old - 1e-6:
            for o in sub.options_of(x):
                schedule[o.ev] = o
            stale = 0
        else:
            stale += 1
        history.append(sum(o.cost for o in schedule.values()))
        if stale >= patience:
            break
    return schedule, {"history": history, "max_qubits": qubits, "seconds": round(time.time() - t0, 1)}


def qaoa_sub_solver(**kw):
    solver = QAOASolver(**kw)

    def solve(sub):
        return best_feasible(sub, solver.solve(sub)["bits"])[1]
    return solve


def exact_sub_solver(sub):
    return brute_force(sub)[1]


def random_sub_solver(shots, seed=0):
    """Control: best of `shots` uniformly random valid-format picks."""
    rng = np.random.default_rng(seed)

    def solve(sub):
        bits = np.zeros((shots, sub.n_qubits), dtype=int)
        for r in sub.registers:
            bits[np.arange(shots), rng.choice(r, shots)] = 1
        return best_feasible(sub, np.unique(bits, axis=0))[1]
    return solve
