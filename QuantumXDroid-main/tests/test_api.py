from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app import app


@pytest.fixture
def client():
    return app.test_client()


CAR = {"lat": 9.55, "lon": 76.52, "soc": 30, "battery_kwh": 40, "ready": "17:00", "deadline": "22:00"}


def test_health_and_pages(client):
    assert client.get("/healthz").json == {"status": "ok"}
    assert client.get("/").status_code == 200
    assert client.get("/live").status_code == 200


def test_map_tiles_get_a_referer(client):
    assert client.get("/").headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_optimize_defaults_to_milp(client):
    r = client.post("/api/optimize", json={"vehicles": [CAR, CAR]})
    assert r.status_code == 200
    assert r.json["engine"] == "milp"
    assert r.json["quantum_info"]["proved_optimal"] is True
    assert len(r.json["schedule"]) == 2


@pytest.mark.parametrize("body", [
    {},
    {"vehicles": "x"},
    {"vehicles": []},
    {"vehicles": [1]},
    {"vehicles": [{**CAR, "soc": 500}]},
    {"vehicles": [{**CAR, "lat": "north"}]},
    {"vehicles": [{**CAR, "ready": "25:99"}]},
    {"vehicles": [{**CAR, "ready": "22:00", "deadline": "17:00"}]},
    {"vehicles": [CAR], "engine": "magic"},
    {"vehicles": [CAR] * 31, "engine": "qaoa"},
])
def test_optimize_rejects_bad_input(client, body):
    r = client.post("/api/optimize", json=body)
    assert r.status_code == 400
    assert "error" in r.json


def test_missing_route_is_json_404(client):
    r = client.get("/nope")
    assert r.status_code == 404


def test_simulate_gap(client):
    r = client.post("/api/simulate", json={"scenario": "gap"}).json
    assert r["policies"]["hold"]["metrics"]["total_rs"] > r["policies"]["rolling"]["metrics"]["total_rs"]
    assert len(r["slots"]) == 17


@pytest.mark.parametrize("body", [{"scenario": "x"}, {"scenario": "rush", "cars": 0},
                                  {"scenario": "rush", "cars": 81}, {"scenario": "rush", "seed": -1}])
def test_simulate_rejects_bad_input(client, body):
    assert client.post("/api/simulate", json=body).status_code == 400
