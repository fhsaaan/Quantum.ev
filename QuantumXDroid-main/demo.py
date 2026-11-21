"""Quick demo: python demo.py [cars] [seed] [--ocm]   (about a minute for 20 cars)"""
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import sys

from evcharge.instance import Instance, N_SLOTS, is_feasible, metrics
from evcharge.solvers import exact_milp, fcfs, lns, qaoa_sub_solver

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = [a for a in sys.argv[1:] if a.startswith("--")]

cars = int(args[0]) if len(args) > 0 else 15
seed = int(args[1]) if len(args) > 1 else 0
use_ocm = "--ocm" in flags


def clock(slot):
    return f"{16 + slot // 2:02d}:{30 * (slot % 2):02d}"


inst = Instance(cars, seed, use_ocm=use_ocm, ocm_origin="pallam")
dataset_name = "OpenChargeMap (Pallam KSEB & Kerala network)" if use_ocm else "Synthetic"
start = fcfs(inst)
print(f"Dataset: {dataset_name}")
print(f"{cars} cars, {len(inst.chargers)} chargers, slots 16:00-24:00, seed {seed}. Running QAOA...")
best, info = lns(inst, start, qaoa_sub_solver(p=2, mixer="xy", seed=seed), iters=40, patience=15, seed=seed)
opt, proved = exact_milp(inst)

print(f"\n{'Car':>3}  {'Station':<26} {'Chg':>3}  {'Start':<5}  {'End':<5}  {'Wait':>7}  {'Rs':>6}")
for e in sorted(best):
    o = best[e]
    if o.charger < 0:
        print(f"{e:>3}  not served tonight")
        continue
    st_name = inst.chargers[o.charger].station[:26]
    print(f"{e:>3}  {st_name:<26} {o.charger:>3}  {clock(o.start):<5}  "
          f"{clock(o.start + o.dur):<5}  {60 * o.wait_h:>3.0f} min  {o.cost:>6.1f}")


print(f"\n{'Method':<22}{'Total Rs':>10}{'Energy Rs':>11}{'Avg wait':>10}{'Max wait':>10}{'Peak kW':>9}{'Unserved':>10}")
for name, sched in [("Nearest station", start), ("QAOA hybrid", best), ("Exact optimum", opt)]:
    m = metrics(inst, sched)
    print(f"{name:<22}{m['total_rs']:>10}{m['energy_rs']:>11}{m['avg_wait_min']:>10}"
          f"{m['max_wait_min']:>10}{m['peak_kw']:>9}{m['unserved']:>10}")

q, f, o = [metrics(inst, s)["total_rs"] for s in (best, start, opt)]
print(f"\nSaved vs nearest station: {100 * (1 - q / f):.1f}%   Above optimum: {100 * (q / o - 1):.2f}%")
print(f"Qubits per round: {info['max_qubits']}   QAOA time: {info['seconds']}s   "
      f"Valid schedule: {is_feasible(best)}   Optimum proved: {proved}")
