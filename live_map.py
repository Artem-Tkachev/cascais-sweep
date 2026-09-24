import json
import os
import math
from datetime import datetime
import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union

METRIC_CRS = 3763
BUFFER_M = 30
ABANDON_TIME = 120
MATCH_M = 5
#SNAP_DIR = "data/snapshots"
SNAP_DIR = "data/snapshots copy"
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

    result = []

    for b, o, d in zip(bikes, outside, distance):
        b["outside"] = bool(o)
        b["dist_m"] = round(d)

    return bikes

zone = load_zone()
snaps = load_snapshots()

t, bikes = snaps[-1]
bikes = classify_zone(bikes, zone)



print(zone.geom_type, round(zone.area))
print(len(snaps))
print(bikes)