"""
Шаг 2: аналитика поверх detect.py.

  - KPI спроса/предложения по шестиугольникам H3 (~170 м)
  - кластеры брошенных -> места для новых станций
  - сценарии: что даст дополнительный вечерний рейс сбора
  - текущая работа оператора (когда техники собирают самокаты)

Запуск: python detect.py  затем  python analytics.py   -> data/data.js для сайта
"""
import json, math
import numpy as np
import pandas as pd
import geopandas as gpd
import h3
from sklearn.cluster import DBSCAN

DATA = "data"
H3_RES = 9
CAPACITY = 18          # самокатов в фургон: João — 15–20, берём 18
DETOUR = 1.35          # коэффициент "дорога длиннее прямой"
SPEED_KMH = 20         # средняя скорость фургона в городе
STOP_MIN = 3           # минут на погрузку одного самоката

ev = pd.read_excel(f"{DATA}/copy_viagens.xlsx")        # события
trips = pd.read_excel(f"{DATA}/copy_cartoes.xlsx")     # поездки
# время в данных в UTC -> лиссабонское (как в detect.py)
to_local = lambda s: s.dt.tz_localize("UTC").dt.tz_convert("Europe/Lisbon").dt.tz_localize(None)
ev["timestamp"] = to_local(ev["timestamp"])
trips["start_time"] = to_local(trips["start_time"]); trips["end_time"] = to_local(trips["end_time"])
ab = pd.read_pickle(f"{DATA}/abandoned.pkl")
parks = pd.read_pickle(f"{DATA}/parks.pkl")
stations = gpd.read_file(f"{DATA}/stations.geojson")
DAYS = (ev.timestamp.max() - ev.timestamp.min()).total_seconds() / 86400

# ------------------------------------------------------------------ поездки
fake = (trips.duration < 60) | (trips.cleaned_distance < 0.05)
trips_ok = trips[~fake].dropna(subset=["start_latitude","start_longitude","end_latitude","end_longitude","start_time"]).copy()

# ------------------------------------------------------------------ H3 KPI
def cell(lat, lng):
    return h3.latlng_to_cell(lat, lng, H3_RES)

trips_ok["h_start"] = [cell(a, b) for a, b in zip(trips_ok.start_latitude, trips_ok.start_longitude)]
trips_ok["h_end"] = [cell(a, b) for a, b in zip(trips_ok.end_latitude, trips_ok.end_longitude)]
ab["h"] = [cell(a, b) for a, b in zip(ab.lat, ab.lng)]

k = pd.DataFrame({
    "starts": trips_ok.h_start.value_counts(),
    "ends": trips_ok.h_end.value_counts(),
    "abandoned": ab.h.value_counts(),
}).fillna(0)
k["hours_avg"] = ab.groupby("h").abandoned_hours.mean()
k["hours_total"] = ab.groupby("h").abandoned_hours.sum()
k = k.fillna(0)
k["net"] = k.ends - k.starts                       # + копятся, - не хватает
k["abandon_rate"] = np.where(k.ends > 0, k.abandoned / k.ends.clip(lower=1), 0)
k = k[(k.starts + k.ends + k.abandoned) >= 3]      # убираем пустые клетки

hex_features = []
for h, r in k.iterrows():
    ring = [[round(lng, 6), round(lat, 6)] for lat, lng in h3.cell_to_boundary(h)]
    ring.append(ring[0])
    hex_features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                         "properties": {"id": h, **{c: round(float(r[c]) / (DAYS if c in ("starts", "ends", "abandoned", "net") else 1), 3)
                                                     if c in ("starts", "ends", "abandoned", "net") else round(float(r[c]), 3)
                                                     for c in k.columns}}})
# starts/ends/abandoned/net даны В СРЕДНЕМ ЗА ДЕНЬ

# ------------------------------------------------------------------ почасовые профили
t = pd.date_range(ev.timestamp.min().ceil("15min"), ev.timestamp.max().floor("15min"), freq="15min")
a0, a1 = ab.abandoned_from.values, ab.end.values
concurrent = pd.Series([int(((a0 <= x) & (a1 > x)).sum()) for x in t.values], index=t)
pickups = ev[ev.event_types == "maintenance_pick_up"]
hourly = {
    "hour": list(range(24)),
    "trips": (trips_ok.start_time.dt.hour.value_counts().reindex(range(24), fill_value=0) / DAYS).round(1).tolist(),
    "abandoned_new": (ab.start.dt.hour.value_counts().reindex(range(24), fill_value=0) / DAYS).round(2).tolist(),
    "abandoned_now": concurrent.groupby(concurrent.index.hour).mean().reindex(range(24)).round(1).tolist(),
    "pickups": (pickups.timestamp.dt.hour.value_counts().reindex(range(24), fill_value=0) / DAYS).round(1).tolist(),
}

# ------------------------------------------------------------------ кластеры -> новые станции
pts = gpd.GeoSeries(gpd.points_from_xy(ab.lng, ab.lat), crs=4326).to_crs(3763)
X = np.c_[pts.x, pts.y]
ab["cluster"] = DBSCAN(eps=60, min_samples=6).fit_predict(X)
st_m = stations.to_crs(3763)
cands = []
for c, g in ab[ab.cluster >= 0].groupby("cluster"):
    cx, cy = np.median(X[g.index, 0]), np.median(X[g.index, 1])
    d = np.hypot(X[:, 0] - cx, X[:, 1] - cy)
    covered = int((d <= 45).sum())             # станция ~15 м + зона 30 м
    centre = gpd.GeoSeries(gpd.points_from_xy([cx], [cy]), crs=3763)
    lonlat = centre.to_crs(4326).iloc[0]
    cands.append({"lat": round(lonlat.y, 6), "lng": round(lonlat.x, 6), "cases": len(g), "covered": covered,
                  "hours": round(float(ab.loc[d <= 45, "abandoned_hours"].sum()), 1),
                  "nearest_station_m": round(float(st_m.distance(centre.iloc[0]).min())),
                  "devices": int(g.device_id.nunique())})
cands = sorted(cands, key=lambda c: -c["covered"])[:8]
for i, c in enumerate(cands, 1):
    c["rank"] = i

# ------------------------------------------------------------------ маршрут (та же логика, что в браузере)
def hav_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h)) * DETOUR

def tour_len(depot, pts, order):
    seq = [depot] + [pts[i] for i in order] + [depot]
    return sum(hav_km(seq[i], seq[i + 1]) for i in range(len(seq) - 1))

def improve(depot, pts, loop):
    improved = True
    while improved:
        improved = False
        for i in range(len(loop) - 1):
            for m in range(i + 2, len(loop) + 1):
                new = loop[:i] + loop[i:m][::-1] + loop[m:]
                if tour_len(depot, pts, new) < tour_len(depot, pts, loop) - 1e-9:
                    loop, improved = new, True
    return loop

def nearest(depot, pts, ids):
    left, loop, cur = set(ids), [], depot
    while left:
        j = min(left, key=lambda i: hav_km(cur, pts[i])); loop.append(j); left.remove(j); cur = pts[j]
    return loop

def plan(depot, pts):
    """sweep: делим точки на заезды секторами вокруг склада (по CAPACITY), внутри - ближайший сосед + 2-opt"""
    if not pts:
        return [], 0.0
    ang = [math.atan2(p[0] - depot[0], (p[1] - depot[1]) * math.cos(math.radians(depot[0]))) for p in pts]
    order = sorted(range(len(pts)), key=lambda i: ang[i])
    n = math.ceil(len(pts) / CAPACITY); size = math.ceil(len(pts) / n)
    best, best_len = None, float("inf")
    for shift in range(0, len(order), max(1, len(order) // 12)):
        rot = order[shift:] + order[:shift]
        loops = [improve(depot, pts, nearest(depot, pts, rot[k * size:(k + 1) * size])) for k in range(n)]
        L = sum(tour_len(depot, pts, l) for l in loops)
        if L < best_len:
            best, best_len = loops, L
    return [l for l in best if l], best_len

def naive(depot, pts, times):
    """как без инструмента: по порядку появления, по CAPACITY за заезд"""
    order = list(np.argsort(times))
    loops = [order[i:i + CAPACITY] for i in range(0, len(order), CAPACITY)]
    return sum(tour_len(depot, pts, l) for l in loops)

# склад муниципалитета: координаты от João Silva (Cascais Próxima), Estrada de Manique 1830, Alcoitão
DEPOT = [38.736065, -9.386573]
SHIFT = (9, 18)            # смена 09:00–18:00
LUNCH = (13, 14)           # обед (допущение: 13–14)

# ------------------------------------------------------------------ модель: заберёт ли самокат пользователь сам
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, StratifiedKFold
MODEL_FEATURES = ["battery", "dist_to_station_m", "demand", "hour_sin", "hour_cos"]

def model_features(df):
    hr = df.start.dt.hour + df.start.dt.minute / 60
    return pd.DataFrame({
        "battery": df.battery.fillna(0.5),
        "dist_to_station_m": df.dist_to_station_m,
        "demand": [float((k.starts / DAYS).get(cell(a, b), 0)) for a, b in zip(df.lat, df.lng)],
        "hour_sin": np.sin(hr / 24 * 2 * np.pi),       # час суток как точка на циферблате
        "hour_cos": np.cos(hr / 24 * 2 * np.pi),
    })

known = ab[ab.end_event.isin(["trip_start", "maintenance_pick_up"])]
Xm, ym = model_features(known), (known.end_event == "trip_start").astype(int)
mu, sd = Xm.mean(), Xm.std()
Xs = (Xm - mu) / sd                                     # стандартизация: все признаки в одном масштабе
cv = StratifiedKFold(5, shuffle=True, random_state=0)
model_acc = float(cross_val_score(LogisticRegression(), Xs, ym, cv=cv, scoring="accuracy").mean())
clf = LogisticRegression().fit(Xs, ym)
model = {"features": MODEL_FEATURES, "mean": mu.round(6).tolist(), "std": sd.round(6).tolist(),
         "coef": clf.coef_[0].round(6).tolist(), "intercept": round(float(clf.intercept_[0]), 6),
         "accuracy": round(model_acc, 3), "baseline": round(float(max(ym.mean(), 1 - ym.mean())), 3), "n": int(len(ym))}

# ------------------------------------------------------------------ симуляция муниципального фургона (смена 9–18)
UNLOAD_MIN = 10            # разгрузка на складе после заезда (допущение)
W = {"time": 3, "dist": 2, "self": 1.5, "stop": 1.5}   # веса по умолчанию (решение Артёма после ответа João)

def simulate_shift(routing="opt", shift=None, lunch=None):
    """Каждый рабочий день фургон делает заезды: берёт до CAPACITY самых важных брошенных самокатов,
    объезжает их (routing='opt' — наш маршрут, 'naive' — по порядку появления), возвращается и планирует снова."""
    SHIFT_, LUNCH_ = shift or SHIFT, lunch if lunch is not None else LUNCH
    ends = ab.end.copy()
    km_total, collected, loops_n = 0.0, 0, 0
    days = pd.date_range(ab.start.min().normalize(), ab.end.max().normalize())
    workdays = [d for d in days if d.dayofweek < 5]                       # смена по будням (допущение)
    for d in workdays:
        t, shift_end = d + pd.Timedelta(hours=SHIFT_[0]), d + pd.Timedelta(hours=SHIFT_[1])
        while t < shift_end:
            if LUNCH_[0] <= t.hour < LUNCH_[1]:
                t = d + pd.Timedelta(hours=LUNCH_[1]); continue
            live = ab[(ab.abandoned_from <= t) & (ends > t) & ~(ab.reserved_at <= t)]
            if live.empty:
                t += pd.Timedelta(minutes=15); continue
            hours = (t - live.start).dt.total_seconds() / 3600
            score = (W["time"] * np.minimum(hours / 12, 1) + W["dist"] * np.minimum(live.dist_to_station_m / 300, 1)
                     + W["self"] * (1 - live.p_self) + W["stop"] * live.stop_f).values
            limit = (d + pd.Timedelta(hours=LUNCH_[0]) if t.hour < LUNCH_[0] and LUNCH_[0] > SHIFT_[0] else shift_end)
            budget = (limit - t).total_seconds() / 60 - UNLOAD_MIN
            p_all = list(zip(live.lat, live.lng))
            # отбор как на сайте: жадная вставка по «балл / минуты крюка», пока влезает во время и вместимость
            loop, left = [], set(range(len(p_all)))
            while left and len(loop) < CAPACITY:
                best = None
                for i in left:
                    for k in range(len(loop) + 1):
                        a_ = p_all[loop[k - 1]] if k else DEPOT
                        b_ = p_all[loop[k]] if k < len(loop) else DEPOT
                        det = hav_km(a_, p_all[i]) + hav_km(p_all[i], b_) - hav_km(a_, b_)
                        r = score[i] / (det / SPEED_KMH * 60 + STOP_MIN)
                        if best is None or r > best[0]:
                            best = (r, i, k)
                _, i, k = best
                cand = loop[:k] + [i] + loop[k:]
                left.discard(i)
                if tour_len(DEPOT, p_all, cand) / SPEED_KMH * 60 + len(cand) * STOP_MIN <= budget:
                    loop = cand
            if not loop:
                t = limit if budget < 30 else t + pd.Timedelta(minutes=15); continue
            if routing == "opt":
                loop = improve(DEPOT, p_all, loop)
            else:
                loop = sorted(loop, key=lambda i: live.abandoned_from.values[i])   # тот же набор, объезд по порядку появления
            p = p_all
            L = tour_len(DEPOT, p, loop)
            dur = L / SPEED_KMH * 60 + len(loop) * STOP_MIN + UNLOAD_MIN
            take = live
            cur, clock = DEPOT, t
            for i in loop:
                clock += pd.Timedelta(minutes=hav_km(cur, p[i]) / SPEED_KMH * 60 + STOP_MIN); cur = p[i]
                idx = take.index[i]
                ends.loc[idx] = min(ends.loc[idx], clock.floor("s"))
            t = t + pd.Timedelta(minutes=dur)
            km_total += L; collected += len(loop); loops_n += 1
    hrs = ((ends - ab.abandoned_from).dt.total_seconds().clip(lower=0) / 3600)
    wd = len(workdays)
    return {"name": routing, "abandoned_hours": round(float(hrs.sum())), "median_h": round(float(hrs.median()), 1),
            "mean_h": round(float(hrs.mean()), 1), "collected_per_day": round(collected / wd, 1),
            "km_per_day": round(km_total / wd, 1), "loops_per_day": round(loops_n / wd, 1),
            "km_per_vehicle": round(km_total / max(collected, 1), 2)}

# ------------------------------------------------------------------ остановки транспорта: «мешает пешеходам»
# stops.csv (TML, формат GTFS): stop_id, stop_name, stop_lat, stop_lon ...
import os
ab["stop_dist_m"], ab["stop_name"], stop_stats = np.nan, "", None
if os.path.exists(f"{DATA}/stops.csv"):
    stops = pd.read_csv(f"{DATA}/stops.csv", low_memory=False).dropna(subset=["stop_lat", "stop_lon"])
    # только остановки рядом с Cascais (рамка вокруг наших данных), чтобы не таскать всю агломерацию
    box = stops[stops.stop_lat.between(ab.lat.min() - .02, ab.lat.max() + .02) & stops.stop_lon.between(ab.lng.min() - .02, ab.lng.max() + .02)]
    st_pts = gpd.GeoDataFrame(box[["stop_name"]], geometry=gpd.points_from_xy(box.stop_lon, box.stop_lat), crs=4326).to_crs(3763)
    ab_pts = gpd.GeoDataFrame(ab[[]], geometry=gpd.points_from_xy(ab.lng, ab.lat), crs=4326).to_crs(3763)
    near = gpd.sjoin_nearest(ab_pts, st_pts, how="left", distance_col="stop_dist_m")
    near = near[~near.index.duplicated()]                     # если две остановки на одинаковом расстоянии
    ab["stop_dist_m"], ab["stop_name"] = near.stop_dist_m.round(0), near.stop_name.fillna("")
    close = ab[ab.stop_dist_m <= 20]
    stop_stats = {"stops_in_area": int(len(box)), "cases_near_stop": int(len(close)),
                  "share_near_stop": round(len(close) / len(ab), 3),
                  "median_hours_near_stop": round(float(close.abandoned_hours.median()), 1) if len(close) else 0,
                  "stop_hours_total": round(float(close.abandoned_hours.sum()))}
# фактор «у остановки»: 1 ближе 20 м, плавно до 0 к 40 м (как на сайте)
ab["stop_f"] = ((40 - ab.stop_dist_m) / 20).clip(0, 1).fillna(0)

# шанс «заберёт пользователь сам» для каждого случая (модель выше)
ab["p_self"] = clf.predict_proba((model_features(ab) - mu) / sd)[:, 1]

# ------------------------------------------------------------------ запуск симуляций
serviced = ab[ab.serviced_at.notna() & (ab.serviced_at >= ab.abandoned_from)]
hrs0 = ab.abandoned_hours
scenarios = [{"name": "now", "abandoned_hours": round(float(hrs0.sum())), "median_h": round(float(hrs0.median()), 1),
              "mean_h": round(float(hrs0.mean()), 1), "collected_per_day": 0, "km_per_day": 0, "loops_per_day": 0, "km_per_vehicle": 0},
             simulate_shift("naive"), simulate_shift("opt")]
# как сейчас у муниципалитета: один заезд в день ~2 ч (João: ~10 самокатов за 2 ч) — наш отбор и маршрут в том же окне
one = simulate_shift("opt", shift=(10, 12), lunch=(0, 0)); one["name"] = "opt_2h"
scenarios.insert(1, one)
FINE_EUR = 4.5            # штраф оператору за каждый собранный муниципалитетом самокат (João Silva)
TODAY_PER_DAY = 10        # сейчас: ~10 самокатов за один 2-часовой заезд в день (João Silva)

summary = {
    "days": round(DAYS, 1), "stations": len(stations), "vehicles": int(ev.device_id.nunique()),
    "trips_total": len(trips), "trips_fake_share": round(float(fake.mean()), 3), "trips_per_day": round(len(trips_ok) / DAYS),
    "abandoned_cases": len(ab), "abandoned_per_day": round(len(ab) / DAYS, 1),
    "abandoned_devices": int(ab.device_id.nunique()),
    "median_hours": round(float(ab.abandoned_hours.median()), 1),
    "total_hours": round(float(ab.abandoned_hours.sum())),
    "mean_concurrent": round(float(concurrent.mean()), 1), "max_concurrent": int(concurrent.max()),
    "median_dist_m": round(float(ab.dist_to_station_m.median())),
    "end_by_pickup": int((ab.end_event == "maintenance_pick_up").sum()),
    "end_by_trip": int((ab.end_event == "trip_start").sum()),
    "parks_outside_share": round(float(parks.outside.mean()), 3),
    "pickups_per_day": round(len(pickups) / DAYS),
    "pickups_peak_share": round(float(pickups.timestamp.dt.hour.between(6, 13).mean()), 3),    # 6:00–13:59 по Лиссабону
    "serviced_left_cases": int(len(serviced)), "serviced_left_hours": round(float(serviced.abandoned_hours.sum())),
    "serviced_left_median_after_h": round(float(((serviced.end - serviced.serviced_at).dt.total_seconds() / 3600).median()), 1) if len(serviced) else 0,
    "depot": DEPOT, "capacity": CAPACITY, "detour": DETOUR, "speed_kmh": SPEED_KMH, "stop_min": STOP_MIN,
    "shift": SHIFT, "lunch": LUNCH, "unload_min": UNLOAD_MIN, "weights": W,
    "fine_eur": FINE_EUR, "today_per_day": TODAY_PER_DAY,
}

out = {"summary": summary, "model": model, "hourly": hourly, "stations_suggested": cands, "scenarios": scenarios,
       "stop_stats": stop_stats, "hex": {"type": "FeatureCollection", "features": hex_features}}
json.dump(out, open(f"{DATA}/analytics.json", "w"), ensure_ascii=False)

# ------------------------------------------------------------------ один файл для сайта (работает двойным щелчком, без сервера)
abj = json.load(open(f"{DATA}/abandoned.json"))
starts_per_day = (k.starts / DAYS).to_dict()
for d, (_, r) in zip(abj, ab.iterrows()):
    d["demand"] = round(float(starts_per_day.get(cell(d["lat"], d["lng"]), 0)), 2)   # спрос в месте
    d["stop_dist_m"] = None if pd.isna(r.stop_dist_m) else float(r.stop_dist_m)
    d["stop_name"] = r.stop_name
stj = json.load(open(f"{DATA}/stations.geojson"))
with open(f"{DATA}/data.js", "w", encoding="utf-8") as f:
    f.write("window.ABANDONED=" + json.dumps(abj, ensure_ascii=False) + ";\n")
    f.write("window.STATIONS=" + json.dumps(stj) + ";\n")
    f.write("window.ANALYTICS=" + json.dumps(out, ensure_ascii=False) + ";\n")

if __name__ == "__main__":
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("ОСТАНОВКИ:", stop_stats)
    print("СЦЕНАРИИ:")
    for s in scenarios: print(s)
    print("МОДЕЛЬ:", model["accuracy"], "vs", model["baseline"])
    print("НОВЫЕ СТАНЦИИ:", [(c["covered"], c["cases"]) for c in cands])
