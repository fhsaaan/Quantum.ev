"""Live dispatch: cars ask for a charge during the evening, not all at 16:00.

The batch solvers in solvers.py assume every car is known up front. Real dispatch
is online, and it has one specific waste: a bay sits empty while its next car is
still driving there. A bay should only be blocked from the car's ETA, and the
plan should be re-solved each time a new car appears.

Policies, all seeing only the cars that have asked so far (except hindsight):
    hold     the bay is locked from the moment its car sets off (the naive system)
    nearest  bay reserved only for the charge itself; nearest station; no re-plan
    cheapest bay reserved only for the charge itself; cheapest option; no re-plan
    rolling  re-solves all cars that have not set off, whenever a new car appears
    hindsight  the batch optimum with the whole evening known (a bound, not a policy)

Cars that have set off keep their booking, so a driver on the road is never moved.
"""
from dataclasses import replace
import math
from types import SimpleNamespace

from .instance import (Charger, EV, Instance, Option, SLOT_H, SPEED_KMH,
                       enumerate_options, is_feasible, metrics)
from .solvers import exact_milp

STICKY_RS = 5.0  # a driver is only re-routed if it saves more than this


def drive_slots(option):
    return math.ceil(option.km / SPEED_KMH / SLOT_H)


def depart_slot(option):
    return option.start - drive_slots(option)


def greedy(inst, rule="nearest", hold_while_driving=False):
    """One decision per car, in request order, never revisited."""
    busy = set()
    plan = {}

    def blocked(o):
        return range(depart_slot(o) if hold_while_driving else o.start, o.start + o.dur)

    key = (lambda o: (round(o.km, 3), o.start)) if rule == "nearest" else (lambda o: o.cost)
    for ev in sorted(inst.fleet, key=lambda e: (e.ready, e.id)):
        free = [o for o in inst.options[ev.id] if o.charger >= 0
                and all((o.charger, s) not in busy for s in blocked(o))]
        pick = min(free, key=key) if free else inst.options[ev.id][0]
        plan[ev.id] = pick
        if pick.charger >= 0:
            busy.update((pick.charger, s) for s in blocked(pick))
    return plan


def rolling(inst, time_limit=10, until=None):
    """Re-solve exactly at each slot in which a new car appears (optionally stop at `until`)."""
    plan, events = {}, []
    known = set()
    for t in sorted({e.ready for e in inst.fleet}):
        if until is not None and t > until:
            break
        arrivals = [e.id for e in inst.fleet if e.ready == t]
        known.update(arrivals)
        view, sticky = [], {}
        for ev in inst.fleet:
            cur = plan.get(ev.id)
            if ev.id not in known:
                view.append([Option(ev.id, -1, 0, 0, 0.0)])  # not asked yet
            elif cur is not None and cur.charger >= 0 and depart_slot(cur) <= t:
                view.append([cur])                           # on the road or charging
            else:
                opts = [o for o in inst.options[ev.id] if o.charger < 0 or depart_slot(o) >= t]
                if cur is not None:
                    sticky[ev.id] = replace(cur, cost=cur.cost - STICKY_RS)
                    opts = [sticky[ev.id] if o == cur else o for o in opts]
                view.append(opts)
        solved, _ = exact_milp(SimpleNamespace(fleet=inst.fleet, chargers=inst.chargers,
                                               options=view), time_limit=time_limit)
        moved = []
        for e in sorted(known):
            new = solved[e]
            if e in sticky and new == sticky[e]:
                new = plan[e]  # same booking: undo the stickiness discount
            elif e in plan and (new.charger, new.start) != (plan[e].charger, plan[e].start):
                moved.append(e)
            plan[e] = new
        events.append({"slot": t, "arrivals": arrivals, "moved": moved})
    return plan, events


POLICIES = ("hold", "nearest", "cheapest", "rolling", "hindsight")


def run_all(inst):
    """Every policy on one instance: {name: {"schedule", "metrics", ...}}."""
    roll, events = rolling(inst)
    schedules = {
        "hold": greedy(inst, "nearest", hold_while_driving=True),
        "nearest": greedy(inst, "nearest"),
        "cheapest": greedy(inst, "cheapest"),
        "rolling": roll,
        "hindsight": exact_milp(inst)[0],
    }
    out = {}
    for name, schedule in schedules.items():
        if not is_feasible(schedule):
            raise RuntimeError(f"{name} produced an infeasible schedule")
        out[name] = {"schedule": schedule, "metrics": metrics(inst, schedule)}
    out["rolling"]["events"] = events
    return out


def custom_instance(fleet, chargers_):
    inst = Instance(0, chargers_list=chargers_)
    inst.fleet = fleet
    inst.options = [enumerate_options(e, chargers_) for e in fleet]
    return inst


def gap_scenario():
    """Smallest case of the bay-gap question: one 60 kW bay, three cars.

    Car 0 asks at 16:00 but is 90 minutes away, so it reaches the bay at 17:30.
    Car 1 is next door at 16:30 and needs one 30-minute slot: it fits in the gap.
    Car 2 asks at 17:30 and takes the bay after Car 0.
    """
    hub = [Charger(0, "Demo Hub", 0.0, 0.0, 60.0)]
    fleet = [
        EV(0, 25.0, 0.0, 0.40, 50.0, ready=0, deadline=8),
        EV(1, 1.0, 0.0, 0.60, 30.0, ready=1, deadline=8),
        EV(2, 0.0, 1.0, 0.60, 30.0, ready=3, deadline=8),
    ]
    return custom_instance(fleet, hub)
