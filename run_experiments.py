"""Regenerates every number in the report.  python run_experiments.py [sub|fleet|noise|live|all]"""
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import json
import sys
import time
from pathlib import Path
import numpy as np
from qiskit import transpile
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2

from evcharge.instance import Instance, metrics, is_feasible
from evcharge.qaoa import QAOASolver, build_circuit
from evcharge.qubo import brute_force, build, select_options
from evcharge.solvers import (exact_milp, exact_sub_solver, fcfs, lns, pick_group,
                              qaoa_sub_solver, random_sub_solver)

OUT = Path("results")
OUT.mkdir(exist_ok=True)


def save(name, data):
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1))


def sub_instances(n_sub, group, k, seed0=100):
    """Real sub-problems as they arise inside the loop, keeping only non-trivial ones."""
    subs, seed = [], seed0
    while len(subs) < n_sub:
        inst = Instance(30, seed)
        sched, rng = fcfs(inst), np.random.default_rng(seed)
        sub = build(select_options(inst, sched, pick_group(inst, sched, group, rng), k))
        seed += 1
        if brute_force(sub)[2] >= 8 and sub.n_qubits == group * k:
            subs.append(sub)
    return subs


def quality(sub, out, opt_rs):
    w = out["weights"] / out["weights"].sum()
    ok = np.array([sub.is_feasible(x) for x in out["bits"]])
    hit = np.array([v and abs(sub.rupees(x) - opt_rs) < 1e-6 for x, v in zip(out["bits"], ok)])
    return float(w[ok].sum()), float(w[hit].sum())


def uniform_p_opt(sub, opt_rs):
    """P(optimum) for a uniform random valid-format pick: the classical control."""
    from itertools import product
    total = hits = 0
    for pick in product(*[r.tolist() for r in sub.registers]):
        total += 1
        x = np.zeros(sub.n_qubits, dtype=int)
        x[list(pick)] = 1
        hits += sub.is_feasible(x) and abs(sub.rupees(x) - opt_rs) < 1e-6
    return hits / total


def exp_sub():
    rows = []
    for group, k, n_sub in [(3, 4, 30), (4, 4, 10)]:
        subs = sub_instances(n_sub, group, k)
        for mixer in ("x", "xy"):
            for p in (1, 2, 3):
                t0 = time.time()
                valid, popt, amp = [], [], []
                for i, sub in enumerate(subs):
                    opt = brute_force(sub)[0]
                    v, h = quality(sub, QAOASolver(p=p, mixer=mixer, maxiter=60, seed=i).solve(sub), opt)
                    u = uniform_p_opt(sub, opt)
                    valid.append(v); popt.append(h); amp.append(h / u)
                rows.append({"qubits": group * k, "mixer": mixer, "p": p, "instances": n_sub,
                             "valid": round(np.mean(valid), 4), "p_opt": round(np.mean(popt), 4),
                             "p_opt_se": round(np.std(popt) / np.sqrt(n_sub), 4),
                             "amplification_median": round(float(np.median(amp)), 2)})
                print(rows[-1], f"{time.time() - t0:.0f}s", flush=True)
                save("subproblems", rows)


def exp_fleet():
    rows, hist = [], {}
    for n in (10, 20, 30, 50):
        for seed in range(3):
            inst = Instance(n, seed)
            start = fcfs(inst)
            opt, proved = exact_milp(inst)
            row = {"n": n, "seed": seed, "proved_optimal": bool(proved),
                   "fcfs": metrics(inst, start), "milp": metrics(inst, opt)}
            solvers = {"lns_qaoa": qaoa_sub_solver(p=2, mixer="xy", seed=seed),
                       "lns_exact": exact_sub_solver,
                       "lns_random1": random_sub_solver(1, seed)}
            for name, solver in solvers.items():
                best, info = lns(inst, start, solver, iters=40, patience=15, seed=seed)
                assert is_feasible(best)
                row[name] = metrics(inst, best) | {"seconds": info["seconds"], "qubits": info["max_qubits"]}
                if n == 30 and seed == 0:
                    hist[name] = info["history"]
                    if name == "lns_qaoa":
                        save("schedule_30ev", [vars(o) | {"station": inst.chargers[o.charger].station
                                                          if o.charger >= 0 else None}
                                               for o in best.values()])
            rows.append(row)
            print(n, seed, {k: row[k]["total_rs"] for k in ("fcfs", "lns_random1", "lns_qaoa", "lns_exact", "milp")},
                  row["lns_qaoa"]["seconds"], flush=True)
            save("fleet", rows)
            save("history", hist)


def exp_noise():
    """Same trained circuit on an ideal simulator and on a noise model of a real IBM chip."""
    from qiskit_ibm_runtime.fake_provider import FakeTorino
    device = FakeTorino()
    rows = []
    for i, sub in enumerate(sub_instances(5, 2, 4)):
        opt = brute_force(sub)[0]
        ideal = QAOASolver(p=1, mixer="xy", seed=i, maxiter=60)
        out = ideal.solve(sub)
        qc, gamma, beta = build_circuit(sub, 1, "xy")
        bound = qc.assign_parameters({gamma[0]: out["theta"][0], beta[0]: out["theta"][1]})
        hw = transpile(bound, device, optimization_level=3, seed_transpiler=i)
        noisy = AerSimulator.from_backend(device, seed_simulator=i)
        counts = noisy.run(hw, shots=4096).result().get_counts()
        from evcharge.qaoa import counts_to_bits
        bits, w = counts_to_bits(counts)
        v_n, h_n = quality(sub, {"bits": bits, "weights": w}, opt)
        v_i, h_i = quality(sub, out, opt)
        rows.append({"qubits": sub.n_qubits, "two_qubit_gates": hw.count_ops().get("cz", 0),
                     "depth": hw.depth(), "ideal_valid": round(v_i, 3), "ideal_p_opt": round(h_i, 3),
                     "noisy_valid": round(v_n, 3), "noisy_p_opt": round(h_n, 3),
                     "uniform_p_opt": round(uniform_p_opt(sub, opt), 3)})
        print(rows[-1], flush=True)
    save("noise", rows)


def exp_live():
    """Online dispatch policies. Each car is unknown until it asks for a charge."""
    from evcharge.live import POLICIES, run_all
    rows = []
    for n in (15, 30, 50, 80):
        runs = [run_all(Instance(n, seed)) for seed in range(10)]
        row = {"cars": n, "seeds": len(runs)}
        for name in POLICIES:
            row[name] = {k: round(float(np.mean([r[name]["metrics"][k] for r in runs])), 1)
                         for k in ("total_rs", "avg_wait_min", "unserved")}
        row["moved_per_evening"] = float(np.mean([sum(len(e["moved"]) for e in r["rolling"]["events"])
                                                  for r in runs]))
        rows.append(row)
        print(row, flush=True)
        save("live", rows)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("sub", "all"):
        exp_sub()
    if what in ("fleet", "all"):
        exp_fleet()
    if what in ("noise", "all"):
        exp_noise()
    if what in ("live", "all"):
        exp_live()
