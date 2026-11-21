"""QAOA in Qiskit, with a constraint-preserving XY mixer.

mixer="xy": start in a W state on each EV's register (the EV holds a superposition
of its options, always exactly one) and mix with XX+YY, which only moves that one
excitation around. Invalid "two options" states are never reached, without noise.
mixer="x":  textbook QAOA: uniform start, X mixer, constraints as penalties only.
"""
import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import ParameterVector
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2
from scipy.optimize import minimize

from .qubo import energies, ising


def w_state(qc, reg):
    """Equal superposition of 'exactly one qubit set' on reg."""
    reg = [int(q) for q in reg]
    qc.x(reg[0])
    n = len(reg)
    for i in range(n - 1):
        qc.cry(2 * np.arccos(np.sqrt(1 / (n - i))), reg[i], reg[i + 1])
        qc.cx(reg[i + 1], reg[i])


def ring_pairs(reg):
    reg = [int(q) for q in reg]
    n = len(reg)
    if n < 2:
        return []
    pairs = [(reg[i], reg[(i + 1) % n]) for i in range(n if n > 2 else 1)]
    return pairs[0::2] + pairs[1::2]  # even bonds, then odd bonds


def build_circuit(sub, p, mixer="xy"):
    one_hot_in_cost = mixer != "xy"
    h, J = ising(sub, one_hot_in_cost)
    gamma, beta = ParameterVector("g", p), ParameterVector("b", p)
    qc = QuantumCircuit(sub.n_qubits)
    if mixer == "xy":
        for r in sub.registers:
            w_state(qc, r)
    else:
        qc.h(range(sub.n_qubits))
    for k in range(p):
        for i, v in enumerate(h):
            qc.rz(2 * gamma[k] * float(v), i)
        for (i, j), v in J.items():
            qc.rzz(2 * gamma[k] * float(v), i, j)
        if mixer == "xy":
            for r in sub.registers:
                for i, j in ring_pairs(r):
                    qc.rxx(beta[k], i, j)
                    qc.ryy(beta[k], i, j)
        else:
            qc.rx(2 * beta[k], range(sub.n_qubits))
    qc.measure_all()
    return qc, gamma, beta


def counts_to_bits(counts):
    keys = list(counts)
    # Qiskit prints qubit 0 as the right-most character.
    bits = np.array([[int(c) for c in k[::-1]] for k in keys], dtype=int)
    return bits, np.array([counts[k] for k in keys], dtype=float)


def cvar(values, weights, alpha):
    """Mean of the best alpha fraction of shots: we keep the best sample, so tune for tails."""
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w)
    need = alpha * cum[-1]
    take = np.minimum(w, np.maximum(need - (cum - w), 0))
    return float((v * take).sum() / take.sum())


class QAOASolver:
    """Same `run` path for simulator, noisy simulator or a real backend via `sampler`."""

    def __init__(self, p=2, mixer="xy", shots=512, maxiter=40, alpha=0.3, seed=0,
                 sampler=None, backend=None):
        self.p, self.mixer, self.shots = p, mixer, shots
        self.maxiter, self.alpha = maxiter, alpha
        self.backend = backend or AerSimulator(method="statevector", seed_simulator=seed)
        self.sampler = sampler or SamplerV2(seed=seed)
        self.evals = 0

    def _sample(self, compiled, theta, shots):
        self.evals += 1
        res = self.sampler.run([(compiled, theta)], shots=shots).result()[0]
        return res.data.meas.get_counts()

    def solve(self, sub, init=None):
        qc, gamma, beta = build_circuit(sub, self.p, self.mixer)
        compiled = transpile(qc, self.backend, optimization_level=1)
        names = [q.name for q in compiled.parameters]

        def vector(theta):
            lookup = {f"g[{k}]": theta[k] for k in range(self.p)}
            lookup |= {f"b[{k}]": theta[self.p + k] for k in range(self.p)}
            return [lookup[n] for n in names]

        def objective(theta):
            bits, w = counts_to_bits(self._sample(compiled, vector(theta), self.shots))
            return cvar(energies(sub, bits, one_hot=True), w, self.alpha)

        if init is None:  # linear ramp: an annealing-like schedule, far better than random
            t = (np.arange(self.p) + 0.5) / self.p
            init = np.concatenate([0.9 * t, 0.7 * (1 - t)])
        res = minimize(objective, init, method="COBYLA",
                       options={"maxiter": self.maxiter, "rhobeg": 0.3})
        counts = self._sample(compiled, vector(res.x), 2048)
        bits, w = counts_to_bits(counts)
        return {"theta": res.x, "bits": bits, "weights": w, "compiled": compiled}


def best_feasible(sub, bits):
    best, best_x = np.inf, None
    for x in bits:
        if sub.is_feasible(x) and sub.rupees(x) < best:
            best, best_x = sub.rupees(x), x
    return best, best_x
