"""Problem data and the per-EV option model.

Everything is priced in rupees, so waiting, energy and driving share one
objective and no arbitrary weights are needed. All data is SYNTHETIC: the
station sites are rough Kochi locations; fleet, tariff and capacity are made up.
"""
from dataclasses import dataclass
import math
from pathlib import Path
import sys
import numpy as np

# Ensure workspace root is in sys.path when running file directly
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)


SLOT_H = 0.5        # 30-minute slots
N_SLOTS = 16        # 16:00 -> 24:00
TARGET_SOC = 0.8
KWH_PER_KM = 0.15
SPEED_KMH = 25
WAIT_RS_PER_H = 60  # value of a driver's time
DRIVE_RS_PER_KM = 2
DEFER_RS = 600      # penalty for not serving an EV this evening
RESERVE_SOC = 0.05  # never plan to arrive below 5 %
# Illustrative time-of-day tariff (Rs/kWh): shoulder, evening peak, night.
PRICE = np.array([7.0] * 4 + [11.0] * 8 + [5.0] * 4)


@dataclass(frozen=True)
class EV:
    id: int
    x: float
    y: float
    soc: float
    battery_kwh: float
    ready: int     # first slot the EV can leave for a station
    deadline: int  # charging must end by this slot


@dataclass(frozen=True)
class Charger:
    id: int
    station: str
    x: float
    y: float
    kw: float


@dataclass(frozen=True)
class Option:
    """One choice for one EV. charger == -1 means 'not served tonight'."""
    ev: int
    charger: int
    start: int
    dur: int
    cost: float
    energy_rs: float = 0.0
    wait_h: float = 0.0
    km: float = 0.0

    @property
    def slots(self):
        return range(self.start, self.start + self.dur)

    def conflicts(self, other):
        return (self.charger >= 0 and self.charger == other.charger
                and self.start < other.start + other.dur
                and other.start < self.start + self.dur)


STATIONS = [  # name, x km, y km, chargers, kW per charger
    ("Aluva", 2, 14, 2, 30), ("Edappally", 0, 5, 2, 60), ("Kakkanad", 7, 4, 2, 30),
    ("Vyttila", 3, -2, 2, 30), ("MG Road", -2, -1, 1, 15),
]


def chargers():
    out = []
    for name, x, y, n, kw in STATIONS:
        out += [Charger(len(out) + i, name, x, y, kw) for i in range(n)]
    return out


def make_fleet(n, seed, chargers_=None):
    r = np.random.default_rng(seed)
    if chargers_ is not None:
        xs = [c.x for c in chargers_]
        ys = [c.y for c in chargers_]
        x_min, x_max = min(xs) - 2.0, max(xs) + 2.0
        y_min, y_max = min(ys) - 2.0, max(ys) + 2.0
    else:
        x_min, x_max = -4.0, 9.0
        y_min, y_max = -4.0, 15.0
    fleet = []
    for i in range(n):
        ready = int(np.clip(round(r.normal(4, 2)), 0, 10))
        fleet.append(EV(i, float(r.uniform(x_min, x_max)), float(r.uniform(y_min, y_max)),
                        float(r.uniform(0.12, 0.5)), float(r.choice([30, 40, 50])),
                        ready, int(min(N_SLOTS, ready + r.integers(5, 12)))))
    return fleet


def enumerate_options(ev, chargers_):
    """Classical preprocessing: keep only physically possible options."""
    opts = [Option(ev.id, -1, 0, 0, DEFER_RS)]
    for c in chargers_:
        km = 1.3 * math.hypot(ev.x - c.x, ev.y - c.y)  # road-winding factor
        if km * KWH_PER_KM > (ev.soc - RESERVE_SOC) * ev.battery_kwh:
            continue  # battery cannot reach this station
        kwh = (TARGET_SOC - ev.soc) * ev.battery_kwh + km * KWH_PER_KM
        dur = math.ceil(kwh / (c.kw * SLOT_H))
        first = ev.ready + math.ceil(km / SPEED_KMH / SLOT_H)
        for s in range(first, ev.deadline - dur + 1):
            energy = kwh / dur * PRICE[s:s + dur].sum()
            wait = (s - first) * SLOT_H
            opts.append(Option(ev.id, c.id, s, dur,
                               energy + wait * WAIT_RS_PER_H + km * DRIVE_RS_PER_KM,
                               energy, wait, km))
    return opts


class Instance:
    def __init__(self, n, seed=0, use_ocm=False, ocm_origin="pallam", chargers_list=None):
        if chargers_list is not None:
            self.chargers = chargers_list
            self.ocm_meta = None
            self.fleet = make_fleet(n, seed, self.chargers)
        elif use_ocm:
            from evcharge.ocm import build_chargers_from_ocm
            self.chargers, self.ocm_meta = build_chargers_from_ocm(origin=ocm_origin)
            self.fleet = make_fleet(n, seed, self.chargers)
        else:
            self.chargers = chargers()
            self.ocm_meta = None
            self.fleet = make_fleet(n, seed)
        self.options = [enumerate_options(e, self.chargers) for e in self.fleet]


def is_feasible(schedule):
    chosen = list(schedule.values())
    return not any(a.conflicts(b) for i, a in enumerate(chosen) for b in chosen[i + 1:])


def metrics(inst, schedule):
    served = [o for o in schedule.values() if o.charger >= 0]
    load = np.zeros(N_SLOTS)
    for o in served:
        for s in o.slots:
            load[s] += inst.chargers[o.charger].kw
    return {
        "total_rs": round(sum(o.cost for o in schedule.values()), 1),
        "energy_rs": round(sum(o.energy_rs for o in served), 1),
        "avg_wait_min": round(60 * float(np.mean([o.wait_h for o in served])), 1) if served else 0.0,
        "max_wait_min": round(60 * max((o.wait_h for o in served), default=0), 1),
        "served": len(served), "unserved": len(schedule) - len(served),
        "peak_kw": float(load.max()), "avg_km": round(float(np.mean([o.km for o in served])), 2) if served else 0.0,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("  EV CHARGING SCHEDULER - INSTANCE MODEL")
    print("=" * 60)

    print("\n[1] Default Synthetic Instance (5 stations, 9 chargers):")
    syn_inst = Instance(10, seed=42)
    print(f"  - Fleet: {len(syn_inst.fleet)} EVs")
    print(f"  - Chargers: {len(syn_inst.chargers)}")
    print(f"  - Total feasible charging options: {sum(len(o) for o in syn_inst.options)}")

    print("\n[2] Real OpenChargeMap Instance (Kerala Network):")
    ocm_inst = Instance(10, seed=42, use_ocm=True, ocm_origin="pallam")
    print(f"  - Fleet: {len(ocm_inst.fleet)} EVs")
    print(f"  - Real Chargers: {len(ocm_inst.chargers)} physical bays")
    print(f"  - Origin Anchor: {ocm_inst.ocm_meta['origin_name'].upper()} {ocm_inst.ocm_meta['origin_coords']}")
    print(f"  - Total feasible charging options: {sum(len(o) for o in ocm_inst.options)}")
    print("\n  Connected Real OCM Stations:")
    for s in ocm_inst.ocm_meta["station_summaries"]:
        print(f"    * [OCM-{s['ocm_id']}] {s['name'][:35]:<35} ({s['x_km']:>+5.1f} km, {s['y_km']:>+5.1f} km) -> {s['bays']} bays")

