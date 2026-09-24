"""
Шаг 1: поиск брошенных самокатов в Cascais.

Брошенный = стоит дальше 30 м от зоны станции дольше 120 минут (определение из брифа).

Логика:
1. Строим "разрешённую территорию": полигоны станций + 30 м.
2. Для каждого самоката идём по его событиям по времени и нарезаем "стоянки":
   стоянка начинается, когда самокат оставили (trip_end / provider_drop_off / trip_cancel),
   и заканчивается, когда его сдвинули (trip_start / maintenance_pick_up / ...).
3. Стоянка вне зоны и длиннее 120 минут = случай брошенного самоката.
   Брошенным он считается с момента (начало стоянки + 120 мин) до конца стоянки.
"""
import json
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union

DATA = "data"
METRIC_CRS = 3763          # Португалия, координаты в метрах
BUFFER_M = 30
ABANDON_MIN = 120

# --- 1. Станции и зона 30 м -------------------------------------------------
st_raw = json.load(open(f"{DATA}/station_information.json"))["data"]["stations"]
stations = gpd.GeoDataFrame(
    [{"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in st_raw],
    geometry=[shape(s["station_area"]) for s in st_raw], crs=4326)
stations_m = stations.to_crs(METRIC_CRS)
allowed_zone = unary_union(stations_m.buffer(BUFFER_M))   # одна фигура: вся разрешённая территория

# --- 2. События и стоянки ---------------------------------------------------
ev = pd.read_excel(f"{DATA}/copy_viagens.xlsx")   # файл СОБЫТИЙ (несмотря на имя)
ev = ev.rename(columns={"battery %": "battery"})
# время в данных в UTC (подтвердил João Silva, Cascais Próxima) -> переводим в лиссабонское
ev["timestamp"] = ev["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Europe/Lisbon").dt.tz_localize(None)
ev = ev.dropna(subset=["lat", "lng"]).sort_values(["device_id", "timestamp"])
DATA_END = ev["timestamp"].max()

# maintenance_pick_up часто = обслуживание Bird НА МЕСТЕ (замена батареи): через минуту provider_drop_off в той же точке.
# Поэтому такой pickup закрывает стоянку, только если самокат потом оказался дальше 50 м (его реально увезли).
nxt = ev.groupby("device_id")[["lat", "lng"]].shift(-1)
dlat = np.radians(nxt.lat - ev.lat); dlng = np.radians(nxt.lng - ev.lng)
h = np.sin(dlat / 2) ** 2 + np.cos(np.radians(ev.lat)) * np.cos(np.radians(nxt.lat)) * np.sin(dlng / 2) ** 2
ev["moved_after_m"] = (2 * 6371000 * np.arcsin(np.sqrt(h))).fillna(1e9)   # нет следующего события = считаем, что увезли
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
            # запоминаем, КОГДА впервые случилось событие (на сайте сравниваем с текущим временем)
            if et == "comms_lost" and "comms_lost_at" not in cur:
                cur["comms_lost_at"] = r.timestamp
            if r.vehicle_state == "non_operational" and "broken_at" not in cur:
                cur["broken_at"] = r.timestamp
            if et == "reservation_start":
                cur["reserved_at"] = r.timestamp
            if et == "reservation_cancel":
                cur.pop("reserved_at", None)
            if et == "maintenance_pick_up" and r.moved_after_m <= MOVE_M:
                cur.setdefault("serviced_at", r.timestamp)       # Bird обслужил на месте, самокат остался стоять
                continue
            if et in PARK_END:
                cur.update(end=r.timestamp, end_event=et)
                rows.append(cur); cur = None
                continue
    if cur is not None:                     # стоит до конца данных
        cur.update(end=DATA_END, end_event="still_there")
        rows.append(cur)

parks = pd.DataFrame(rows)
parks["minutes"] = (parks["end"] - parks["start"]).dt.total_seconds() / 60

# вне зоны?
pts = gpd.GeoSeries(gpd.points_from_xy(parks.lng, parks.lat), crs=4326).to_crs(METRIC_CRS)
parks["outside"] = ~pts.within(allowed_zone).values
parks["dist_to_station_m"] = pts.distance(allowed_zone).values   # внутри зоны = 0

# --- 3. Брошенные ----------------------------------------------------------
ab = parks[parks.outside & (parks.minutes > ABANDON_MIN)].copy()
ab["abandoned_from"] = ab["start"] + pd.Timedelta(minutes=ABANDON_MIN)
ab["abandoned_hours"] = (ab["end"] - ab["abandoned_from"]).dt.total_seconds() / 3600
ab = ab.reset_index(drop=True)

parks.to_pickle(f"{DATA}/parks.pkl")
ab.to_pickle(f"{DATA}/abandoned.pkl")
# для сайта: компактный JSON
for c in ["comms_lost_at", "broken_at", "reserved_at", "serviced_at"]:
    if c not in ab: ab[c] = pd.NaT
out = ab[["device_id","lat","lng","start","abandoned_from","end","end_event","abandoned_hours","dist_to_station_m","battery",
          "comms_lost_at","broken_at","reserved_at","serviced_at"]].copy()
for c in ["start","abandoned_from","end","comms_lost_at","broken_at","reserved_at","serviced_at"]:
    out[c] = out[c].dt.strftime("%Y-%m-%dT%H:%M:%S")
out = out.round({"lat":6,"lng":6,"abandoned_hours":2,"dist_to_station_m":0,"battery":2})
out.to_json(f"{DATA}/abandoned.json", orient="records")
stations.to_file(f"{DATA}/stations.geojson", driver="GeoJSON")

# --- Сводка ---------------------------------------------------------------
if __name__ == "__main__":
    days = (DATA_END - ev.timestamp.min()).total_seconds() / 86400
    print(f"Период: {ev.timestamp.min():%d.%m} – {DATA_END:%d.%m.%Y} ({days:.1f} дней)")
    print(f"Станций: {len(stations)}, самокатов: {ev.device_id.nunique()}")
    print(f"Стоянок всего: {len(parks)}; из них вне зоны: {parks.outside.mean():.0%}")
    print(f"Брошенных случаев (>30 м и >120 мин): {len(ab)}  (~{len(ab)/days:.0f} в день)")
    print(f"Уникальных самокатов, хоть раз брошенных: {ab.device_id.nunique()}")
    print("Время простоя после 2 ч, часов:", ab.abandoned_hours.describe().round(1).to_dict())
    print("Чем закончился простой:", ab.end_event.value_counts().to_dict())
    print("Расстояние до ближайшей зоны, м:", ab.dist_to_station_m.describe().round(0).to_dict())
