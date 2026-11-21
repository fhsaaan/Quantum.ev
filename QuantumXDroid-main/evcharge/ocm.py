"""OpenChargeMap (OCM) integration for EV charging optimization.

Provides utilities to load real station data from OpenChargeMap (including
the Pallam KSEB EVCS OCM-313584 and Kerala fast charging networks),
project real GPS coordinates to a local kilometer coordinate system,
and convert physical charging bays into Charger instances for the optimization model.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys

from typing import List, Optional, Tuple, Dict, Any

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)


from evcharge.instance import Charger


DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_DATASET = DATA_DIR / "ocm_kerala.json"

# Known reference origins (lat, lon)
ORIGINS = {
    "pallam": (9.543065, 76.514231),  # Pallam KSEB station (OCM-313584)
    "kottayam": (9.568000, 76.520000), # Central Kottayam
    "kochi": (9.939769, 76.330848),    # Maradu / South Kochi
}


def lat_lon_to_km(
    lat: float, lon: float, origin_lat: float, origin_lon: float
) -> Tuple[float, float]:
    """Projects (lat, lon) to Cartesian (x, y) km coordinates relative to origin.
    
    Uses standard equirectangular projection valid for local regional spans (< 100 km).
    """
    rad = math.radians(origin_lat)
    x = (lon - origin_lon) * 111.32 * math.cos(rad)
    y = (lat - origin_lat) * 110.57
    return round(x, 2), round(y, 2)


def km_to_lat_lon(
    x: float, y: float, origin_lat: float, origin_lon: float
) -> Tuple[float, float]:
    """Inverse projection from Cartesian (x, y) km back to (lat, lon)."""
    rad = math.radians(origin_lat)
    lat = origin_lat + y / 110.57
    lon = origin_lon + x / (111.32 * math.cos(rad))
    return round(lat, 6), round(lon, 6)


def load_ocm_stations(dataset_path: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    """Loads station metadata from the local OpenChargeMap dataset."""
    path = Path(dataset_path) if dataset_path else DEFAULT_DATASET
    if not path.exists():
        raise FileNotFoundError(f"OCM dataset not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_chargers_from_ocm(
    stations: Optional[List[Dict[str, Any]]] = None,
    origin: str | Tuple[float, float] = "pallam",
    min_kw: float = 10.0,
    max_stations: Optional[int] = None,
) -> Tuple[List[Charger], Dict[str, Any]]:
    """Converts OpenChargeMap station data into a list of Charger objects.
    
    Args:
        stations: Optional list of station dicts; if None, loads default Kerala dataset.
        origin: Name of reference origin ('pallam', 'kochi', 'kottayam') or (lat, lon) tuple.
        min_kw: Minimum charger power in kW to include (default 10 kW filters out slow 3.3 kW sockets).
        max_stations: Maximum number of stations to include.

    Returns:
        (chargers, metadata_dict)
    """
    if stations is None:
        stations = load_ocm_stations()

    if isinstance(origin, str):
        if origin not in ORIGINS:
            raise ValueError(f"Unknown origin '{origin}'. Choose from {list(ORIGINS.keys())} or pass (lat, lon)")
        orig_lat, orig_lon = ORIGINS[origin]
    else:
        orig_lat, orig_lon = origin

    if max_stations:
        stations = stations[:max_stations]

    chargers: List[Charger] = []
    meta = {
        "origin_name": origin if isinstance(origin, str) else "custom",
        "origin_coords": (orig_lat, orig_lon),
        "stations_loaded": len(stations),
        "station_summaries": [],
    }

    cid = 0
    for st in stations:
        lat = st["latitude"]
        lon = st["longitude"]
        name = st["name"]
        x, y = lat_lon_to_km(lat, lon, orig_lat, orig_lon)

        station_chargers_count = 0
        for chg in st.get("chargers", []):
            kw = float(chg.get("kw", 30.0))
            if kw < min_kw:
                continue
            count = int(chg.get("count", 1))
            for _ in range(count):
                chargers.append(Charger(id=cid, station=name, x=x, y=y, kw=kw))
                cid += 1
                station_chargers_count += 1

        meta["station_summaries"].append({
            "ocm_id": st.get("ocm_id"),
            "name": name,
            "x_km": x,
            "y_km": y,
            "lat": lat,
            "lon": lon,
            "bays": station_chargers_count,
        })

    return chargers, meta
