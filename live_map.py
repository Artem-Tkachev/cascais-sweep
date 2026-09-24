import json
import os
import math
from datetime import datetime
import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union
from collections import defaultdict

METRIC_CRS = 3763
BUFFER_M = 30
ABANDON_TIME = 120
MATCH_M = 5
SNAP_DIR = "data/snapshots"
#SNAP_DIR = "data/snapshots copy"
STATIONS_FILE = "data/station_information.json"

def load_zone():
    stations_raw = json.load(open(STATIONS_FILE))["data"]["stations"]
    stations = gpd.GeoDataFrame(
        [{"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in stations_raw],
        geometry=[shape(s["station_area"]) for s in stations_raw], crs=4326)
    station_m = stations.to_crs(METRIC_CRS)
    allowed_zone = unary_union(station_m.buffer(BUFFER_M))
    return allowed_zone

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

def classify_zone(bikes, zone):
    lons = [b["lon"] for b in bikes]
    lats = [b["lat"] for b in bikes]

    pts = gpd.GeoSeries(gpd.points_from_xy(lons, lats), crs=4326).to_crs(METRIC_CRS)
    outside = ~pts.within(zone)
    distance = pts.distance(zone)

    for b, o, d in zip(bikes, outside, distance):
        b["outside"] = bool(o)
        b["dist_m"] = round(d)

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





zone = load_zone()
snaps = load_snapshots()

bikes, t = track(snaps)

bikes = classify_zone(bikes, zone)

for b in bikes:
    b["minutes"] = round((t - b["first_seen"]) / 60)
    if b["outside"] and b["minutes"] > ABANDON_TIME and not b["is_reserved"]:
        b["abandoned"] = True
    else:
        b["abandoned"] = False

print(sum(b["abandoned"] for b in bikes))
print(max(b["minutes"] for b in bikes))