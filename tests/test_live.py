from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from evcharge.instance import Instance, is_feasible
from evcharge.live import depart_slot, gap_scenario, greedy, rolling, run_all


def total(schedule):
    return sum(o.cost for o in schedule.values())


def test_second_car_uses_the_bay_while_the_first_is_driving():
    inst = gap_scenario()
    hold, eta = greedy(inst, hold_while_driving=True), greedy(inst)
    first, second = eta[0], eta[1]
    assert depart_slot(first) < second.start < first.start  # the gap really is used
    assert eta[0].start == hold[0].start                    # and car 0 is not delayed
    assert second.start < hold[1].start
    assert total(eta) < total(hold)


def test_car_on_the_road_is_never_moved():
    inst = Instance(80, 3)
    final, events = rolling(inst)
    assert is_feasible(final)
    assert any(e["moved"] for e in events)  # otherwise this test proves nothing
    slots = [e["slot"] for e in events]
    for t, later in zip(slots, slots[1:]):
        before, _ = rolling(inst, until=t)
        after, _ = rolling(inst, until=later)
        for car, o in before.items():
            if o.charger >= 0 and depart_slot(o) <= t:
                assert after[car] == o


@pytest.mark.parametrize("seed", range(4))
def test_policy_ordering(seed):
    r = run_all(Instance(40, seed))
    cost = {name: v["metrics"]["total_rs"] for name, v in r.items()}
    assert cost["hindsight"] <= cost["rolling"] + 1e-6  # nobody beats perfect foresight
    assert cost["rolling"] <= cost["nearest"]
    assert all(v["metrics"]["served"] + v["metrics"]["unserved"] == 40 for v in r.values())


def test_plan_ignores_cars_that_have_not_asked_yet():
    inst = Instance(20, 5)
    t = sorted({e.ready for e in inst.fleet})[1]
    plan, _ = rolling(inst, until=t)
    assert set(plan) == {e.id for e in inst.fleet if e.ready <= t}
