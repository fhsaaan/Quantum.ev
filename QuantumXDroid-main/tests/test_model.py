import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

from pathlib import Path
import sys

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

from evcharge.instance import Instance, is_feasible
from evcharge.qaoa import QAOASolver, build_circuit, counts_to_bits, w_state
from evcharge.qubo import brute_force, build, energies, ising, select_options, to_pauli
from evcharge.solvers import exact_milp, exact_sub_solver, fcfs, lns


def sub_problem(seed=0, n=12, evs=(0, 1, 2), k=4):
    inst = Instance(n, seed)
    return inst, build(select_options(inst, fcfs(inst), list(evs), k))


def all_bits(n):
    return np.array([[(i >> q) & 1 for q in range(n)] for i in range(2 ** n)])


def test_qubo_ground_state_is_true_optimum():
    for seed in range(8):
        _, sub = sub_problem(seed, evs=(0, 1, 2))
        bits = all_bits(sub.n_qubits)
        e = energies(sub, bits)
        ground = bits[np.argmin(e)]
        assert sub.is_feasible(ground)
        assert abs(sub.rupees(ground) - brute_force(sub)[0]) < 1e-6


def test_pauli_operator_matches_qubo():
    _, sub = sub_problem()
    h, J = ising(sub, True)
    diag = to_pauli(h, J).to_matrix(sparse=True).diagonal().real
    bits = all_bits(sub.n_qubits)
    e = energies(sub, bits)
    ratio = (e - e.mean()) / np.where(np.abs(diag) > 1e-9, diag - diag.mean(), np.nan)
    assert np.nanstd(ratio) < 1e-9


def test_w_state_is_uniform_one_hot():
    for n in (2, 3, 4, 5):
        qc = QuantumCircuit(n)
        w_state(qc, range(n))
        p = Statevector(qc).probabilities_dict()
        assert len(p) == n
        assert all(abs(v - 1 / n) < 1e-9 and k.count("1") == 1 for k, v in p.items())


def test_xy_mixer_stays_one_hot():
    _, sub = sub_problem()
    out = QAOASolver(p=2, mixer="xy", maxiter=4).solve(sub)
    assert all(x[r].sum() == 1 for x in out["bits"] for r in sub.registers)


def test_schedules_are_feasible_and_ordered():
    inst = Instance(15, 1)
    start = fcfs(inst)
    best, _ = lns(inst, start, exact_sub_solver, iters=30)
    opt, proved = exact_milp(inst)
    assert proved and is_feasible(start) and is_feasible(best) and is_feasible(opt)
    cost = lambda s: sum(o.cost for o in s.values())
    assert cost(opt) <= cost(best) + 1e-6 <= cost(start) + 2e-6


def test_battery_range_is_respected():
    inst = Instance(30, 2)
    for ev, opts in zip(inst.fleet, inst.options):
        for o in opts:
            assert o.charger < 0 or o.km * 0.15 <= (ev.soc - 0.05) * ev.battery_kwh + 1e-9
