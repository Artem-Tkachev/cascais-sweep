import json
import os
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union
from collections import defaultdict
import h3
import pandas as pd

METRIC_CRS = 3763
BUFFER_M = 30
ABANDON_TIME = 120
MATCH_M = 5
H3_RES = 9                          # same hexagons as analytics.py
SNAP_DIR = "data/snapshots"
#SNAP_DIR = "data/snapshots copy"
STATIONS_FILE = "data/station_information.json"
STOPS_FILES = ["data/stops.csv", "temp/stops.csv"]   # bus stops (TML, GTFS), first one that exists
DATA_FILE = "data/data.js"          # written by analytics.py, has demand per hexagon
LISBON = ZoneInfo("Europe/Lisbon")  # data times are Lisbon time, also on a UTC server

def load_zone():
    stations_raw = json.load(open(STATIONS_FILE))["data"]["stations"]
    stations = gpd.GeoDataFrame(
        [{"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in stations_raw],
        geometry=[shape(s["station_area"]) for s in stations_raw], crs=4326)
    station_m = stations.to_crs(METRIC_CRS)
    allowed_zone = unary_union(station_m.buffer(BUFFER_M))
    return allowed_zone

def load_stops():
    # bus stops near Cascais in metres, like in analytics.py (box = stations +- 0.02 degrees)
    found = [p for p in STOPS_FILES if os.path.exists(p)]
    if not found:
        print(f"Warning: no stops.csv in {STOPS_FILES} - bus stops will be empty")
        return None
    stations_raw = json.load(open(STATIONS_FILE))["data"]["stations"]
    lats = [s["lat"] for s in stations_raw]
    lons = [s["lon"] for s in stations_raw]
    stops = pd.read_csv(found[0], low_memory=False).dropna(subset=["stop_lat", "stop_lon"])
    box = stops[stops.stop_lat.between(min(lats) - .02, max(lats) + .02) &
                stops.stop_lon.between(min(lons) - .02, max(lons) + .02)]
    return gpd.GeoDataFrame(box[["stop_name"]], geometry=gpd.points_from_xy(box.stop_lon, box.stop_lat),
                            crs=4326).to_crs(METRIC_CRS)

def load_demand():
    # trips started per day in every H3 hexagon, computed by analytics.py
    if not os.path.exists(DATA_FILE):
        print(f"Warning: {DATA_FILE} not found - demand will be empty")
        return None
    text = open(DATA_FILE, encoding="utf-8").read()
    start = text.index("window.ANALYTICS=") + len("window.ANALYTICS=")
    analytics = json.loads(text[start:text.index(";\n", start)])
    return {f["properties"]["id"]: f["properties"]["starts"] for f in analytics["hex"]["features"]}

def load_snapshots():
    result = []
    for name in sorted(os.listdir(SNAP_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(SNAP_DIR, name)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                t = data["last_updated"]
                bikes = data["data"]["bikes"]
                result.append((t, bikes))
        except Exception:
            continue
    return result

def classify_zone(bikes, zone, stops, demand):
    lons = [b["lon"] for b in bikes]
    lats = [b["lat"] for b in bikes]

    pts = gpd.GeoSeries(gpd.points_from_xy(lons, lats), crs=4326).to_crs(METRIC_CRS)
    outside = ~pts.within(zone)
    distance = pts.distance(zone)

    for b, o, d in zip(bikes, outside, distance):
        b["outside"] = bool(o)
        b["dist_m"] = round(d)

    # nearest bus stop for every vehicle
    if stops is not None and len(stops):
        near = gpd.sjoin_nearest(gpd.GeoDataFrame(geometry=pts), stops, how="left", distance_col="stop_dist_m")
        near = near[~near.index.duplicated()]          # two stops at the same distance
        for b, sd, sn in zip(bikes, near.stop_dist_m, near.stop_name):
            b["stop_dist_m"] = round(sd)
            b["stop_name"] = sn
    else:
        for b in bikes:
            b["stop_dist_m"] = None
            b["stop_name"] = ""

    # demand in the vehicle's hexagon (no hexagon in the data = almost no trips there)
    for b in bikes:
        if demand is None:
            b["demand"] = None
        else:
            b["demand"] = demand.get(h3.latlng_to_cell(b["lat"], b["lon"], H3_RES), 0)

    return bikes

def address(b):
    return(round(b["lat"], 6), round(b["lon"], 6), b["vehicle_type_id"])

def meters(a, b):
    dy = (a["lat"] - b["lat"]) * 111_000
    dx = (a["lon"] - b["lon"]) * 111_000 * math.cos(math.radians(a["lat"]))
    
    return math.hypot(dx, dy)

def match(old, new, fuzzy):
    book = defaultdict(list)
    pairs = {}

    for i, b in enumerate(old):
        book[address(b)].append(i)

    for j, b in enumerate(new):
        found = book[address(b)]
        if found:
            pairs[j] = found.pop()

    used_old = set(pairs.values())
    left_old = [i for i in range(len(old)) if i not in used_old]

    if fuzzy:
        left_new = [j for j in range(len(new)) if j not in pairs]

        candidates = []
        for i in left_old:
            for j in left_new:
                if old[i]["vehicle_type_id"] != new[j]["vehicle_type_id"]:
                    continue
                d = meters(old[i], new[j])
                if d < MATCH_M:
                    candidates.append((d, i, j))

        candidates.sort()
        for d, i, j in candidates:
            if i in used_old or j in pairs:
                continue
            pairs[j] = i
            used_old.add(i)

    return pairs

def track(snaps):
    prev = []
    prev_t = 0
    next_id = 1

    for t, bikes in snaps:
        gap = t - prev_t
        pairs = match(prev, bikes, gap <= 300)

        for j, b in enumerate(bikes):
            if j in pairs:
                old = prev[pairs[j]]
                b["track_id"] = old["track_id"]
                b["first_seen"] = old["first_seen"]
                jump = b["current_fuel_percent"] - old["current_fuel_percent"]
                b["serviced"] = old["serviced"] or jump > 0.3
            else:
                b["track_id"] = next_id
                next_id += 1
                b["first_seen"] = t
                b["serviced"] = False

        prev = bikes
        prev_t = t
    return prev, t


def write_live(bikes, t):
    out = []
    for b in bikes:
        if not b["abandoned"]:
            continue
        out.append({
            "lat": b["lat"],
            "lng": b["lon"],
            "start": datetime.fromtimestamp(b["first_seen"], LISBON).strftime("%Y-%m-%dT%H:%M:%S"),
            "dist_to_station_m": b["dist_m"],
            "battery": b["current_fuel_percent"],
            "serviced_at": datetime.fromtimestamp(t, LISBON).strftime("%Y-%m-%dT%H:%M:%S") if b["serviced"] else None,
            "reserved_at": None,
            "demand": b["demand"],
            "stop_dist_m": b["stop_dist_m"],
            "stop_name": b["stop_name"],
        })
    live = {"updated": t, "bikes": out}
    tmp = "data/live.js.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.LIVE = " + json.dumps(live) + ";")
    os.replace(tmp, "data/live.js")
    return len(out)


zone = load_zone()
stops = load_stops()
demand = load_demand()

while True:
    try:
        snaps = load_snapshots()
        bikes, t = track(snaps)
        bikes = classify_zone(bikes, zone, stops, demand)
        for b in bikes:
            b["minutes"] = round((t - b["first_seen"]) / 60)
            b["abandoned"] = b["outside"] and b["minutes"] > ABANDON_TIME and not b["is_reserved"]
        n = write_live(bikes, t)
        print(f"{datetime.now():%H:%M:%S}  snapshots: {len(snaps)}  abandoned now: {n}")
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(60 - time.time() % 60 + 10)