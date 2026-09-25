"""
Step 1: find abandoned scooters in Cascais.

Abandoned = parked more than 30 m from a station area for more than 120 minutes (definition from the brief).

Logic:
1. Build the "allowed zone": station polygons + 30 m.
2. For every scooter, walk through its events in time order and cut them into "parkings":
   a parking starts when the scooter is left (trip_end / provider_drop_off / trip_cancel)
   and ends when it is moved (trip_start / maintenance_pick_up / ...).
3. A parking outside the zone and longer than 120 minutes = an abandoned case.
   It counts as abandoned from (parking start + 120 min) until the parking ends.
"""
import json
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union

DATA = "data"
METRIC_CRS = 3763          # Portugal, coordinates in metres
BUFFER_M = 30
ABANDON_MIN = 120

# --- 1. Stations and the 30 m zone ------------------------------------------
st_raw = json.load(open(f"{DATA}/station_information.json"))["data"]["stations"]
stations = gpd.GeoDataFrame(
    [{"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in st_raw],
    geometry=[shape(s["station_area"]) for s in st_raw], crs=4326)
stations_m = stations.to_crs(METRIC_CRS)
allowed_zone = unary_union(stations_m.buffer(BUFFER_M))   # one shape: the whole allowed zone

# --- 2. Events and parkings --------------------------------------------------
ev = pd.read_excel(f"{DATA}/copy_viagens.xlsx")   # this is the EVENTS file (despite its name)
ev = ev.rename(columns={"battery %": "battery"})
# timestamps are UTC (confirmed by João Silva, Cascais Próxima) -> convert to Lisbon time
ev["timestamp"] = ev["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Europe/Lisbon").dt.tz_localize(None)
ev = ev.dropna(subset=["lat", "lng"]).sort_values(["device_id", "timestamp"])
DATA_END = ev["timestamp"].max()

# maintenance_pick_up is often Bird servicing ON THE SPOT (battery swap): a minute later provider_drop_off at the same place.
# So such a pickup ends the parking only if the scooter then ends up more than 50 m away (it was really taken away).
nxt = ev.groupby("device_id")[["lat", "lng"]].shift(-1)
dlat = np.radians(nxt.lat - ev.lat); dlng = np.radians(nxt.lng - ev.lng)
h = np.sin(dlat / 2) ** 2 + np.cos(np.radians(ev.lat)) * np.cos(np.radians(nxt.lat)) * np.sin(dlng / 2) ** 2
ev["moved_after_m"] = (2 * 6371000 * np.arcsin(np.sqrt(h))).fillna(1e9)   # no next event = treat as taken away
MOVE_M = 50

PARK_START = {"trip_end", "provider_drop_off", "trip_cancel"}
PARK_END = {"trip_start", "maintenance_pick_up", "decommissioned", "trip_leave_jurisdiction"}

rows = []
for dev, g in ev.groupby("device_id", sort=False):
    cur = None
    for r in g.itertuples(index=False):
        et = r.event_types
        if et in PARK_START and cur is None:
            cur = dict(device_id=dev, start=r.timestamp, lat=r.lat, lng=r.lng,
                       battery=r.battery, start_event=et)
        elif cur is not None:
            # remember WHEN an event first happened (the website compares it with the slider time)
            if et == "comms_lost" and "comms_lost_at" not in cur:
                cur["comms_lost_at"] = r.timestamp
            if r.vehicle_state == "non_operational" and "broken_at" not in cur:
                cur["broken_at"] = r.timestamp
            if et == "reservation_start":
                cur["reserved_at"] = r.timestamp
            if et == "reservation_cancel":
                cur.pop("reserved_at", None)
            if et == "maintenance_pick_up" and r.moved_after_m <= MOVE_M:
                cur.setdefault("serviced_at", r.timestamp)       # Bird serviced it on the spot, the scooter stayed there
                continue
            if et in PARK_END:
                cur.update(end=r.timestamp, end_event=et)
                rows.append(cur); cur = None
                continue
    if cur is not None:                     # still there when the data ends
        cur.update(end=DATA_END, end_event="still_there")
        rows.append(cur)

parks = pd.DataFrame(rows)
parks["minutes"] = (parks["end"] - parks["start"]).dt.total_seconds() / 60

# outside the zone?
pts = gpd.GeoSeries(gpd.points_from_xy(parks.lng, parks.lat), crs=4326).to_crs(METRIC_CRS)
parks["outside"] = ~pts.within(allowed_zone).values
parks["dist_to_station_m"] = pts.distance(allowed_zone).values   # distance to the zone edge, 0 inside the zone

# --- 3. Abandoned -----------------------------------------------------------
ab = parks[parks.outside & (parks.minutes > ABANDON_MIN)].copy()
ab["abandoned_from"] = ab["start"] + pd.Timedelta(minutes=ABANDON_MIN)
ab["abandoned_hours"] = (ab["end"] - ab["abandoned_from"]).dt.total_seconds() / 3600
ab = ab.reset_index(drop=True)

parks.to_pickle(f"{DATA}/parks.pkl")
ab.to_pickle(f"{DATA}/abandoned.pkl")
# compact JSON for the website
for c in ["comms_lost_at", "broken_at", "reserved_at", "serviced_at"]:
    if c not in ab: ab[c] = pd.NaT
out = ab[["device_id","lat","lng","start","abandoned_from","end","end_event","abandoned_hours","dist_to_station_m","battery",
          "comms_lost_at","broken_at","reserved_at","serviced_at"]].copy()
for c in ["start","abandoned_from","end","comms_lost_at","broken_at","reserved_at","serviced_at"]:
    out[c] = out[c].dt.strftime("%Y-%m-%dT%H:%M:%S")
out = out.round({"lat":6,"lng":6,"abandoned_hours":2,"dist_to_station_m":0,"battery":2})
out.to_json(f"{DATA}/abandoned.json", orient="records")
stations.to_file(f"{DATA}/stations.geojson", driver="GeoJSON")

# --- Summary ----------------------------------------------------------------
if __name__ == "__main__":
    days = (DATA_END - ev.timestamp.min()).total_seconds() / 86400
    print(f"Period: {ev.timestamp.min():%d.%m} – {DATA_END:%d.%m.%Y} ({days:.1f} days)")
    print(f"Stations: {len(stations)}, scooters: {ev.device_id.nunique()}")
    print(f"Parkings: {len(parks)}; outside the zone: {parks.outside.mean():.0%}")
    print(f"Abandoned cases (>30 m and >120 min): {len(ab)}  (~{len(ab)/days:.0f} per day)")
    print(f"Unique scooters abandoned at least once: {ab.device_id.nunique()}")
    print("Hours abandoned after the first 2 h:", ab.abandoned_hours.describe().round(1).to_dict())
    print("How it ended:", ab.end_event.value_counts().to_dict())
    print("Distance to the nearest zone, m:", ab.dist_to_station_m.describe().round(0).to_dict())
