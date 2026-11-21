"""Quantum.ev EV charging dispatcher: Flask API and dashboards.

Local:       python app.py
Production:  waitress-serve --host=0.0.0.0 --port=$PORT --threads=8 app:app
"""
from functools import lru_cache
import logging
import math
import os
from pathlib import Path
import re
import sys
import threading
import time

for _var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, render_template, request

from evcharge.instance import EV, Instance, N_SLOTS, PRICE, is_feasible, metrics
from evcharge.live import POLICIES, custom_instance, depart_slot, drive_slots, gap_scenario, run_all
from evcharge.ocm import ORIGINS, build_chargers_from_ocm, km_to_lat_lon, lat_lon_to_km, load_ocm_stations
from evcharge.solvers import exact_milp, fcfs, lns, qaoa_sub_solver

log = logging.getLogger("quantumx")

app = Flask(__name__,
            template_folder=str(ROOT / "web" / "templates"),
            static_folder=str(ROOT / "web" / "static"))
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

ORIGIN = ORIGINS["pallam"]
MAX_MILP_CARS = 200
MAX_QAOA_CARS = 30
MAX_SIM_CARS = 80
QAOA_SLOTS = int(os.environ.get("QAOA_CONCURRENCY", "1"))  # QAOA pins a CPU for about a minute
_qaoa_gate = threading.BoundedSemaphore(QAOA_SLOTS)
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class BadRequest(ValueError):
    """Client input error; the message is safe to return."""


def slot_to_time(slot):
    return f"{(16 + slot // 2) % 24:02d}:{30 * (slot % 2):02d}"


def time_to_slot(text):
    if not isinstance(text, str) or not _TIME.match(text):
        raise BadRequest(f"Invalid time {text!r}; expected HH:MM")
    h, m = map(int, text.split(":"))
    return max(0, min(N_SLOTS - 1, (h - 16) * 2 + (1 if m >= 30 else 0)))


def number(vehicle, key, low, high, default=None):
    value = vehicle.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadRequest(f"{key} must be a number")
    if not low <= value <= high:
        raise BadRequest(f"{key} must be between {low} and {high}")
    return float(value)


def parse_fleet(raw):
    fleet = []
    for i, v in enumerate(raw):
        if not isinstance(v, dict):
            raise BadRequest("Each vehicle must be an object")
        x, y = lat_lon_to_km(number(v, "lat", -90, 90), number(v, "lon", -180, 180), *ORIGIN)
        ready = time_to_slot(v.get("ready", "16:00"))
        deadline = min(time_to_slot(v.get("deadline", "23:30")) + 1, N_SLOTS)
        if deadline <= ready:
            raise BadRequest(f"Vehicle {i}: deadline must be after ready time")
        fleet.append(EV(i, x, y, number(v, "soc", 1, 100, 25) / 100,
                        number(v, "battery_kwh", 5, 200, 40), ready, deadline))
    return fleet


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # OpenStreetMap's tile servers reject browsers that send no Referer, so keep the origin.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.errorhandler(BadRequest)
def on_bad_request(err):
    return jsonify({"error": str(err)}), 400


@app.errorhandler(413)
def on_too_large(_):
    return jsonify({"error": "Request too large"}), 413


@app.errorhandler(Exception)
def on_error(err):
    code = getattr(err, "code", None)
    if isinstance(code, int) and code < 500:
        return jsonify({"error": getattr(err, "description", "Request failed")}), code
    log.exception("Unhandled error on %s", request.path)
    return jsonify({"error": "Internal server error"}), 500


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/live")
def live():
    return render_template("live.html")


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/stations")
def api_stations():
    return jsonify(load_ocm_stations())


@app.route("/api/tariff")
def api_tariff():
    return jsonify({"slots": [slot_to_time(s) for s in range(N_SLOTS)],
                    "price_rs_kwh": PRICE.tolist(),
                    "note": "Illustrative tariff, not a published KSEB rate."})


def schedule_rows(inst, schedule, raw):
    rows = []
    for ev in inst.fleet:
        o = schedule[ev.id]
        row = {"ev_id": ev.id, "ev_lat": raw[ev.id]["lat"], "ev_lon": raw[ev.id]["lon"],
               "soc": round(ev.soc * 100, 1), "served": o.charger >= 0, "cost_rs": round(o.cost, 1)}
        if o.charger >= 0:
            c = inst.chargers[o.charger]
            lat, lon = km_to_lat_lon(c.x, c.y, *ORIGIN)
            row.update({"station": c.station, "charger_id": o.charger, "charger_kw": c.kw,
                        "station_lat": lat, "station_lon": lon,
                        "start_time": slot_to_time(o.start), "end_time": slot_to_time(o.start + o.dur),
                        "wait_min": round(o.wait_h * 60), "energy_rs": round(o.energy_rs, 1),
                        "distance_km": round(o.km, 1)})
        rows.append(row)
    return rows


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    """Batch plan for a known fleet. engine: "milp" (default, instant) or "qaoa" (research, slow)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("vehicles"), list):
        raise BadRequest("Body must be JSON with a 'vehicles' list")
    engine = data.get("engine", "milp")
    if engine not in ("milp", "qaoa"):
        raise BadRequest("engine must be 'milp' or 'qaoa'")
    raw = data["vehicles"]
    limit = MAX_QAOA_CARS if engine == "qaoa" else MAX_MILP_CARS
    if not 1 <= len(raw) <= limit:
        raise BadRequest(f"Fleet size must be 1-{limit} vehicles for engine '{engine}'")

    chargers_, _ = build_chargers_from_ocm(origin="pallam")
    inst = custom_instance(parse_fleet(raw), chargers_)
    t0 = time.time()
    baseline = fcfs(inst)
    optimum, proved = exact_milp(inst, time_limit=30)
    chosen, info = optimum, {"history": [], "max_qubits": 0, "seconds": 0}

    if engine == "qaoa":
        if not _qaoa_gate.acquire(blocking=False):
            return jsonify({"error": "The quantum simulator is busy. Try again in a minute."}), 429
        try:
            n = len(raw)
            chosen, info = lns(inst, baseline, qaoa_sub_solver(p=2, mixer="xy", seed=0),
                               iters=min(30, max(10, n * 3)), patience=10, seed=0)
        finally:
            _qaoa_gate.release()

    comparison = {"fcfs": metrics(inst, baseline), "optimal": metrics(inst, optimum)}
    if engine == "qaoa":
        comparison["qaoa"] = metrics(inst, chosen)
    return jsonify({
        "engine": engine,
        "schedule": schedule_rows(inst, chosen, raw),
        "comparison": comparison,
        "quantum_info": {"qubits_per_round": info["max_qubits"], "qaoa_time_s": info["seconds"],
                         "total_solve_time_s": round(time.time() - t0, 2),
                         "is_feasible": is_feasible(chosen), "proved_optimal": bool(proved),
                         "iterations": len(info["history"])},
    })


@lru_cache(maxsize=256)
def simulate(scenario, cars, seed):
    inst = gap_scenario() if scenario == "gap" else Instance(cars, seed)
    results = run_all(inst)
    policies = {}
    for name in POLICIES:
        rows = []
        for e, o in sorted(results[name]["schedule"].items()):
            if o.charger < 0:
                continue
            rows.append({"car": e, "charger": o.charger, "depart": depart_slot(o),
                         "drive": drive_slots(o), "start": o.start, "end": o.start + o.dur,
                         "wait_min": round(o.wait_h * 60), "cost_rs": round(o.cost, 1)})
        policies[name] = {"metrics": results[name]["metrics"], "bookings": rows}
    return {
        "scenario": scenario, "seed": seed,
        "slots": [slot_to_time(s) for s in range(N_SLOTS + 1)],
        "price_rs_kwh": PRICE.tolist(),
        "chargers": [{"id": c.id, "station": c.station, "kw": c.kw} for c in inst.chargers],
        "cars": [{"id": e.id, "asks": e.ready, "battery_kwh": e.battery_kwh, "soc": round(e.soc * 100)}
                 for e in inst.fleet],
        "events": results["rolling"]["events"],
        "policies": policies,
    }


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    """Play one evening through every dispatch policy. Synthetic fleet."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Body must be JSON")
    scenario = data.get("scenario", "gap")
    if scenario not in ("gap", "rush"):
        raise BadRequest("scenario must be 'gap' or 'rush'")
    cars, seed = data.get("cars", 30), data.get("seed", 0)
    if isinstance(cars, bool) or not isinstance(cars, int) or not 1 <= cars <= MAX_SIM_CARS:
        raise BadRequest(f"cars must be an integer from 1 to {MAX_SIM_CARS}")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 9999:
        raise BadRequest("seed must be an integer from 0 to 9999")
    return jsonify(simulate(scenario, cars, seed))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Debug stays off unless asked for: Werkzeug's debugger allows remote code execution.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1",
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5000")))
